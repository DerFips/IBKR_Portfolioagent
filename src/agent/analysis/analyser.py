"""KI-Marktanalyse (Ollama oder Claude).

Fuer jede Position im Portfolio wird ein LLM-Prompt gebaut,
der eine strukturierte Empfehlung (BUY / HOLD / SELL) mit
Begruendung und Konfidenz zurueckgibt. Zusaetzlich fasst
`summarize_portfolio` das Gesamtportfolio zusammen.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass

from ..llm import chat, LLMError
from ..settings import Settings

log = logging.getLogger(__name__)


@dataclass
class PositionAnalysis:
    symbol:       str
    action:       str        # BUY | HOLD | SELL
    confidence:   float      # 0.0 – 1.0
    rationale:    str
    risk_level:   str        # LOW | MEDIUM | HIGH


_SYSTEM_PROMPT = """Du bist ein erfahrener Portfoliomanager und Aktienanalyst.
Du analysierst einzelne Aktienpositionen auf Basis von Kursdaten
und gibst eine klare Handlungsempfehlung.

Antworte IMMER als valides JSON-Objekt in exakt diesem Format:
{
  "action": "HOLD",
  "confidence": 0.75,
  "rationale": "Begruendung auf Deutsch in 2-3 Saetzen.",
  "risk_level": "MEDIUM"
}

Erlaubte Werte:
- action: BUY | HOLD | SELL
- confidence: 0.0 bis 1.0
- risk_level: LOW | MEDIUM | HIGH

Kein Text ausserhalb des JSON-Objekts.
"""

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "action":     {"type": "string", "enum": ["BUY", "HOLD", "SELL"]},
        "confidence": {"type": "number"},
        "rationale":  {"type": "string"},
        "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
    },
    "required": ["action", "confidence", "rationale", "risk_level"],
    "additionalProperties": False,
}

_SUMMARY_SYSTEM = """Du bist ein erfahrener Portfoliomanager.
Du erhaeltst die Einzelempfehlungen fuer ein Depot und fasst sie zusammen.
Antworte als JSON: {"market_view": "bullish|neutral|bearish",
"summary": "3-5 Saetze auf Deutsch: Gesamtlage, Klumpenrisiken, wichtigste Massnahmen"}.
Kein Text ausserhalb des JSON-Objekts."""

_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "market_view": {"type": "string", "enum": ["bullish", "neutral", "bearish"]},
        "summary":     {"type": "string"},
    },
    "required": ["market_view", "summary"],
    "additionalProperties": False,
}


def _build_prompt(symbol: str, quantity: float, avg_cost: float,
                  current_price: float, market_value: float,
                  unrealized_pnl: float, weight: float,
                  currency: str, context: str = "", metrics: dict | None = None) -> str:
    pnl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0
    direction = "im Plus" if unrealized_pnl >= 0 else "im Minus"
    m = metrics or {}
    fmt = lambda v, s="%": "n/a" if v is None else f"{v:+.1f}{s}"
    market = ""
    if any(v is not None for v in m.values()):
        market = (
            f"Kursentwicklung (aus Tageskursen):\n"
            f"  1 Monat {fmt(m.get('ret_1m'))} | 3 Monate {fmt(m.get('ret_3m'))} | 6 Monate {fmt(m.get('ret_6m'))}\n"
            f"  Abstand zum 52-Wochen-Hoch {fmt(m.get('from_high_pct'))} "
            f"(Hoch {m.get('high_52w') or 0:.2f}, Tief {m.get('low_52w') or 0:.2f})\n"
            f"  Volatilitaet (annualisiert) {fmt(m.get('volatility'), ' %').replace('+','')} | "
            f"Max. Rueckgang 1 Jahr {fmt(m.get('max_drawdown'))}\n\n")

    return (
        f"Analysiere folgende Aktienposition:\n\n"
        f"Symbol:           {symbol}\n"
        f"Stück:            {quantity:.0f}\n"
        f"Einstandskurs:    {avg_cost:.2f} {currency}\n"
        f"Aktueller Kurs:   {current_price:.2f} {currency}\n"
        f"Marktwert:        {market_value:,.2f} {currency}\n"
        f"Unrealisiertes PnL: {unrealized_pnl:+,.2f} {currency} "
        f"({pnl_pct:+.1f}%, {direction})\n"
        f"Portfolio-Gewicht: {weight*100:.1f}%\n\n"
        + market
        + (f"Portfolio-Kontext (groesste Positionen):\n{context}\n\n" if context else "")
        + f"Gib eine Handlungsempfehlung: Soll diese Position gehalten (HOLD), "
        f"abgestossen (SELL) oder aufgestockt werden (BUY)?\n"
        f"Beruecksichtige: PnL-Entwicklung, Gewichtung im Portfolio, "
        f"typisches Kursverhalten von {symbol}."
    )


def _extract_json(raw: str) -> dict:
    """Extrahiert das JSON-Objekt aus der LLM-Antwort (auch aus Markdown-Fences)."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(match.group(0) if match else raw)


