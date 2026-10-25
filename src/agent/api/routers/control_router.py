from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone, date
import asyncio, logging

from ... import __version__

from ..deps import get_db, SessionLocal
from ...db import repository as repo
from ...settings import Settings
from ...ibkr.client import IBKRClient
from ...analytics import metrics
from ...analysis.analyser import analyse_portfolio, summarize_portfolio
from ...llm import provider_label

log = logging.getLogger(__name__)
router = APIRouter(tags=["Steuerung"])

_run_state: dict = {
    "running": False, "step": 0, "total": 6,
    "step_name": "", "run_id": None, "error": None,
}

STEPS = [
    "IBKR-Verbindung aufbauen",
    "Portfolio-Daten abrufen",
    "Marktdaten laden",
    "KI-Analyse",
    "Aktionen berechnen",
    "Ergebnis speichern",
]


def _set_step(i: int):
    _run_state["step"]      = i + 1
    _run_state["step_name"] = STEPS[i]
    log.info(f"[run {_run_state['run_id']}] Schritt {i+1}/{len(STEPS)}: {STEPS[i]}")


@router.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@router.get("/api/control/status")
def control_status():
    return {"status": "online", "version": __version__}


@router.get("/api/run/status")
def run_status():
    return {**_run_state}


async def _execute_run(run_id: int, db_factory) -> None:
    global _run_state
    _run_state.update({"running": True, "step": 0, "run_id": run_id, "error": None})
    db: Session = db_factory()
    s = Settings()

    try:
        # ── Schritt 1+2: IBKR (eigener Thread) ───────────────────
        _set_step(0)
        ibkr   = IBKRClient(s.ibkr_host, s.ibkr_port, s.ibkr_client_id, s.benchmark_symbol)
        _set_step(1)
        result = await ibkr.fetch()

        if result.error:
            raise RuntimeError(
                f"IBKR: {result.error} – "
                f"Laeuft TWS auf {s.ibkr_host}:{s.ibkr_port}? "
                f"API aktiviert? Trusted IP gesetzt?"
            )
        if not result.positions:
            raise RuntimeError(
                "Keine Positionen empfangen – Portfolio leer "
                "oder falscher Port (Live=7496, Paper=7497)?"
            )

        positions = result.positions
        account   = result.account

        # ── Schritt 3: Marktdaten (Kurshistorie aus IBKR) ─────────
        _set_step(2)
        for key, series in result.history.items():
            repo.upsert_price_bars(db, key, series)
        for p in positions:
            series = result.history.get(p.symbol)
            if series:
                p.metrics = metrics.summarize(series)
        if result.history_errors:
            log.warning(f"[run {run_id}] Kurshistorie unvollstaendig: "
                        f"{'; '.join(result.history_errors[:8])}")
        log.info(f"[run {run_id}] Kurshistorie fuer {sum(1 for p in positions if p.metrics)}"
                 f"/{len(positions)} Positionen")

        # ── Schritt 4: KI-Analyse ─────────────────────────────────
        _set_step(3)
        log.info(f"[run {run_id}] Analysiere {len(positions)} Positionen via {provider_label(s)}...")
        analyses = await analyse_portfolio(positions, s)
        weights  = {p.symbol: p.weight for p in positions}
        by_sym   = {p.symbol: p for p in positions}

        # ── Schritt 5: Aktionen aus Analysen ableiten ─────────────
        _set_step(4)
        actions = []
        for a in analyses:
            if a.action in ("SELL", "BUY"):
                actions.append({
                    "symbol":       a.symbol,
                    "action":       a.action,
                    "confidence":   a.confidence,
                    "rationale":    a.rationale,
                    "risk_level":   a.risk_level,
                    "conid":        by_sym[a.symbol].conid,
                    "isin":         by_sym[a.symbol].isin,
                    "wkn":          by_sym[a.symbol].wkn,
                    "approved":     False,
                    "executed":     False,
                    "risk_blocked": (
                        (a.risk_level == "HIGH" and a.confidence < 0.6)
                        or a.confidence < s.min_confidence
                        or (a.action == "BUY"
                            and weights.get(a.symbol, 0) * 100 >= s.max_position_pct)
                    ),
                })

        view, ki_summary = await summarize_portfolio(positions, analyses, s)
        ki_summary += f" {len(actions)} Aktionen vorgeschlagen."

        # ── Schritt 6: Speichern ──────────────────────────────────
        _set_step(5)
        repo.save_snapshots(db, run_id, [
            {"symbol": p.symbol, "quantity": p.quantity,
             "avg_cost": p.avg_cost, "current_price": p.current_price,
             "market_value": p.market_value, "unrealized_pnl": p.unrealized_pnl,
             "weight": p.weight, "currency": p.currency, "sector": p.sector,
             "conid": p.conid, "isin": p.isin, "wkn": p.wkn, "exchange": p.exchange,
             **{k: p.metrics.get(k) for k in ("ret_1m", "ret_3m", "ret_6m", "volatility",
                                              "high_52w", "low_52w")}}
            for p in positions
        ])
        if actions:
            repo.save_actions(db, run_id, actions)

        # Vollständige Analysen als JSON im raw_response speichern
        import json as _json
        raw_json = _json.dumps([
            {"symbol": a.symbol, "action": a.action,
             "confidence": a.confidence, "rationale": a.rationale,
             "risk_level": a.risk_level}
            for a in analyses
        ], ensure_ascii=False)

        net_liq = account.get("NetLiquidation",
                               sum(p.market_value for p in positions))
        cash    = account.get("TotalCashValue", 0.0)
        repo.upsert_daily_nav(
            db, nav_date=date.today(),
            net_liq=net_liq, cash=cash,
            equity=net_liq - cash, pos_count=len(positions),
        )
        repo.update_run_summary(
            db=db, run_id=run_id,
            summary=ki_summary, market_view=view,
            raw=raw_json,
        )

        _run_state["step"]      = len(STEPS)
        _run_state["step_name"] = "Abgeschlossen"
        log.info(f"[run {run_id}] Abgeschlossen ✓  {ki_summary}")

    except Exception as e:
        log.error(f"[run {run_id}] Fehler: {e}", exc_info=True)
        _run_state["error"] = str(e)
    finally:
        _run_state["running"] = False
        db.close()


@router.post("/api/run")
async def trigger_run(background_tasks: BackgroundTasks,
                      db: Session = Depends(get_db)):
    if _run_state["running"]:
        raise HTTPException(409, "Ein Run laeuft bereits")
    run = repo.create_run(db=db, market_view="running", summary="Laeuft...", raw="")
    background_tasks.add_task(_execute_run, run.id, SessionLocal)
    return {"ok": True, "run_id": run.id}


@router.post("/api/control/run-now")
async def run_now(background_tasks: BackgroundTasks,
                  db: Session = Depends(get_db)):
    return await trigger_run(background_tasks, db)
