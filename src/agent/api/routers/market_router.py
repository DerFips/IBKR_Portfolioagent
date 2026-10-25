"""Marktanalyse-Router.

Zwei Modi:
1. /analyse      – analysiert bekannte Symbole (Universum + Watchlist)
2. /discover     – Die KI sucht selbst nach Trends & unbekannten Kandidaten
"""
import asyncio, json, logging, re
import httpx
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from ..deps import get_db
from ...settings import Settings
from ...llm import chat
from ...identifiers import clean_ids
from ...ibkr.client import IBKRClient
from ...db.repository import get_watchlist, get_all_settings, save_scan, load_scan
from ...db import SessionLocal

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["Marktanalyse"])

# ── Shared State ──────────────────────────────────────────────────────────────
_market_state = {
    "running": False, "progress": 0, "total": 0,
    "current": "", "results": [], "error": None, "timestamp": None,
}
_discover_state = {
    "running": False, "phase": "", "phase_num": 0,
    "progress": 0, "total": 0, "current": "",
    "themes": [], "results": [], "error": None, "timestamp": None,
}

# ── Standard-Universum ────────────────────────────────────────────────────────
DEFAULT_UNIVERSE = [
    "AAPL","MSFT","GOOGL","AMZN","META","NVDA","TSLA","AMD",
    "INTC","ORCL","CRM","ADBE","QCOM","AVGO",
    "JPM","BRK.B","V","MA","BAC",
    "JNJ","LLY","ABBV","UNH",
    "SAP","ASML","SIE.DE","ALV.DE","BAS.DE",
    "SPY","QQQ","VTI",
]

# ── Prompts ───────────────────────────────────────────────────────────────────
_SYS_ANALYSE = """Du bist ein erfahrener Aktienanalyst. Analysiere die gegebene Aktie.
Antworte NUR als valides JSON:
{
  "symbol": "AAPL",
  "isin": "US0378331005",
  "recommendation": "BUY",
  "confidence": 0.75,
  "target_horizon": "3-6 Monate",
  "rationale": "Begruendung auf Deutsch, 2-3 Saetze.",
  "risk_level": "MEDIUM",
  "sector": "Technology",
  "catalysts": ["Catalyst 1"],
  "risks": ["Risiko 1"]
}
recommendation: BUY | WATCH | SKIP. Kein Text ausserhalb des JSON."""

_SYS_DISCOVER_THEMES = """Du bist ein vorausschauender Aktienanalyst und Trendscout.
Heute ist {date}.

Identifiziere 5 konkrete Megatrends oder Themen, bei denen in den naechsten
3-12 Monaten ein signifikanter Kursanstieg moeglich ist.
Beruecksichtige: Makrooekonomie, Technologiezyklen, regulatorische Aenderungen,
geopolitische Verschiebungen, Konsumtrends, Infrastrukturausgaben.

Antworte NUR als valides JSON-Array:
[
  {{
    "theme": "Name des Themas",
    "rationale": "Warum genau jetzt interessant (2-3 Saetze auf Deutsch)",
    "catalyst": "Konkreter Ausloeser in naechsten 6 Monaten",
    "symbols": ["TICK1", "TICK2", "TICK3", "TICK4", "TICK5"],
    "sector": "Branche"
  }}
]
symbols: 4-6 boersenlotierte Ticker, die von diesem Trend profitieren.
Kein Text ausserhalb des JSON-Arrays."""

_SYS_DEEP_ANALYSE = """Du bist ein erfahrener Portfoliomanager. Analysiere diese Aktie im Kontext
des genannten Megatrends.
Antworte NUR als valides JSON:
{{
  "symbol": "{symbol}",
  "isin": "ISIN der Aktie (12 Zeichen) oder leer, falls unsicher",
  "theme": "{theme}",
  "recommendation": "BUY",
  "confidence": 0.80,
  "target_horizon": "6-12 Monate",
  "upside_potential": "ca. 25%%",
  "rationale": "Begruendung auf Deutsch, 3-4 Saetze warum diese Aktie von dem Trend profitiert.",
  "risk_level": "MEDIUM",
  "sector": "{sector}",
  "entry_strategy": "Sofort kaufen / Bei Ruecksetzer auf X kaufen",
  "catalysts": ["Trigger 1", "Trigger 2"],
  "risks": ["Risiko 1"]
}}
recommendation: BUY | WATCH | SKIP. Kein Text ausserhalb des JSON."""


# ── Helpers ───────────────────────────────────────────────────────────────────
def _get_settings() -> Settings:
    import os
    db = SessionLocal()
    try:
        for k, v in get_all_settings(db).items():
            os.environ[k] = v
    finally:
        db.close()
    return Settings()


