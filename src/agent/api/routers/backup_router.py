"""Datenbank-Backup: erstellen, herunterladen, importieren, loeschen."""
import asyncio
import logging
import os
import pathlib
import tempfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ... import backup as B
from ...settings import Settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backup", tags=["Backup"])


def _busy() -> str | None:
    from . import control_router, analysis_router
    if control_router._run_state.get("running"):
        return "Ein Run laeuft gerade"
    if analysis_router._job.get("running"):
        return "Eine Analyse laeuft gerade"
    return None


@router.get("")
def overview():
    s = Settings()
    return {"backups": B.list_backups(), "auto": {"enabled": s.backup_enabled, "hour": s.backup_hour, "keep": s.backup_keep},
            "note": "Gespeicherte API-Keys sind in Sicherungen verschluesselt; der Schluessel (.settings.key) ist nicht "
                    "enthalten. Nach einem Import auf einem anderen Rechner Keys neu eintragen."}


@router.post("/create")
async def create():
    path = await asyncio.to_thread(B.create_backup, "manual")
    return {"ok": True, "name": path.name, "size": path.stat().st_size}


@router.get("/download/{name}")
def download(name: str):
    try:
        p = B.resolve_backup(name)
    except B.BackupError as e:
        raise HTTPException(404, str(e))
    return FileResponse(p, media_type="application/gzip", filename=name)


@router.delete("/{name}")
def delete(name: str):
    try:
        B.resolve_backup(name).unlink()
    except B.BackupError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.post("/import")
async def import_backup(request: Request):
    """Roher Request-Body = Datei (.db oder .db.gz). Header X-Confirm-Import: yes ist Pflicht."""
    if request.headers.get("x-confirm-import") != "yes":
        raise HTTPException(400, "Bestaetigung fehlt (Header X-Confirm-Import: yes)")
    if (why := _busy()):
        raise HTTPException(409, f"Import nicht moeglich: {why}")
    fd, tmp = tempfile.mkstemp(suffix=".upload")
    size = 0
    try:
        with os.fdopen(fd, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > B.MAX_IMPORT_BYTES:
                    raise HTTPException(413, "Datei zu gross")
                f.write(chunk)
        if size == 0:
            raise HTTPException(400, "Leere Datei")
        try:
            info = await asyncio.to_thread(B.restore, pathlib.Path(tmp))
        except B.BackupError as e:
            raise HTTPException(400, str(e))
        _reload_state()
        return {"ok": True, **info}
    finally:
        pathlib.Path(tmp).unlink(missing_ok=True)


def _reload_state() -> None:
    """Nach dem Import: Einstellungen und Scan-Ergebnisse aus der neuen Datenbank uebernehmen."""
    from ...db import SessionLocal
    from ...db.repository import get_all_settings
    from . import market_router
    db = SessionLocal()
    try:
        for k, v in get_all_settings(db).items():
            os.environ[k] = v
    finally:
        db.close()
    market_router.restore_scans()


async def scheduler() -> None:
    """Taeglich zur eingestellten Stunde eine automatische Sicherung anlegen."""
    from datetime import datetime
    while True:
        try:
            s = Settings()
            if s.backup_enabled and datetime.now().hour >= s.backup_hour and not B.has_auto_backup_today():
                p = await asyncio.to_thread(B.create_backup, "auto")
                removed = B.prune_auto(s.backup_keep)
                log.info(f"Automatische Sicherung: {p.name} (alte entfernt: {removed})")
        except Exception as e:
            log.error(f"Automatische Sicherung fehlgeschlagen: {e}")
        await asyncio.sleep(300)
