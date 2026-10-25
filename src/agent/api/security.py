"""Zugriffsschutz fuer das Dashboard.

- HTTP-Basic-Auth (beliebiger Benutzername, Passwort = DASHBOARD_PASSWORD)
- Fail-closed: ohne gesetztes Passwort sind alle Routen ausser /api/health gesperrt
- Sperre nach zu vielen Fehlversuchen pro IP
- CSRF-Schutz: schreibende Requests mit fremdem Origin werden abgelehnt
- Sicherheits-Header
"""
import base64
import hmac
import time
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from ..settings import Settings

_OPEN_PATHS = {"/api/health"}
_MAX_FAILS, _WINDOW_S = 5, 300
_fails: dict[str, list[float]] = {}


def _locked(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < _WINDOW_S]
    _fails[ip] = recent
    return len(recent) >= _MAX_FAILS


def _check_password(header: str, expected: str) -> bool:
    try:
        scheme, _, b64 = header.partition(" ")
        if scheme.lower() != "basic":
            return False
        _, _, pw = base64.b64decode(b64).decode("utf-8").partition(":")
    except Exception:
        return False
    return hmac.compare_digest(pw.encode(), expected.encode())


def _headers(resp: Response) -> Response:
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def security_middleware(request: Request, call_next):
    if request.url.path in _OPEN_PATHS:
        return _headers(await call_next(request))

    password = Settings().dashboard_password   # live: Aenderungen wirken sofort
    if not password:
        return _headers(JSONResponse(
            {"detail": "Gesperrt: DASHBOARD_PASSWORD in .env setzen und neu starten."},
            status_code=503))

    ip = request.client.host if request.client else "?"
    if _locked(ip):
        return _headers(JSONResponse(
            {"detail": "Zu viele Fehlversuche – spaeter erneut versuchen."},
            status_code=429))

    if not _check_password(request.headers.get("authorization", ""), password):
        _fails.setdefault(ip, []).append(time.time())
        return _headers(Response(
            "Authentifizierung erforderlich", status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Portfolio-Agent"'}))

    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return _headers(JSONResponse({"detail": "Origin nicht erlaubt"}, status_code=403))

    return _headers(await call_next(request))
