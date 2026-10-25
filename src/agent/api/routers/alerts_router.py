from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..deps import get_db
from ...db.repository import get_alerts, create_alert

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


class AlertIn(BaseModel):
    symbol: str
    condition: str
    threshold: float


@router.get("")
def list_alerts(db: Session = Depends(get_db)):
    return [{"id": a.id, "symbol": a.symbol, "condition": a.condition,
             "threshold": a.threshold, "triggered": a.triggered}
            for a in get_alerts(db)]


@router.post("")
def add_alert(body: AlertIn, db: Session = Depends(get_db)):
    a = create_alert(db, body.symbol, body.condition, body.threshold)
    return {"ok": True, "id": a.id}
