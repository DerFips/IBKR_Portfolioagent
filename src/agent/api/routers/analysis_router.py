"""Unternehmensanalyse per ISIN (Menue 'Analyse')."""
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..deps import get_db, SessionLocal
from ...analysis.company import analyse_company, diff_analyses
from ...analysis.report import build_pdf
from ...db.models import CompanyAnalysis, PortfolioSnapshot, WatchlistItem
from ...identifiers import isin_valid
from ...llm import LLMError
from ...settings import Settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analysis", tags=["Analyse"])

_job = {"running": False, "isin": None, "step": "", "error": None, "started": None}


class AnalysisIn(BaseModel):
    isin: str


def _hint(db: Session, isin: str) -> str:
    """Ticker aus eigenem Depot/Watchlist, falls die ISIN dort bekannt ist."""
    row = db.execute(select(PortfolioSnapshot).where(PortfolioSnapshot.isin == isin)
                     .order_by(desc(PortfolioSnapshot.id)).limit(1)).scalar_one_or_none()
    if row:
        return f"Ticker {row.symbol}, Waehrung {row.currency}"
    w = db.execute(select(WatchlistItem).where(WatchlistItem.isin == isin)).scalar_one_or_none()
    return f"Ticker {w.symbol}" if w else ""


async def _run(isin: str, hint: str) -> None:
    _job.update(running=True, isin=isin, step="Starte…", error=None, started=time.time())
    db = SessionLocal()
    try:
        s = Settings()
        data = await analyse_company(isin, hint, s, on_step=lambda m: _job.update(step=m))
        db.add(CompanyAnalysis(
            isin=isin, name=(data.get("company") or {}).get("name", "")[:128],
            provider=data["provider"], live=data["live"],
            payload=json.dumps(data, ensure_ascii=False),
            timestamp=datetime.now(timezone.utc)))
        db.commit()
        try:   # Termine (Zahlen, Hauptversammlung, Dividenden) in den Kalender uebernehmen
            from .calendar_router import sync_from_analysis
            row = db.execute(select(CompanyAnalysis).order_by(desc(CompanyAnalysis.id)).limit(1)).scalar_one()
            n = sync_from_analysis(db, isin, row.id, data)
            log.info(f"[{isin}] {n} Termine im Kalender")
        except Exception as e:
            log.warning(f"Kalender-Sync fehlgeschlagen: {e}")
        _job["step"] = "Fertig"
    except LLMError as e:
        _job["error"] = str(e)
    except Exception as e:
        log.error(f"Analyse {isin}: {e}", exc_info=True)
        _job["error"] = f"{type(e).__name__}: {e}"
    finally:
        _job["running"] = False
        db.close()


@router.post("")
async def start(body: AnalysisIn, background_tasks: BackgroundTasks,
                db: Session = Depends(get_db)):
    isin = body.isin.strip().upper()
    if not isin_valid(isin):
        raise HTTPException(400, "ISIN ungueltig (12 Zeichen, z.B. DE0007164600, Pruefsumme stimmt nicht)")
    if _job["running"]:
        raise HTTPException(409, f"Analyse fuer {_job['isin']} laeuft bereits")
    background_tasks.add_task(_run, isin, _hint(db, isin))
    return {"ok": True, "isin": isin}


@router.get("/status")
def status():
    return {**_job, "elapsed": int(time.time() - _job["started"]) if _job["running"] else 0}


@router.get("")
def history(limit: int = 30, db: Session = Depends(get_db)):
    rows = db.execute(select(CompanyAnalysis).order_by(desc(CompanyAnalysis.id))
                      .limit(min(limit, 100))).scalars().all()
    return [{"id": r.id, "isin": r.isin, "name": r.name, "live": r.live,
             "provider": r.provider, "timestamp": r.timestamp.isoformat()} for r in rows]


@router.get("/{analysis_id}")
def detail(analysis_id: int, db: Session = Depends(get_db)):
    r = db.get(CompanyAnalysis, analysis_id)
    if not r:
        raise HTTPException(404, "Analyse nicht gefunden")
    return {**json.loads(r.payload), "id": r.id, "timestamp": r.timestamp.isoformat()}


@router.get("/{analysis_id}/compare")
def compare(analysis_id: int, db: Session = Depends(get_db)):
    """Vergleich mit der vorherigen Analyse derselben ISIN (leer, wenn es keine gibt)."""
    cur = db.get(CompanyAnalysis, analysis_id)
    if not cur:
        raise HTTPException(404, "Analyse nicht gefunden")
    prev = db.execute(select(CompanyAnalysis).where(CompanyAnalysis.isin == cur.isin, CompanyAnalysis.id < cur.id)
                      .order_by(desc(CompanyAnalysis.id)).limit(1)).scalar_one_or_none()
    if not prev:
        return {"previous": None}
    return {"previous": {"id": prev.id, "timestamp": prev.timestamp.isoformat(), "live": prev.live},
            **diff_analyses(json.loads(prev.payload), json.loads(cur.payload))}


@router.get("/{analysis_id}/pdf")
def pdf(analysis_id: int, db: Session = Depends(get_db)):
    r = db.get(CompanyAnalysis, analysis_id)
    if not r:
        raise HTTPException(404, "Analyse nicht gefunden")
    data = {**json.loads(r.payload), "id": r.id, "timestamp": r.timestamp.isoformat()}
    name = "".join(ch for ch in (r.name or "Analyse") if ch.isascii() and ch.isalnum())[:30] or "Analyse"
    return Response(build_pdf(data), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="Analyse_{name}_{r.isin}_{r.timestamp:%Y-%m-%d}.pdf"'})
