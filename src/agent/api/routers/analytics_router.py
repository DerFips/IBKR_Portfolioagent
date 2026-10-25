from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..deps import get_db
from ...db.repository import get_latest_sentiments, get_nav_history

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.get("/nav")
def nav_history(days: int = Query(90, ge=7, le=365), db: Session = Depends(get_db)):
    rows = get_nav_history(db, days)
    return [{"date": str(r.date), "net_liquidation": r.net_liquidation,
             "cash": r.cash, "equity_value": r.equity_value,
             "position_count": r.position_count}
            for r in rows]


@router.get("/sentiments")
def sentiments(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    return get_latest_sentiments(db, limit)
