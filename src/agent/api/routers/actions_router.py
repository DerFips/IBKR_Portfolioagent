from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging

from ..deps import get_db
from ...db.repository import (get_all_pending_actions, approve_action,
                               mark_executed, get_run, save_order)
from datetime import datetime, timezone
from sqlalchemy import func
from ...db.models import ActionRecord, PortfolioSnapshot, DailyNav, OrderRecord
from ...risk import size_order
from pydantic import BaseModel
from sqlalchemy import select, desc
from ...settings import Settings
from ...ibkr.client import IBKRClient

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/actions", tags=["Actions"])


@router.get("")
def pending_actions(db: Session = Depends(get_db)):
    return [
        {"id": a.id, "symbol": a.symbol, "action": a.action,
         "confidence": a.confidence, "rationale": a.rationale,
         "approved": a.approved, "executed": a.executed,
         "risk_blocked": a.risk_blocked,
         "conid": a.conid, "isin": a.isin, "wkn": a.wkn}
        for a in get_all_pending_actions(db)
    ]


def _plan(db, a: ActionRecord, s: Settings) -> dict:
    """Ordergroesse aus Depotwert, Limits und Cash (Stand des Runs, aus dem die Aktion stammt)."""
    snap = db.execute(select(PortfolioSnapshot).where(
        PortfolioSnapshot.run_id == a.run_id, PortfolioSnapshot.symbol == a.symbol)).scalars().first()
    nav = db.execute(select(DailyNav).order_by(desc(DailyNav.date)).limit(1)).scalar_one_or_none()
    price = snap.current_price if snap else 0.0
    held = snap.quantity if snap else 0.0
    plan = size_order(a.action, price, held, abs(snap.market_value) if snap else 0.0,
                      nav.net_liquidation if nav else 0.0, nav.cash if nav else 0.0,
                      s.max_position_pct, s.max_risk_pct_per_trade, s.stop_loss_pct)
    return {**plan, "price": price, "held": held, "symbol": a.symbol, "action": a.action,
            "nav": nav.net_liquidation if nav else 0.0, "cash": nav.cash if nav else 0.0,
            "dry_run": s.ibkr_dry_run}


@router.get("/{action_id}/preview")
def preview(action_id: int, db: Session = Depends(get_db)):
    a = db.get(ActionRecord, action_id)
    if not a:
        raise HTTPException(404, "Action nicht gefunden")
    return _plan(db, a, Settings())


class ExecuteIn(BaseModel):
    quantity: int | None = None      # nur Verringern erlaubt


@router.post("/{action_id}/approve")
def approve(action_id: int, db: Session = Depends(get_db)):
    a = approve_action(db, action_id)
    if not a:
        raise HTTPException(404, "Action nicht gefunden")
    log.info(f"Action {action_id} genehmigt: {a.action} {a.symbol}")
    return {"ok": True, "action_id": action_id,
            "message": f"{a.action} {a.symbol} genehmigt – bereit zur Ausfuehrung"}


@router.post("/{action_id}/execute")
async def execute(action_id: int, body: ExecuteIn | None = None, db: Session = Depends(get_db)):
    """Fuehrt eine genehmigte Aktion als IBKR-Order aus."""
    s = Settings()

    # Action laden
    a: ActionRecord = db.get(ActionRecord, action_id)
    if not a:
        raise HTTPException(404, "Action nicht gefunden")
    if not a.approved:
        raise HTTPException(400, "Action nicht genehmigt – zuerst genehmigen!")
    if a.executed:
        raise HTTPException(400, "Action bereits ausgefuehrt")
    if a.risk_blocked:
        raise HTTPException(400, "Action ist durch Risiko-Check geblockt")

    # Risiko-Check: Konfidenz-Schwelle
    if a.confidence < s.min_confidence:
        mark_executed(db, action_id, risk_blocked=True)
        raise HTTPException(400,
            f"Konfidenz {a.confidence:.0%} unter Minimum {s.min_confidence:.0%} "
            f"– Ausfuehrung verweigert")

    # Tageslimit fuer Orders (Dry-Run und echte zusammen, damit das Limit auch beim Testen greift)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)   # Zeitstempel sind UTC
    done_today = db.execute(select(func.count(OrderRecord.id)).where(OrderRecord.timestamp >= today)).scalar() or 0
    if done_today >= s.max_daily_trades:
        raise HTTPException(400, f"Tageslimit erreicht: {done_today}/{s.max_daily_trades} Orders heute "
                                 f"(MAX_DAILY_TRADES)")

    # Menge aus Depotwert/Limits/Cash; der Nutzer darf sie nur verringern
    plan = _plan(db, a, s)
    if plan["blocked"]:
        raise HTTPException(400, f"Keine Order moeglich: {plan['blocked']}")
    quantity = float(plan["quantity"])
    if body and body.quantity is not None:
        if not (1 <= body.quantity <= plan["quantity"]):
            raise HTTPException(400, f"Stueckzahl muss zwischen 1 und {plan['quantity']} liegen")
        quantity = float(body.quantity)

    log.info(f"Fuehre aus: {a.action} {quantity}x {a.symbol} "
             f"(dry_run={s.ibkr_dry_run})")

    # IBKR-Order via eigenem Thread
    ibkr   = IBKRClient(s.ibkr_host, s.ibkr_port, s.ibkr_client_id)
    result = await ibkr.place_order(
        symbol   = a.symbol,
        action   = a.action,
        quantity = quantity,
        dry_run  = s.ibkr_dry_run,
        conid    = a.conid or 0,
    )

    if result.error:
        raise HTTPException(500, f"Order fehlgeschlagen: {result.error}")

    # In DB speichern
    mark_executed(db, action_id, risk_blocked=False)
    save_order(
        db,
        symbol     = a.symbol,
        action     = a.action,
        quantity   = quantity,
        price      = plan["price"],
        commission = result.commission,
        fill_price = result.fill_price,
        status     = result.status,
        dry_run    = s.ibkr_dry_run,
        conid      = a.conid or 0,
        isin       = a.isin or "",
        wkn        = a.wkn or "",
    )

    msg = (f"[DRY-RUN] {a.action} {quantity}x {a.symbol} simuliert"
           if s.ibkr_dry_run else
           f"{a.action} {quantity}x {a.symbol} @ {result.fill_price} – {result.status}")
    log.info(msg)
    return {
        "ok":         True,
        "action_id":  action_id,
        "symbol":     a.symbol,
        "action":     a.action,
        "quantity":   quantity,
        "fill_price": result.fill_price,
        "status":     result.status,
        "dry_run":    s.ibkr_dry_run,
        "message":    msg,
    }
