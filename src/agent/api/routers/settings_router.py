"""Settings-Router: .env live editierbar via DB + os.environ."""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..deps import get_db
from ...db.repository import get_all_settings, set_setting
from ...settings import Settings
from ...llm import test_connection

router = APIRouter(prefix="/api/settings", tags=["Settings"])

SETTINGS_SCHEMA = [
    {"key": "LLM_PROVIDER",   "label": "KI-Provider", "type": "select", "group": "KI-Modell",
     "options": ["ollama", "anthropic", "nvidia", "hermes"]},
    # "providers": nur bei diesen KI-Providern im Dashboard sichtbar
    {"key": "ANTHROPIC_API_KEY", "label": "Claude API-Key (sk-ant-…)", "type": "password", "group": "KI-Modell", "providers": ["anthropic"]},
    {"key": "ANTHROPIC_MODEL", "label": "Claude-Modell", "type": "select", "group": "KI-Modell", "providers": ["anthropic"],
     "options": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]},
    {"key": "ANTHROPIC_EFFORT", "label": "Claude Denktiefe (effort)", "type": "select", "group": "KI-Modell", "providers": ["anthropic"],
     "options": ["low", "medium", "high", "xhigh", "max"]},
    {"key": "NVIDIA_API_KEY", "label": "NVIDIA API-Key (nvapi-…)", "type": "password", "group": "KI-Modell", "providers": ["nvidia"]},
    {"key": "NVIDIA_MODEL",   "label": "NVIDIA-Modell (z.B. nvidia/nemotron-3-ultra-550b-a55b)", "type": "text", "group": "KI-Modell", "providers": ["nvidia"]},
    {"key": "NVIDIA_TIMEOUT", "label": "NVIDIA-Timeout (Sekunden gesamt)", "type": "number", "group": "KI-Modell", "providers": ["nvidia"]},
    {"key": "OLLAMA_BASE_URL", "label": "Ollama Base URL", "type": "text", "group": "KI-Modell", "providers": ["ollama"]},
    {"key": "OLLAMA_MODEL",    "label": "Ollama-Modell", "type": "text", "group": "KI-Modell", "providers": ["ollama"]},
    {"key": "OLLAMA_TIMEOUT", "label": "Ollama-Timeout (Sekunden)", "type": "number", "group": "KI-Modell", "providers": ["ollama"]},
    {"key": "HERMES_BASE_URL", "label": "Hermes API-Server URL", "type": "text", "group": "KI-Modell", "providers": ["hermes"]},
    {"key": "HERMES_API_KEY", "label": "Hermes API_SERVER_KEY", "type": "password", "group": "KI-Modell", "providers": ["hermes"]},
    {"key": "HERMES_TIMEOUT", "label": "Hermes-Timeout (Sekunden gesamt)", "type": "number", "group": "KI-Modell", "providers": ["hermes"]},
    {"key": "TAVILY_API_KEY", "label": "Tavily API-Key (Websuche für Analysen)", "type": "password", "group": "KI-Modell", "providers": ["ollama", "nvidia"]},
    {"key": "IBKR_HOST",       "label": "TWS Host",               "type": "text",     "group": "IBKR"},
    {"key": "IBKR_PORT",       "label": "Port (Live=7496 / Paper=7497)", "type": "number", "group": "IBKR"},
    {"key": "IBKR_CLIENT_ID",  "label": "Client ID",              "type": "number",   "group": "IBKR"},
    {"key": "IBKR_DRY_RUN",    "label": "Dry Run (keine echten Orders)", "type": "bool", "group": "IBKR"},
    {"key": "MIN_CONFIDENCE",  "label": "Min. Konfidenz (0.0–1.0)","type": "number",  "group": "Risiko"},
    {"key": "STOP_LOSS_PCT",  "label": "Angenommener Stopp % (für Ordergröße)", "type": "number", "group": "Risiko"},
    {"key": "MAX_RISK_PCT_PER_TRADE", "label": "Max. Risiko je Trade % vom Depot", "type": "number", "group": "Risiko"},
    {"key": "BENCHMARK_SYMBOL","label": "Benchmark-ETF (z.B. SPY, leer = aus)", "type": "text", "group": "Risiko"},
    {"key": "MAX_POSITION_PCT","label": "Max. Positions-Gewicht %","type": "number",  "group": "Risiko"},
    {"key": "MAX_DAILY_TRADES","label": "Max. Trades pro Tag",    "type": "number",   "group": "Risiko"},
    {"key": "AGENT_SCHEDULE_ENABLED", "label": "Automatische Runs nach Zeitplan", "type": "bool", "group": "Zeitplan"},
    {"key": "AGENT_RUN_DAYS", "label": "Wochentage (z.B. mon-fri oder mon,wed)", "type": "text", "group": "Zeitplan"},
    {"key": "AGENT_RUN_HOUR",  "label": "Run-Stunde (0–23)",      "type": "number",   "group": "Zeitplan"},
    {"key": "AGENT_RUN_MINUTE","label": "Run-Minute (0–59)",      "type": "number",   "group": "Zeitplan"},
    {"key": "BACKUP_ENABLED", "label": "Tägliche automatische DB-Sicherung", "type": "bool", "group": "Backup"},
    {"key": "BACKUP_HOUR",    "label": "Sicherung ab Uhrzeit (0–23)", "type": "number", "group": "Backup"},
    {"key": "BACKUP_KEEP",    "label": "Automatische Sicherungen behalten", "type": "number", "group": "Backup"},
    {"key": "DASHBOARD_PASSWORD","label": "Dashboard-Passwort",   "type": "password", "group": "Dashboard"},
]
_SCHEMA_KEYS = {s["key"] for s in SETTINGS_SCHEMA}
_SECRET_KEYS = {s["key"] for s in SETTINGS_SCHEMA if s["type"] == "password"}
_MASK = "••••••••"


