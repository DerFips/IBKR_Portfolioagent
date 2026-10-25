from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from ..deps import get_db
from ...db.repository import get_runs, get_run, get_latest_run, get_snapshots, get_actions

router = APIRouter(prefix="/api/runs", tags=["Runs"])


def _run_detail(r, db):
    return {
        "id":          r.id,
        "timestamp":   r.timestamp.isoformat(),
        "market_view": r.market_view,
        "summary":     r.summary,
        "positions": [
            {"symbol": s.symbol, "isin": s.isin, "wkn": s.wkn, "conid": s.conid,
             "quantity": s.quantity, "avg_cost": s.avg_cost,
             "current_price": s.current_price, "market_value": s.market_value,
             "unrealized_pnl": s.unrealized_pnl, "weight": s.weight,
             "currency": s.currency}
            for s in get_snapshots(db, r.id)
        ],
        "actions": [
            {"id": a.id, "symbol": a.symbol, "isin": a.isin, "wkn": a.wkn,
             "action": a.action,
             "confidence": a.confidence, "rationale": a.rationale,
             "risk_level": getattr(a, "risk_level", "MEDIUM"),
             "approved": a.approved, "executed": a.executed,
             "risk_blocked": a.risk_blocked}
            for a in get_actions(db, r.id)
        ],
    }


@router.get("")
def list_runs(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    return [{"id": r.id, "timestamp": r.timestamp.isoformat(),
             "market_view": r.market_view, "summary": r.summary}
            for r in get_runs(db, limit)]


@router.get("/latest")
def latest_run(db: Session = Depends(get_db)):
    r = get_latest_run(db)
    if not r:
        return {"id": None, "message": "Noch kein Agent-Run vorhanden"}
    return _run_detail(r, db)


@router.get("/{run_id}")
def run_detail(run_id: int, db: Session = Depends(get_db)):
    r = get_run(db, run_id)
    if not r:
        raise HTTPException(404, "Run nicht gefunden")
    return _run_detail(r, db)