def _parse_response(raw: str, symbol: str) -> dict:
    try:
        data = _extract_json(raw)
        action = str(data.get("action", "HOLD")).upper()
        risk   = str(data.get("risk_level", "MEDIUM")).upper()
        return {
            "action":     action if action in ("BUY", "HOLD", "SELL") else "HOLD",
            "confidence": min(1.0, max(0.0, float(data.get("confidence", 0.5)))),
            "rationale":  str(data.get("rationale", "–")),
            "risk_level": risk if risk in ("LOW", "MEDIUM", "HIGH") else "MEDIUM",
        }
    except Exception as e:
        log.warning(f"[{symbol}] JSON-Parse fehlgeschlagen: {e}  raw={raw[:200]}")
        return {
            "action":     "HOLD",
            "confidence": 0.3,
            "rationale":  f"Analyse fehlgeschlagen: {e}",
            "risk_level": "HIGH",
        }


async def analyse_position(
    symbol: str, quantity: float, avg_cost: float,
    current_price: float, market_value: float,
    unrealized_pnl: float, weight: float, currency: str,
    settings: Settings, context: str = "", metrics: dict | None = None,
) -> PositionAnalysis:
    """Analysiert eine einzelne Position via konfiguriertem LLM."""
    prompt = _build_prompt(symbol, quantity, avg_cost, current_price,
                           market_value, unrealized_pnl, weight, currency, context, metrics)
    try:
        raw = await chat(
            [{"role": "system", "content": _SYSTEM_PROMPT},
             {"role": "user",   "content": prompt}],
            settings, temperature=0.2, schema=_ANALYSIS_SCHEMA,
        )
        log.debug(f"[{symbol}] LLM-Antwort: {raw[:300]}")
    except Exception as e:
        log.error(f"[{symbol}] LLM-Fehler: {e}")
        raw = json.dumps({
            "action": "HOLD", "confidence": 0.2,
            "rationale": f"LLM nicht erreichbar: {e}",
            "risk_level": "HIGH",
        })

    parsed = _parse_response(raw, symbol)
    log.info(
        f"[{symbol}] {parsed['action']}  "
        f"conf={parsed['confidence']:.0%}  "
        f"risk={parsed['risk_level']}"
    )
    return PositionAnalysis(symbol=symbol, **parsed)


async def analyse_portfolio(positions, settings: Settings) -> list[PositionAnalysis]:
    """Analysiert alle Positionen.

    Ollama sequenziell (lokale Hardware), Claude parallel (max. 4), NVIDIA max. 2 (Rate-Limit).
    """
    top = sorted(positions, key=lambda p: p.weight, reverse=True)[:5]
    context = "\n".join(f"- {p.symbol}: {p.weight*100:.1f}%" for p in top)
    sem = asyncio.Semaphore({"anthropic": 4, "nvidia": 2}.get(settings.llm_provider.lower(), 1))

    async def _one(p):
        async with sem:
            return await analyse_position(
                symbol=p.symbol, quantity=p.quantity, avg_cost=p.avg_cost,
                current_price=p.current_price, market_value=p.market_value,
                unrealized_pnl=p.unrealized_pnl, weight=p.weight,
                currency=p.currency, settings=settings, context=context,
                metrics=getattr(p, 'metrics', None),
            )

    return list(await asyncio.gather(*[_one(p) for p in positions]))


def _heuristic_view(analyses: list[PositionAnalysis]) -> str:
    sells = sum(1 for a in analyses if a.action == "SELL")
    holds = sum(1 for a in analyses if a.action == "HOLD")
    buys  = sum(1 for a in analyses if a.action == "BUY")
    return "bearish" if sells > holds else ("bullish" if buys > holds else "neutral")


async def summarize_portfolio(positions, analyses: list[PositionAnalysis],
                              settings: Settings) -> tuple[str, str]:
    """Gesamteinschaetzung (market_view, summary) via LLM; Fallback: Zaehl-Heuristik."""
    by_sym = {p.symbol: p for p in positions}
    lines = []
    for a in analyses:
        p = by_sym.get(a.symbol)
        w = f"{p.weight*100:.1f}%" if p else "?"
        lines.append(f"- {a.symbol} ({w}): {a.action}, Konfidenz {a.confidence:.0%}, "
                     f"Risiko {a.risk_level} – {a.rationale}")
    heuristic = _heuristic_view(analyses)
    fallback = (f"{len(analyses)} Positionen analysiert: "
                f"{sum(a.action=='BUY' for a in analyses)}x BUY, "
                f"{sum(a.action=='HOLD' for a in analyses)}x HOLD, "
                f"{sum(a.action=='SELL' for a in analyses)}x SELL. "
                f"Markteinschaetzung: {heuristic}.")
    try:
        raw = await chat(
            [{"role": "system", "content": _SUMMARY_SYSTEM},
             {"role": "user", "content": "Einzelempfehlungen:\n" + "\n".join(lines)}],
            settings, temperature=0.2, schema=_SUMMARY_SCHEMA,
        )
        data = _extract_json(raw)
        view = str(data.get("market_view", heuristic)).lower()
        if view not in ("bullish", "neutral", "bearish"):
            view = heuristic
        return view, str(data.get("summary") or fallback)
    except (LLMError, Exception) as e:   # Zusammenfassung ist optional
        log.warning(f"Portfolio-Zusammenfassung fehlgeschlagen: {e}")
        return heuristic, fallback
