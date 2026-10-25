"""Reine Logik ohne Netzwerk: Kennungen, Kennzahlen, Ordergroesse, Kalender, Analyse-Parser."""
import datetime as dt
import random

from src.agent import identifiers as ids
from src.agent.analysis import company
from src.agent.analytics import metrics as M
from src.agent.calendar_util import extract_events, parse_date, to_ics
from src.agent.risk import size_order


def test_isin_checksum_and_wkn():
    assert ids.isin_valid("US0378331005") and ids.isin_valid("DE0007164600")
    assert not ids.isin_valid("US0378331006")          # falsche Pruefziffer
    assert not ids.isin_valid("ignore previous")        # Prompt-Injection-Versuch
    assert ids.wkn_from_isin("DE0007164600") == "716460"
    assert ids.wkn_from_isin("US0378331005") == ""      # nur deutsche ISINs


def _series(beta, noise, seed, n=260):
    random.seed(7)
    mk = [random.gauss(0.0004, 0.01) for _ in range(n)]
    random.seed(seed)
    p, out = 100.0, []
    for i in range(n):
        p *= 1 + beta * mk[i] + random.gauss(0, noise)
        out.append((dt.date(2025, 1, 1) + dt.timedelta(days=i), p))
    return out


def test_beta_and_correlation():
    bench = _series(1.0, 0.0, 1)
    asset = _series(1.5, 0.002, 2)
    assert 1.3 < M.beta(asset, bench) < 1.7
    assert M.correlation(asset, bench) > 0.95
    assert M.annual_vol(bench) > 0 and M.max_drawdown(bench) <= 0
    assert M.summarize(bench[:10])["ret_1m"] is None     # zu kurz -> None statt Fehler


def test_size_order_limits():
    buy = size_order("BUY", 50, 0, 0, 100_000, 20_000, 10, 1, 10)
    assert buy["quantity"] == 200 and not buy["blocked"]            # 1% Risiko / 10% Stopp = 10% Depot
    full = size_order("BUY", 50, 0, 10_000, 100_000, 20_000, 10, 1, 10)
    assert full["quantity"] == 0 and "Positionslimit" in full["blocked"]
    poor = size_order("BUY", 50, 0, 0, 100_000, 10, 10, 1, 10)
    assert poor["blocked"]                                          # kein Cash
    assert size_order("SELL", 50, 120.7, 0, 1, 1, 10, 1, 10)["quantity"] == 120


def test_calendar_extraction():
    today = dt.date(2026, 10, 21)
    assert parse_date("1.5.2027") == (dt.date(2027, 5, 1), False)
    assert parse_date("2027-05") == (dt.date(2027, 5, 1), True)
    assert parse_date("irgendwann") is None
    data = {"company": {"name": "SAP SE"},
            "reports": {"next_events": [{"event": "Q3 Quartalszahlen", "date": "2026-10-22"},
                                         {"event": "alt", "date": "2026-01-01"}]},
            "financial_health": {"dividend": "2,50 EUR (Ex-Tag 06.05.2027)"}}
    ev = extract_events(data, today)
    assert [e["kind"] for e in ev] == ["earnings", "dividend"]       # Vergangenes fliegt raus


def test_ics_escapes_special_chars():
    e = type("E", (), {"id": 1, "date": dt.date(2026, 12, 1), "title": "A; B, C", "note": "", "approx": False})()
    assert r"SUMMARY:A\; B\, C" in to_ics([e])


def test_company_parse_and_url_validation():
    raw = 'Hier das Ergebnis:\n```json\n{"company": {"name": "X"}, "news": [{"headline": "h", "url": "https://a.de/1/"}, ' \
          '{"headline": "i", "url": "https://erfunden.de"}, {"headline": "j", "url": "javascript:alert(1)"}]}\n```'
    data = company._parse(raw)
    assert data and data["company"]["name"] == "X"
    company._validate_urls(data, [{"url": "https://a.de/1"}])
    assert [n["url"] for n in data["news"]] == ["https://a.de/1/", "", ""]   # nur belegte Links bleiben
    assert company._parse("keine json antwort") is None


def test_diff_analyses():
    prev = {"outlook": {"verdict": "BULLISH", "confidence": .6}, "news": [{"headline": "Alt"}]}
    cur = {"outlook": {"verdict": "NEUTRAL", "confidence": .7}, "news": [{"headline": "alt"}, {"headline": "Neu"}]}
    d = company.diff_analyses(prev, cur)
    assert d["verdict"] == {"was": "BULLISH", "now": "NEUTRAL"} and [n["headline"] for n in d["new_news"]] == ["Neu"]


def test_schedule_day_parsing_and_due():
    from src.agent.scheduler import is_due, parse_days
    assert parse_days("mon-fri") == {0, 1, 2, 3, 4}
    assert parse_days("sat-mon") == {5, 6, 0}                 # ueber das Wochenende
    assert parse_days("mon, wed,xyz") == {0, 2}
    assert parse_days("") == set()
    mon_1800 = dt.datetime(2026, 10, 19, 18, 0)               # Montag
    assert is_due(mon_1800, 17, 5, {0}, None)
    assert not is_due(mon_1800, 17, 5, {0}, mon_1800.date())  # heute schon gelaufen
    assert not is_due(dt.datetime(2026, 10, 19, 16, 59), 17, 5, {0}, None)
    assert not is_due(dt.datetime(2026, 10, 20, 18, 0), 17, 5, {0}, None)   # Dienstag nicht erlaubt
