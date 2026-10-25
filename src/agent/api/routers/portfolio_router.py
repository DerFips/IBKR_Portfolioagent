from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from ..deps import get_db
from ...db.models import AgentRun
from ...db.repository import get_snapshots

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])


@router.get("/latest")
def latest_portfolio(db: Session = Depends(get_db)):
    r = db.execute(
        select(AgentRun).order_by(desc(AgentRun.timestamp)).limit(1)
    ).scalar_one_or_none()
    if not r:
        return {"positions": [], "run_id": None}
    return {
        "run_id": r.id, "timestamp": r.timestamp.isoformat(),
        "market_view": r.market_view,
        "positions": [
            {"symbol": s.symbol, "quantity": s.quantity, "avg_cost": s.avg_cost,
             "current_price": s.current_price, "market_value": s.market_value,
             "unrealized_pnl": s.unrealized_pnl, "weight": s.weight,
             "currency": s.currency, "conid": s.conid, "isin": s.isin,
             "wkn": s.wkn, "exchange": s.exchange}
            for s in get_snapshots(db, r.id)
        ],
    }
