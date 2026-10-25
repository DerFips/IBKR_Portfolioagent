"""Termine aus Analysen extrahieren und als iCalendar (.ics) ausgeben."""
import re
from datetime import date, datetime, timedelta, timezone

_ISO = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")
_DE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def parse_date(text: str) -> tuple[date, bool] | None:
    """(Datum, approx) aus 'YYYY-MM-DD', 'DD.MM.YYYY' oder 'YYYY-MM' (approx=True, Monatserster)."""
    text = str(text or "")
    m = _DE.search(text)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1])), False
        except ValueError:
            return None
    m = _ISO.search(text)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3] or 1)), m[3] is None
        except ValueError:
            return None
    return None


def guess_kind(title: str) -> str:
    t = title.lower()
    if "hauptversammlung" in t or re.search(r"\bagm\b|\bhv\b", t):
        return "agm"
    if "dividend" in t or "ex-tag" in t or "ex-date" in t:
        return "dividend"
    if re.search(r"quartal|q[1-4]\b|zahlen|ergebnis|earnings|geschaeftsbericht|geschäftsbericht|bilanz", t):
        return "earnings"
    return "other"


def extract_events(data: dict, today: date | None = None) -> list[dict]:
    """Zukuenftige Termine aus einer Analyse (reports.next_events, Dividenden-Ex-Tag)."""
    today = today or date.today()
    name = (data.get("company") or {}).get("name") or ""
    out, seen = [], set()

    def add(raw_date, title, kind=None, note=""):
        parsed = parse_date(raw_date)
        if not parsed or parsed[0] < today - timedelta(days=1):
            return
        d, approx = parsed
        title = f"{name}: {title}".strip(": ") if name and name.lower() not in title.lower() else title
        key = (d, title.lower())
        if key in seen:
            return
        seen.add(key)
        out.append({"date": d, "title": title[:200], "kind": kind or guess_kind(title),
                    "approx": approx, "note": note[:300]})

    for e in (data.get("reports") or {}).get("next_events") or []:
        if isinstance(e, dict) and e.get("event"):
            add(e.get("date"), str(e["event"]), note=str(e.get("date") or ""))
    div = str((data.get("financial_health") or {}).get("dividend") or "")
    m = re.search(r"ex[- ]?(?:tag|date)[^0-9]{0,12}(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2})", div, re.I)
    if m:
        add(m.group(1), "Dividenden-Ex-Tag", "dividend", note=div)
    return out


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def to_ics(events) -> str:
    """events: Objekte mit id, date, title, note, approx."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Portfolio-Agent//DE", "CALSCALE:GREGORIAN"]
    for e in events:
        lines += ["BEGIN:VEVENT", f"UID:pa-{e.id}@portfolio-agent", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{e.date:%Y%m%d}", f"DTEND;VALUE=DATE:{e.date + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_esc(('ca. ' if e.approx else '') + e.title)}"]
        if e.note:
            lines.append(f"DESCRIPTION:{_esc(e.note)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