def _mask(key: str, value: str) -> str:
    """Geheimnisse verlassen den Server nie im Klartext."""
    if key in _SECRET_KEYS and value:
        return _MASK + value[-4:] if key.endswith("_API_KEY") and len(value) > 8 else _MASK
    return value


def _valid(key: str, value: str) -> str | None:
    """Fehlertext oder None, je nach Typ aus dem Schema."""
    item = next(s for s in SETTINGS_SCHEMA if s["key"] == key)
    if len(value) > 500:
        return "Wert zu lang"
    try:
        if item["type"] == "number":
            import math
            v = float(value)
            if not math.isfinite(v) or v < 0:
                return "muss eine Zahl >= 0 sein"
            if key == "STOP_LOSS_PCT" and not (1 <= v <= 90):
                return "zwischen 1 und 90"
            if key in ("MAX_RISK_PCT_PER_TRADE", "MAX_POSITION_PCT") and v > 100:
                return "höchstens 100"
        elif item["type"] == "bool" and value not in ("true", "false"):
            return "nur true/false erlaubt"
        elif item["type"] == "select" and value not in item["options"]:
            return f"erlaubt: {', '.join(item['options'])}"
    except ValueError:
        return "keine gueltige Zahl"
    return None


def _is_masked(value: str) -> bool:
    return value.startswith(_MASK)


def _current_values(db: Session) -> dict:
    s      = Settings()
    db_vals = get_all_settings(db)
    defaults = {
        "LLM_PROVIDER":       s.llm_provider,
        "ANTHROPIC_API_KEY":  s.anthropic_api_key,
        "NVIDIA_API_KEY":     s.nvidia_api_key,
        "NVIDIA_MODEL":       s.nvidia_model,
        "NVIDIA_TIMEOUT":     str(s.nvidia_timeout),
        "HERMES_TIMEOUT":     str(s.hermes_timeout),
        "TAVILY_API_KEY":     s.tavily_api_key,
        "HERMES_BASE_URL":    s.hermes_base_url,
        "HERMES_API_KEY":     s.hermes_api_key,
        "ANTHROPIC_MODEL":    s.anthropic_model,
        "ANTHROPIC_EFFORT":   s.anthropic_effort,
        "OLLAMA_BASE_URL":    s.ollama_base_url,
        "OLLAMA_MODEL":       s.ollama_model,
        "OLLAMA_TIMEOUT":     str(s.ollama_timeout),
        "IBKR_HOST":          s.ibkr_host,
        "IBKR_PORT":          str(s.ibkr_port),
        "IBKR_CLIENT_ID":     str(s.ibkr_client_id),
        "IBKR_DRY_RUN":       str(s.ibkr_dry_run).lower(),
        "MIN_CONFIDENCE":     str(s.min_confidence),
        "MAX_POSITION_PCT":   str(s.max_position_pct),
        "STOP_LOSS_PCT":      str(s.stop_loss_pct),
        "MAX_RISK_PCT_PER_TRADE": str(s.max_risk_pct_per_trade),
        "BENCHMARK_SYMBOL":   s.benchmark_symbol,
        "MAX_DAILY_TRADES":   str(s.max_daily_trades),
        "AGENT_SCHEDULE_ENABLED": str(s.agent_schedule_enabled).lower(),
        "AGENT_RUN_DAYS":     s.agent_run_days,
        "AGENT_RUN_HOUR":     str(s.agent_run_hour),
        "AGENT_RUN_MINUTE":   str(s.agent_run_minute),
        "BACKUP_ENABLED":     str(s.backup_enabled).lower(),
        "BACKUP_HOUR":        str(s.backup_hour),
        "BACKUP_KEEP":        str(s.backup_keep),
        "DASHBOARD_PASSWORD": s.dashboard_password,
    }
    return {k: db_vals.get(k, v) for k, v in defaults.items()}


def _public_values(db: Session) -> dict:
    return {k: _mask(k, v) for k, v in _current_values(db).items()}


@router.get("/schema")
def settings_schema():
    return SETTINGS_SCHEMA


@router.get("")
def all_settings(db: Session = Depends(get_db)):
    return _public_values(db)


class SettingIn(BaseModel):
    key:   str
    value: str


@router.post("")
def save_setting(body: SettingIn, db: Session = Depends(get_db)):
    if body.key not in _SCHEMA_KEYS:
        raise HTTPException(400, f"Unbekannter Schluessel: {body.key}")
    if body.key in _SECRET_KEYS and _is_masked(body.value):
        return {"ok": True, "key": body.key, "unchanged": True}
    if (err := _valid(body.key, body.value)):
        raise HTTPException(400, f"{body.key}: {err}")
    set_setting(db, body.key, body.value)
    os.environ[body.key] = body.value
    return {"ok": True, "key": body.key, "value": _mask(body.key, body.value)}


class BulkSettingsIn(BaseModel):
    settings: dict[str, str]


@router.post("/bulk")
def save_bulk(body: BulkSettingsIn, db: Session = Depends(get_db)):
    saved = {}
    for key, value in body.settings.items():
        if key in _SCHEMA_KEYS:
            if key in _SECRET_KEYS and _is_masked(value):
                continue   # unveraenderter Platzhalter
            if (err := _valid(key, value)):
                raise HTTPException(400, f"{key}: {err}")
            set_setting(db, key, value)
            os.environ[key] = value
            saved[key] = _mask(key, value)
    return {"ok": True, "saved": saved}


@router.post("/test-llm")
async def test_llm():
    """Testet die aktuell gespeicherte KI-Konfiguration (Ollama oder Claude)."""
    return await test_connection(Settings())
