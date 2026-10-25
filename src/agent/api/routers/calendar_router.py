"""Terminkalender: Termine aus Analysen + manuelle Eintraege, Export als .ics."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...calendar_util import extract_events, to_ics
from ...db.models import CalendarEvent
from ...identifiers import isin_valid

router = APIRouter(prefix="/api/calendar", tags=["Kalender"])
KINDS = {"earnings", "dividend", "agm", "other"}


def sync_from_analysis(db: Session, isin: str, analysis_id: int, data: dict) -> int:
    """Zukuenftige analyse-erzeugte Termine dieser ISIN durch die der neuesten Analyse ersetzen."""
    db.execute(delete(CalendarEvent).where(CalendarEvent.isin == isin, CalendarEvent.source == "analysis",
                                           CalendarEvent.date >= date.today()))
    sym = (data.get("company") or {}).get("ticker") or ""
    events = extract_events(data)
    for e in events:
        db.add(CalendarEvent(isin=isin, symbol=sym, source="analysis", analysis_id=analysis_id, **e))
    db.commit()
    return len(events)


def _out(e: CalendarEvent) -> dict:
    return {"id": e.id, "date": e.date.isoformat(), "title": e.title, "kind": e.kind, "isin": e.isin or "",
            "symbol": e.symbol or "", "source": e.source, "approx": bool(e.approx), "note": e.note or "",
            "analysis_id": e.analysis_id}


@router.get("")
def list_events(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)):
    start = start or date.today() - timedelta(days=31)
    end = end or date.today() + timedelta(days=400)
    rows = db.execute(select(CalendarEvent).where(CalendarEvent.date >= start, CalendarEvent.date <= end)
                      .order_by(CalendarEvent.date, CalendarEvent.id)).scalars().all()
    return [_out(e) for e in rows]


class EventIn(BaseModel):
    date: date
    title: str = Field(min_length=1, max_length=200)
    kind: str = "other"
    isin: str = ""
    symbol: str = Field("", max_length=32)
    note: str = Field("", max_length=300)


@router.post("")
def add_event(body: EventIn, db: Session = Depends(get_db)):
    isin = body.isin.strip().upper()
    if isin and not isin_valid(isin):
        raise HTTPException(400, "ISIN ungueltig (Format oder Pruefsumme)")
    e = CalendarEvent(date=body.date, title=body.title.strip(), kind=body.kind if body.kind in KINDS else "other",
                      isin=isin, symbol=body.symbol.strip().upper(), source="manual", note=body.note)
    db.add(e); db.commit(); db.refresh(e)
    return _out(e)


@router.delete("/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    e = db.get(CalendarEvent, event_id)
    if not e:
        raise HTTPException(404, "Termin nicht gefunden")
    db.delete(e); db.commit()
    return {"ok": True}


@router.get("/export.ics")
def export_ics(db: Session = Depends(get_db)):
    rows = db.execute(select(CalendarEvent).where(CalendarEvent.date >= date.today() - timedelta(days=31))
                      .order_by(CalendarEvent.date)).scalars().all()
    return Response(to_ics(rows), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="portfolio-termine.ics"'})
