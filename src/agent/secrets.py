"""Verschluesselung sensibler Einstellungen (API-Keys, Passwoerter) in der Datenbank.

Schluessel: SETTINGS_ENCRYPTION_KEY aus der Umgebung, sonst eine automatisch angelegte
Datei <db-ordner>/.settings.key (Rechte 600). Der Schluessel ist NICHT Teil von
Datenbank-Backups – ein Backup verraet also keine Zugangsdaten, beim Einspielen auf
einem anderen Rechner muessen sie neu eingetragen werden.
"""
import logging
import os
import pathlib

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)
PREFIX = "enc:v1:"
_fernet: Fernet | None = None


def is_secret_key(key: str) -> bool:
    return key.endswith("_API_KEY") or key in {"DASHBOARD_PASSWORD"}


def _load() -> Fernet:
    global _fernet
    if _fernet:
        return _fernet
    key = os.environ.get("SETTINGS_ENCRYPTION_KEY", "").strip()
    if not key:
        path = pathlib.Path(os.environ.get("DB_PATH", "data/portfolio.db")).parent / ".settings.key"
        if path.exists():
            key = path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(key)
            os.chmod(path, 0o600)
            log.info(f"Neuer Einstellungs-Schluessel angelegt: {path}")
    _fernet = Fernet(key.encode())
    return _fernet


def reset_cache() -> None:
    global _fernet
    _fernet = None


def encrypt(value: str) -> str:
    return PREFIX + _load().encrypt(value.encode()).decode()


def decrypt(stored: str) -> str | None:
    """Klartext; Werte ohne Praefix (Altbestand) werden unveraendert geliefert.
    None, wenn der Schluessel nicht passt (z.B. Datenbank von anderem Rechner)."""
    if not stored.startswith(PREFIX):
        return stored
    try:
        return _load().decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return None
