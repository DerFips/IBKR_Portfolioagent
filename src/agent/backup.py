"""Datenbank-Sicherung und -Wiederherstellung (SQLite Online-Backup, gzip).

Sicherheit beim Import: Die Datei wird vor dem Einspielen geprueft (SQLite-Integritaet,
nur bekannte Tabellen, keine Trigger/Views/Virtual Tables), und es wird automatisch eine
Sicherung des aktuellen Stands angelegt. Der Schluessel fuer verschluesselte Einstellungen
(.settings.key) ist nie Teil einer Sicherung.
"""
import gzip
import logging
import os
import pathlib
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime

from .db.models import Base
from .settings import Settings

log = logging.getLogger(__name__)
MAX_IMPORT_BYTES = 300 * 1024 * 1024
_NAME = re.compile(r"^portfolio-\d{8}-\d{6}-(manual|auto|pre-restore)\.db\.gz$")


class BackupError(ValueError):
    pass


def db_path() -> pathlib.Path:
    return pathlib.Path(Settings().db_path).resolve()


def backup_dir() -> pathlib.Path:
    d = db_path().parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_backup(label: str = "manual") -> pathlib.Path:
    """Konsistente, komprimierte Kopie der laufenden Datenbank."""
    assert label in ("manual", "auto", "pre-restore")
    name = f"portfolio-{datetime.now():%Y%m%d-%H%M%S}-{label}.db.gz"
    target = backup_dir() / name
    with tempfile.TemporaryDirectory() as tmp:
        raw = pathlib.Path(tmp) / "snap.db"
        src = sqlite3.connect(str(db_path()), timeout=30)
        dst = sqlite3.connect(str(raw))
        try:
            src.backup(dst)        # sicher auch waehrend die App schreibt
        finally:
            dst.close(); src.close()
        with open(raw, "rb") as f_in, gzip.open(target, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.chmod(target, 0o600)
    return target


def list_backups() -> list[dict]:
    out = []
    for p in sorted(backup_dir().glob("portfolio-*.db.gz"), reverse=True):
        if _NAME.match(p.name):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "created": datetime.fromtimestamp(st.st_mtime).isoformat(),
                        "kind": _NAME.match(p.name).group(1)})
    return out


def resolve_backup(name: str) -> pathlib.Path:
    """Nur Dateien aus dem Backup-Ordner mit erwartetem Namensmuster (kein Path-Traversal)."""
    if not _NAME.match(name):
        raise BackupError("Ungueltiger Dateiname")
    p = backup_dir() / name
    if not p.is_file():
        raise BackupError("Sicherung nicht gefunden")
    return p


def prune_auto(keep: int) -> int:
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    for b in autos[max(keep, 1):]:
        (backup_dir() / b["name"]).unlink(missing_ok=True)
    return max(len(autos) - max(keep, 1), 0)


def has_auto_backup_today() -> bool:
    today = datetime.now().strftime("%Y%m%d")
    return any(b["kind"] == "auto" and b["name"].startswith(f"portfolio-{today}") for b in list_backups())


def validate_sqlite(path: pathlib.Path) -> dict:
    """Prueft eine entpackte SQLite-Datei; wirft BackupError. Liefert Zusammenfassung."""
    allowed = set(Base.metadata.tables)
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise BackupError(f"Keine gueltige SQLite-Datei: {e}")
    try:
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("Datenbank ist beschaedigt (integrity_check fehlgeschlagen)")
            rows = con.execute("SELECT type, name FROM sqlite_master").fetchall()
        except sqlite3.DatabaseError as e:
            raise BackupError(f"Keine gueltige SQLite-Datei: {e}")
        bad = [f"{t} {n}" for t, n in rows if t not in ("table", "index")]
        if bad:
            raise BackupError(f"Nicht erlaubte Objekte (Trigger/Views): {', '.join(bad[:3])}")
        tables = {n for t, n in rows if t == "table" and not n.startswith("sqlite_")}
        unknown = tables - allowed
        if unknown:
            raise BackupError(f"Unbekannte Tabellen: {', '.join(sorted(unknown)[:5])}")
        if not tables & {"agent_runs", "settings", "watchlist"}:
            raise BackupError("Sieht nicht nach einer Portfolio-Agent-Datenbank aus")
        counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in sorted(tables)}
        return {"tables": len(tables), "rows": counts}
    finally:
        con.close()


def restore(data_path: pathlib.Path) -> dict:
    """Spielt eine (ggf. gzip-komprimierte) Sicherung ein. Legt vorher eine Sicherung des Ist-Stands an."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = pathlib.Path(tmp) / "import.db"
        with open(data_path, "rb") as f:
            gz = f.read(2) == b"\x1f\x8b"
        with (gzip.open(data_path, "rb") if gz else open(data_path, "rb")) as f_in, open(raw, "wb") as f_out:
            size = 0
            while chunk := f_in.read(1 << 20):
                size += len(chunk)
                if size > MAX_IMPORT_BYTES * 2:
                    raise BackupError("Entpackte Datei zu gross")
                f_out.write(chunk)
        info = validate_sqlite(raw)
        safety = create_backup("pre-restore")
        src = sqlite3.connect(f"file:{raw}?mode=ro", uri=True)
        dst = sqlite3.connect(str(db_path()), timeout=30)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
    from .db import migrate
    migrate()
    log.info(f"Datenbank wiederhergestellt aus Import ({info['tables']} Tabellen); Sicherung davor: {safety.name}")
    return {**info, "safety_backup": safety.name}