_PERSIST_KEYS = {
    "market":   ("results", "timestamp", "progress"),
    "discover": ("themes", "results", "timestamp", "progress"),
    "penny":    ("results", "timestamp", "progress"),
}


def _state_for(kind: str) -> dict:
    return {"market": _market_state, "discover": _discover_state, "penny": _penny_state}[kind]


def _persist(kind: str) -> None:
    """Ergebnis des Scans in der DB sichern (ueberlebt Neustarts)."""
    state = _state_for(kind)
    if state.get("error") or not state.get("timestamp"):
        return   # fehlgeschlagene Laeufe ueberschreiben kein gutes Ergebnis
    db = SessionLocal()
    try:
        save_scan(db, kind, {k: state[k] for k in _PERSIST_KEYS[kind]})
    except Exception as e:
        log.error(f"Scan '{kind}' konnte nicht gespeichert werden: {e}")
    finally:
        db.close()


def restore_scans() -> None:
    """Beim Start: letzte Ergebnisse aus der DB zurueckladen."""
    db = SessionLocal()
    try:
        for kind in _PERSIST_KEYS:
            data = load_scan(db, kind)
            if data:
                _state_for(kind).update(data)
                log.info(f"Scan '{kind}' wiederhergestellt ({len(data.get('results', []))} Ergebnisse)")
    finally:
        db.close()


def _extract_json(raw: str, is_array=False):
    """Erstes vollstaendiges JSON-Objekt/-Array aus der Antwort (auch in ```-Fences,
    mit Text davor/danach, mit verschachtelten Listen und Klammern in Strings)."""
    opener = "[" if is_array else "{"
    dec = json.JSONDecoder()
    pos = raw.find(opener)
    while pos != -1:
        try:
            val, _ = dec.raw_decode(raw[pos:])
            return val
        except ValueError:
            pos = raw.find(opener, pos + 1)
    return None


def _with_ids(data: dict) -> dict:
    """ISIN der KI nur uebernehmen, wenn die Pruefsumme stimmt; WKN bei DE-ISIN ableiten.
    Die KI kann ISINs erfinden – daher immer als 'ki_ids' markiert (bitte gegenpruefen)."""
    ids = clean_ids(data.get("isin"))
    data["isin"], data["wkn"] = ids["isin"], ids["wkn"]
    data["ids_source"] = "KI" if ids["isin"] else ""
    return data


async def _verify_isins(results: list[dict], s: Settings) -> None:
    """ISINs der KI per IBKR gegenpruefen/ersetzen (falls TWS erreichbar)."""
    syms = [r["symbol"] for r in results if r.get("symbol")]
    if not syms:
        return
    try:
        found = await IBKRClient(s.ibkr_host, s.ibkr_port, s.ibkr_client_id).lookup_isins(syms)
    except Exception as e:
        log.info(f"ISIN-Verifikation uebersprungen: {_err(e)}")
        return
    for r in results:
        hit = found.get(r.get("symbol"))
        if not hit:
            continue
        ids = clean_ids(hit["isin"])
        if r.get("isin") and r["isin"] != ids["isin"]:
            log.info(f"[{r['symbol']}] KI-ISIN {r['isin']} durch IBKR-ISIN {ids['isin']} ersetzt")
        r.update(isin=ids["isin"], wkn=ids["wkn"], conid=hit["conid"], ids_source="IBKR")


def _err(e: Exception) -> str:
    """Fehlertext, auch fuer Exceptions ohne Message (z.B. httpx.ReadTimeout)."""
    return f"{type(e).__name__}: {e}".rstrip(": ")


def _snippet(raw: str) -> str:
    return " ".join(raw.split())[:150]


async def _ollama(messages: list, s: Settings, temperature=0.3) -> str:
    """Name historisch – delegiert an den konfigurierten Provider (Ollama/Claude)."""
    return await chat(messages, s, temperature=temperature, max_tokens=8000)


# ── Modus 1: Universum-Analyse ────────────────────────────────────────────────
async def _analyse_symbol(symbol: str, s: Settings) -> dict | None:
    try:
        raw = await _ollama([
            {"role": "system", "content": _SYS_ANALYSE},
            {"role": "user",   "content":
             f"Analysiere {symbol} als potenzielle Kaufposition. "
             f"Beruecksichtige Marktumfeld, Bewertung, Wettbewerb, Risiken."},
        ], s)
        data = _extract_json(raw)
        if data:
            data["symbol"] = symbol
            return _with_ids(data)
    except Exception as e:
        log.warning(f"[{symbol}] {e}")
    return None


