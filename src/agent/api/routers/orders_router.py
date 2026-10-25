from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..deps import get_db
from ...db.repository import get_orders

router = APIRouter(prefix="/api/orders", tags=["Orders"])


@router.get("")
def list_orders(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    return [
        {"id": o.id, "timestamp": o.timestamp.isoformat(),
         "symbol": o.symbol, "action": o.action, "quantity": o.quantity,
         "price": o.price, "fill_price": o.fill_price,
         "status": o.status, "dry_run": o.dry_run,
         "isin": o.isin or "", "wkn": o.wkn or "", "conid": o.conid or 0}
        for o in get_orders(db, limit)
    ]
