from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..deps import get_db
from ...db.repository import (get_watchlist, add_to_watchlist,
                               remove_from_watchlist, find_known_ids)
from ...identifiers import clean_ids

router = APIRouter(prefix="/api/watchlist", tags=["Watchlist"])


class SymbolIn(BaseModel):
    symbol: str
    isin:   str = ""


@router.get("")
def list_watchlist(db: Session = Depends(get_db)):
    return [{"symbol": i.symbol, "active": i.active, "isin": i.isin or "",
             "wkn": i.wkn or "", "conid": i.conid or 0}
            for i in get_watchlist(db)]


@router.post("")
def add_symbol(body: SymbolIn, db: Session = Depends(get_db)):
    ids = clean_ids(body.isin) if body.isin else {}
    if body.isin and not ids["isin"]:
        raise HTTPException(400, "ISIN ungueltig (Format oder Pruefsumme)")
    if not ids:   # sonst aus bekanntem Portfolio-Snapshot uebernehmen
        ids = find_known_ids(db, body.symbol)
    i = add_to_watchlist(db, body.symbol, ids.get("isin", ""), ids.get("wkn", ""),
                         ids.get("conid", 0))
    return {"ok": True, "symbol": i.symbol, "isin": i.isin or "", "wkn": i.wkn or ""}


@router.delete("/{symbol}")
def remove_symbol(symbol: str, db: Session = Depends(get_db)):
    remove_from_watchlist(db, symbol)
    return {"ok": True, "symbol": symbol.upper()}