async def _run_market_analysis(symbols: list[str]) -> None:
    global _market_state
    s = _get_settings()
    _market_state.update({"running": True, "progress": 0, "total": len(symbols),
                           "current": "", "results": [], "error": None})
    results = []
    for i, sym in enumerate(symbols):
        _market_state["current"] = sym
        _market_state["progress"] = i
        r = await _analyse_symbol(sym, s)
        if r and r.get("recommendation") in ("BUY", "WATCH"):
            results.append(r)
        await asyncio.sleep(0.3)

    results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    _market_state.update({
        "running": False, "progress": len(symbols), "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _persist("market")
    log.info(f"Universum-Analyse: {len(results)} Kandidaten aus {len(symbols)}")


# ── Modus 2: Discovery (Themen → Kandidaten) ─────────────────────────────────
async def _run_discover() -> None:
    global _discover_state
    s = _get_settings()
    _discover_state.update({
        "running": True, "phase": "Trends identifizieren", "phase_num": 1,
        "progress": 0, "total": 0, "current": "",
        "themes": [], "results": [], "error": None,
    })

    # Phase 1: Trends generieren
    log.info("Discovery Phase 1: Trends identifizieren…")
    try:
        raw = await _ollama([
            {"role": "system", "content":
             _SYS_DISCOVER_THEMES.format(date=datetime.now().strftime("%B %Y"))},
            {"role": "user", "content":
             "Welche 5 Megatrends bieten in den naechsten 3-12 Monaten "
             "das groesste Kurspotenzial? Sei konkret und aktuell."},
        ], s, temperature=0.5)
        themes = _extract_json(raw, is_array=True) or []
        if not themes:
            log.warning(f"Discovery Phase 1 nicht parsebar: {raw[:300]}")
            bad = _snippet(raw)
    except Exception as e:
        log.error(f"Discovery Phase 1: {_err(e)}", exc_info=True)
        _discover_state["error"] = f"Phase 1 fehlgeschlagen: {_err(e)}"
        _discover_state["running"] = False
        return

    if not themes:
        _discover_state["error"] = f"Keine Trends generiert – KI-Antwort nicht parsebar: {bad}"
        _discover_state["running"] = False
        return

    _discover_state["themes"] = themes
    log.info(f"Discovery: {len(themes)} Trends identifiziert")

    # Phase 2: Kandidaten tiefenanalysieren
    all_symbols = []
    for t in themes:
        for sym in t.get("symbols", []):
            if sym not in all_symbols:
                all_symbols.append(sym)

    _discover_state.update({
        "phase": "Kandidaten analysieren", "phase_num": 2,
        "total": len(all_symbols), "progress": 0,
    })
    log.info(f"Discovery Phase 2: {len(all_symbols)} Kandidaten analysieren…")

    results = []
    fails, last_err = 0, ""
    for i, sym in enumerate(all_symbols):
        _discover_state["current"]  = sym
        _discover_state["progress"] = i

        # Passendes Theme finden
        theme_obj = next(
            (t for t in themes if sym in t.get("symbols", [])), themes[0]
        )
        theme_name  = theme_obj.get("theme", "")
        theme_sector= theme_obj.get("sector", "")

        try:
            raw = await _ollama([
                {"role": "system", "content":
                 _SYS_DEEP_ANALYSE.format(
                     symbol=sym, theme=theme_name, sector=theme_sector)},
                {"role": "user", "content":
                 f"Analysiere {sym} im Kontext des Trends '{theme_name}'. "
                 f"Trend-Rationale: {theme_obj.get('rationale','')} "
                 f"Konkreter Katalysator: {theme_obj.get('catalyst','')}"},
            ], s, temperature=0.25)
            data = _extract_json(raw)
            if not data:
                fails += 1; last_err = f"Antwort nicht parsebar: {_snippet(raw)}"
                log.warning(f"[{sym}] Deep-Analyse nicht parsebar: {raw[:300]}")
            if data:
                _with_ids(data)
                data["symbol"] = sym
                data["theme"]  = theme_name
                data["sector"] = theme_sector
                if data.get("recommendation") in ("BUY", "WATCH"):
                    results.append(data)
        except Exception as e:
            fails += 1; last_err = _err(e)
            log.warning(f"[{sym}] Deep-Analyse Fehler: {_err(e)}")

        await asyncio.sleep(0.3)

    results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    if not results and fails:
        _discover_state["error"] = (f"{fails} von {len(all_symbols)} Analysen fehlgeschlagen "
                                    f"(zuletzt: {last_err})")
    _discover_state.update({
        "running": False, "progress": len(all_symbols), "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _persist("discover")
    log.info(f"Discovery abgeschlossen: {len(results)} Kandidaten")


# ── Endpunkte ─────────────────────────────────────────────────────────────────
@router.get("/status")
def market_status():
    return {**_market_state}


@router.post("/analyse")
async def start_analysis(background_tasks: BackgroundTasks,
                         db: Session = Depends(get_db)):
    if _market_state["running"]:
        raise HTTPException(409, "Universum-Analyse laeuft bereits")
    watchlist = [i.symbol for i in get_watchlist(db)]
    symbols   = list(dict.fromkeys(DEFAULT_UNIVERSE + watchlist))
    background_tasks.add_task(_run_market_analysis, symbols)
    return {"ok": True, "symbols": len(symbols)}


@router.get("/results")
def market_results():
    return {"results": _market_state["results"],
            "timestamp": _market_state["timestamp"],
            "total_analysed": _market_state["progress"]}


@router.get("/discover/status")
def discover_status():
    return {**_discover_state}


@router.post("/discover")
async def start_discover(background_tasks: BackgroundTasks):
    if _discover_state["running"]:
        raise HTTPException(409, "Discovery laeuft bereits")
    background_tasks.add_task(_run_discover)
    return {"ok": True, "message": "Discovery gestartet"}


@router.get("/discover/results")
def discover_results():
    return {
        "themes":  _discover_state["themes"],
        "results": _discover_state["results"],
        "timestamp": _discover_state["timestamp"],
        "total_analysed": _discover_state["progress"],
    }


# ── Modus 3: Pennystock-Discovery ─────────────────────────────────────────────
_penny_state = {
    "running": False, "phase": "", "phase_num": 0,
    "progress": 0, "total": 0, "current": "",
    "results": [], "error": None, "timestamp": None,
}

_SYS_PENNY_DISCOVER = """Du bist ein spezialisierter Pennystock- und Small-Cap-Analyst mit Fokus auf
hochspekulative Aktien mit Vervielfachungspotenzial (Multibagger).
Heute ist {date}.

Identifiziere 6 konkrete Pennystock- oder Micro-Cap-Aktien (Kurs typischerweise
unter 5 USD bzw. unter 5 EUR), bei denen in den naechsten 1-6 Monaten ein
signifikanter Kursanstieg moeglich ist. Mit Katalysator (z.B. FDA-Entscheid,
Earnings, Deal), boersenlotiert (NYSE, NASDAQ, OTC, Xetra o.ae.).
Halte die Antwort KURZ – Details folgen in einer separaten Tiefenanalyse.

Antworte NUR als valides JSON-Array:
[
  {{
    "symbol": "TICK",
    "name": "Firmenname",
    "isin": "ISIN oder leer, falls unsicher",
    "exchange": "NASDAQ",
    "approx_price_usd": 0.85,
    "market_cap": "Micro-Cap ~50M USD",
    "sector": "Biotech",
    "catalyst": "Ausloeser in max. 10 Worten"
  }}
]
Kein Text ausserhalb des JSON-Arrays."""

_SYS_PENNY_DEEP = """Du bist ein Pennystock-Spezialist. Analysiere diese spekulative Aktie detailliert.
Antworte NUR als valides JSON:
{{
  "symbol": "{symbol}",
  "name": "{name}",
  "isin": "ISIN (12 Zeichen) oder leer, falls unsicher",
  "recommendation": "SPECULATIVE_BUY",
  "confidence": 0.65,
  "upside_potential": "2x-4x",
  "target_horizon": "1-3 Monate",
  "entry_strategy": "Limit-Order bei 0.80 USD, max. 1-2% Depotanteil",
  "stop_loss": "ca. -30% bis -40% Verlustbegrenzung",
  "rationale": "Detaillierte Begruendung auf Deutsch, 3-4 Saetze.",
  "catalyst": "Konkreter naher Ausloeser",
  "risk_level": "HIGH",
  "sector": "{sector}",
  "risks": ["Delisting-Risiko", "Dilution durch Kapitalerhöhung"],
  "warning": "Hochspekulativ – Totalverlust moeglich"
}}
Kein Text ausserhalb des JSON."""


async def _run_penny_discovery() -> None:
    global _penny_state
    s = _get_settings()
    _penny_state.update({
        "running": True, "phase": "Pennystock-Kandidaten suchen",
        "phase_num": 1, "progress": 0, "total": 0,
        "current": "", "results": [], "error": None,
    })

    # Phase 1: Kandidaten generieren
    log.info("Pennystock Phase 1: Kandidaten generieren…")
    try:
        raw = await _ollama([
            {"role": "system", "content":
             _SYS_PENNY_DISCOVER.format(date=datetime.now().strftime("%B %Y"))},
            {"role": "user", "content":
             "Welche 6 Pennystocks oder Micro-Caps haben aktuell das groesste "
             "spekulative Kurspotenzial? Sei sehr konkret mit Ticker und Boerse. "
             "Fokus auf Aktien mit einem konkreten nahen Katalysator."},
        ], s, temperature=0.45)
        candidates = _extract_json(raw, is_array=True) or []
        if not candidates:
            log.warning(f"Penny Phase 1 nicht parsebar: {raw[:300]}")
            bad = _snippet(raw)
    except Exception as e:
        log.error(f"Penny Phase 1: {_err(e)}", exc_info=True)
        _penny_state["error"] = f"Phase 1 fehlgeschlagen: {_err(e)}"
        _penny_state["running"] = False
        return

    if not candidates:
        _penny_state["error"] = f"Keine Kandidaten generiert – KI-Antwort nicht parsebar: {bad}"
        _penny_state["running"] = False
        return

    log.info(f"Pennystock: {len(candidates)} Kandidaten gefunden")
    _penny_state.update({
        "phase": "Tiefenanalyse", "phase_num": 2,
        "total": len(candidates), "progress": 0,
    })

    # Phase 2: Tiefenanalyse
    results = []
    fails, last_err = 0, ""
    candidates = [c for c in candidates if isinstance(c, dict)]
    for i, c in enumerate(candidates):
        sym  = c.get("symbol", "?")
        name = c.get("name", sym)
        sect = c.get("sector", "")
        _penny_state["current"]  = sym
        _penny_state["progress"] = i

        try:
            raw = await _ollama([
                {"role": "system", "content":
                 _SYS_PENNY_DEEP.format(symbol=sym, name=name, sector=sect)},
                {"role": "user", "content":
                 f"Analysiere {sym} ({name}) als Pennystock-Kandidaten. "
                 f"Bekannter Katalysator: {c.get('catalyst','unbekannt')}. "
                 f"Marktkapitalisierung: {c.get('market_cap','unbekannt')}. "
                 f"Bisherige Einschaetzung Upside: {c.get('upside_potential','?')}"},
            ], s, temperature=0.25)
            data = _extract_json(raw)
            if not data:
                fails += 1; last_err = f"Antwort nicht parsebar: {_snippet(raw)}"
                log.warning(f"[{sym}] Penny-Tiefenanalyse nicht parsebar: {raw[:300]}")
            if data:
                # Basis-Felder aus Phase 1 ergänzen
                data.setdefault("symbol",       sym)
                data.setdefault("name",         name)
                data.setdefault("exchange",     c.get("exchange", ""))
                data.setdefault("approx_price_usd", c.get("approx_price_usd", 0))
                data.setdefault("market_cap",   c.get("market_cap", ""))
                data.setdefault("warning",      c.get("warning", "Hochspekulativ"))
                if not data.get("isin"):
                    data["isin"] = c.get("isin", "")
                _with_ids(data)
                data["_pennystock"] = True
                if data.get("recommendation") in ("SPECULATIVE_BUY", "BUY", "WATCH"):
                    results.append(data)
        except Exception as e:
            fails += 1; last_err = _err(e)
            log.warning(f"[{sym}] Penny-Tiefenanalyse: {_err(e)}")

        await asyncio.sleep(0.3)

    await _verify_isins(results, s)
    results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    if not results and fails:
        _penny_state["error"] = (f"{fails} von {len(candidates)} Analysen fehlgeschlagen "
                                 f"(zuletzt: {last_err})")
    _penny_state.update({
        "running": False, "progress": len(candidates),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _persist("penny")
    log.info(f"Pennystock-Discovery: {len(results)} Kandidaten")


@router.get("/penny/status")
def penny_status():
    return {**_penny_state}


@router.post("/penny")
async def start_penny(background_tasks: BackgroundTasks):
    if _penny_state["running"]:
        raise HTTPException(409, "Pennystock-Analyse laeuft bereits")
    background_tasks.add_task(_run_penny_discovery)
    return {"ok": True, "message": "Pennystock-Discovery gestartet"}


@router.get("/penny/results")
def penny_results():
    return {
        "results":       _penny_state["results"],
        "timestamp":     _penny_state["timestamp"],
        "total_analysed": _penny_state["progress"],
    }
