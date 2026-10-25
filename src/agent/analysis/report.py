"""PDF-Report zur Unternehmensanalyse (reportlab, rein in Python, ohne Systemabhaengigkeiten)."""
import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Flowable, Frame, KeepTogether, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

NAVY, INK, MUTED = colors.HexColor("#0f172a"), colors.HexColor("#1e293b"), colors.HexColor("#64748b")
LINE, SOFT = colors.HexColor("#e2e8f0"), colors.HexColor("#f8fafc")
GREEN, RED, GREY, AMBER = (colors.HexColor("#16a34a"), colors.HexColor("#dc2626"),
                           colors.HexColor("#64748b"), colors.HexColor("#d97706"))
ACCENT = colors.HexColor("#4f46e5")
W = A4[0] - 36 * mm      # nutzbare Breite

_SUBST = {"→": "->", "←": "<-", "↗": "^", "↘": "v", "↑": "(+)", "↓": "(-)", "▲": "(+)", "▼": "(-)", "≈": "~", "≥": ">=", "≤": "<=", "•": "-",
          "✓": "", "⚠": "!", " ": " ", " ": " ", "−": "-", "‑": "-", "’": "'"}


def _t(v) -> str:
    """Text fuer Helvetica (WinAnsi) aufbereiten und XML-escapen."""
    s = "" if v is None else str(v)
    for a, b in _SUBST.items():
        s = s.replace(a, b)
    return escape(s.encode("cp1252", "replace").decode("cp1252"))


def _st(name, **kw):
    base = dict(fontName="Helvetica", fontSize=9.3, leading=13.2, textColor=INK)
    base.update(kw)
    return ParagraphStyle(name, **base)


BODY = _st("body")
SMALL = _st("small", fontSize=7.8, leading=10.5, textColor=MUTED)
H2 = _st("h2", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=NAVY, spaceBefore=10, spaceAfter=4)
LBL = _st("lbl", fontSize=8, textColor=MUTED, leading=10)


def P(text, style=BODY):
    return Paragraph(_t(text), style)


class Arrow(Flowable):
    """Gezeichneter Pfeil (hoch / seitwaerts / runter) – unabhaengig von Schriftzeichen."""
    def __init__(self, direction, size=16 * mm):
        super().__init__()
        self.d, self.size = (direction or "flat").lower(), size
        self.width = self.height = size

    def draw(self):
        c, s = self.canv, self.size
        col = {"up": GREEN, "down": RED}.get(self.d, GREY)
        ang = {"up": 40, "down": -40}.get(self.d, 0)
        c.saveState()
        c.translate(s / 2, s / 2)
        c.rotate(ang)
        c.setFillColor(col)
        c.setStrokeColor(col)
        c.setLineWidth(s * 0.16)
        c.setLineCap(1)
        c.line(-s * 0.36, 0, s * 0.12, 0)
        p = c.beginPath()
        p.moveTo(s * 0.44, 0)
        p.lineTo(s * 0.10, s * 0.26)
        p.lineTo(s * 0.10, -s * 0.26)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        c.restoreState()


def _kv(rows):
    rows = [(k, v) for k, v in rows if v]
    if not rows:
        return P("Keine Angaben", SMALL)
    t = Table([[P(k, LBL), P(v)] for k, v in rows], colWidths=[42 * mm, W - 42 * mm - 12])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE)]))
    return t


def _card(title, flow):
    """Abschnitt mit Titel; kurze Abschnitte bleiben zusammen, lange duerfen umbrechen."""
    items = [CondPageBreak(40 * mm), P(title, H2), flow, Spacer(1, 3)]
    return items


def _bullets(items, width=None):
    width = width or W
    items = [i for i in (items or []) if i]
    if not items:
        return P("Keine Angaben", SMALL)
    t = Table([[P("-", BODY), P(i)] for i in items], colWidths=[5 * mm, width - 5 * mm - 12])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 1)]))
    return t


def _horizons(hs):
    hs = [h for h in (hs or []) if isinstance(h, dict)][:3]
    if not hs:
        return None
    cols = []
    for h in hs:
        d = (h.get("direction") or "flat").lower()
        col = {"up": GREEN, "down": RED}.get(d, GREY)
        eff = _st("eff", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=col, alignment=TA_CENTER)
        cell = [P(h.get("period", ""), _st("per", fontName="Helvetica-Bold", fontSize=9, textColor=MUTED, alignment=TA_CENTER)),
                Spacer(1, 3), Arrow(d), Spacer(1, 3),
                P(h.get("price_effect") or "offen", eff), Spacer(1, 4),
                P(h.get("events", ""), _st("ev", fontSize=8.4, leading=11.4)), Spacer(1, 4),
                P(f"Wahrscheinlichkeit: {h.get('probability') or 'unbekannt'}", _st("pr", fontSize=7.6, textColor=MUTED, alignment=TA_CENTER))]
        cols.append(cell)
    gap = 4 * mm
    cw = (W - gap * (len(cols) - 1)) / len(cols)
    row, widths = [], []
    for n, cell in enumerate(cols):
        if n:
            row.append("")
            widths.append(gap)
        row.append(cell)
        widths.append(cw)
    t = Table([row], colWidths=widths, hAlign="LEFT")
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
             ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]
    for i in range(0, len(row), 2):
        style += [("BACKGROUND", (i, 0), (i, 0), SOFT), ("BOX", (i, 0), (i, 0), 0.6, LINE)]
    for i in range(1, len(row), 2):
        style += [("LEFTPADDING", (i, 0), (i, 0), 0), ("RIGHTPADDING", (i, 0), (i, 0), 0)]
    t.setStyle(TableStyle(style))
    return t


def _on_page(canv, doc):
    canv.saveState()
    canv.setStrokeColor(LINE)
    canv.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    canv.setFont("Helvetica", 7.5)
    canv.setFillColor(MUTED)
    canv.drawString(18 * mm, 9.5 * mm, "Portfolio-Agent - KI-Analyse. Keine Anlageberatung; Angaben koennen unvollstaendig oder falsch sein.")
    canv.drawRightString(A4[0] - 18 * mm, 9.5 * mm, f"Seite {doc.page}")
    canv.restoreState()


def build_pdf(d: dict) -> bytes:
    """d = gespeicherte Analyse (inkl. timestamp). Gibt PDF-Bytes zurueck."""
    c, m, r, f = d.get("company") or {}, d.get("market") or {}, d.get("reports") or {}, d.get("financial_health") or {}
    k, o = d.get("competition") or {}, d.get("outlook") or {}
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                          bottomMargin=20 * mm, title=f"Analyse {c.get('name') or d.get('isin')}",
                          author="Portfolio-Agent")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                                                             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)],
                                       onPage=_on_page)])
    story = []

    # Kopfband
    verdict = (o.get("verdict") or "NEUTRAL").upper()
    vcol = {"BULLISH": GREEN, "BEARISH": RED}.get(verdict, GREY)
    ts = d.get("timestamp") or ""
    try:
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        pass
    head = Table([[
        [P(c.get("name") or d.get("isin"), _st("t", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=colors.white)),
         P(" | ".join(x for x in [f"ISIN {d.get('isin')}", c.get("ticker"), c.get("exchange"), c.get("country")] if x),
           _st("s", fontSize=9, textColor=colors.HexColor("#cbd5e1"))),
         P(f"Stand {ts} | {d.get('provider', '')} | {'Live-Recherche' if d.get('live') else 'Nur Modellwissen'}",
           _st("s2", fontSize=8, textColor=colors.HexColor("#94a3b8")))],
        [P(verdict, _st("v", fontName="Helvetica-Bold", fontSize=12, textColor=colors.white, alignment=TA_CENTER, leading=15))],
    ]], colWidths=[W - 36 * mm, 36 * mm])
    head.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), NAVY), ("BACKGROUND", (1, 0), (1, 0), vcol),
                              ("VALIGN", (0, 0), (0, 0), "MIDDLE"), ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
                              ("LEFTPADDING", (0, 0), (0, 0), 14), ("TOPPADDING", (0, 0), (-1, -1), 12),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
    story += [head, Spacer(1, 8)]

    if d.get("data_warning"):
        w = Table([[P("Hinweis: " + d["data_warning"], _st("w", fontSize=8.6, textColor=colors.HexColor("#92400e")))]], colWidths=[W])
        w.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fef3c7")),
                               ("BOX", (0, 0), (-1, -1), 0.6, AMBER), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story += [w, Spacer(1, 6)]
    if (c.get("identification_confidence") or "").lower() == "niedrig":
        story += [P("Zuordnung der ISIN unsicher: " + (c.get("identification_note") or ""), _st("u", textColor=RED)), Spacer(1, 4)]

    story += [P(c.get("business_summary", ""))]
    story += [Spacer(1, 2), _kv([("Branche", c.get("sector")), ("Website", c.get("website"))])]

    # KI-Einschaetzung (Kern), danach Ausblick mit Pfeilen, danach Szenarien
    conf = o.get("confidence")
    story += _card("KI-Einschaetzung", _kv([
        ("Tendenz", f"{verdict}" + (f" | Datenlage {round(conf * 100)} %" if isinstance(conf, (int, float)) else "")),
        ("Horizont", o.get("horizon")), ("These", o.get("thesis"))]))

    hz = _horizons(o.get("horizons"))
    if hz is not None:
        story += [KeepTogether(_card("Ausblick: Was kann passieren?", hz)),
                  P("Szenario-Schaetzungen der KI auf Basis der verfuegbaren Daten - Vermutungen, keine Prognosen. "
                    "Kursspannen sind grobe Annahmen.", SMALL)]

    story += _card("Szenarien und Beobachtungspunkte", _kv([
        ("Bull-Case", o.get("bull_case")), ("Bear-Case", o.get("bear_case")),
        ("Worauf achten", " | ".join(w for w in (o.get("watchpoints") or []) if w))]))

    story += _card("Marktdaten", _kv([("Marktkapitalisierung", m.get("market_cap")), ("Kurs", m.get("price")),
                                      ("Stand", m.get("as_of")), ("Entwicklung 1 Jahr", m.get("change_1y")),
                                      ("Bewertung", m.get("valuation")), ("Analystenmeinung", m.get("analyst_view"))]))

    news = [n for n in (d.get("news") or []) if isinstance(n, dict)]
    if news:
        rows = []
        for n in news:
            col = {"positiv": GREEN, "negativ": RED}.get((n.get("sentiment") or "").lower(), GREY)
            rows.append([P(n.get("date", ""), SMALL),
                         [P(n.get("headline", ""), _st("nh", fontName="Helvetica-Bold", textColor=col)),
                          P(n.get("summary", "")), P(n.get("source", ""), SMALL)]])
        t = Table(rows, colWidths=[22 * mm, W - 22 * mm])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5)]))
        story += _card("Aktuelle News", t)

    mg = [x for x in (d.get("management") or []) if isinstance(x, dict)]
    if mg:
        story += _card("Fuehrungsebene", _bullets([f"{x.get('date', '')}: {x.get('change', '')} {x.get('impact', '')}".strip() for x in mg]))

    ev = [e for e in (r.get("next_events") or []) if isinstance(e, dict)]
    story += _card("Berichte und Kennzahlen", _kv([
        ("Zeitraum", r.get("latest_period")), ("Veroeffentlicht", r.get("published")), ("Umsatz", r.get("revenue")),
        ("Gewinn", r.get("net_income")), ("EPS", r.get("eps")), ("Unternehmensausblick", r.get("guidance")),
        ("Trend", r.get("trend")), ("Highlights", " - ".join(r.get("highlights") or [])),
        ("Kommende Termine", "; ".join(f"{e.get('date', '')} {e.get('event', '')}" for e in ev))]))

    story += _card("Finanzlage", _kv([("Cash / Schulden", f.get("cash_debt")), ("Cashflow", f.get("cash_flow")),
                                      ("Dividende", f.get("dividend")), ("Einschaetzung", f.get("assessment"))]))
    story += _card("Wettbewerb", _kv([("Position", k.get("position")), ("Konkurrenten", ", ".join(k.get("competitors") or [])),
                                      ("Wettbewerbsvorteil", k.get("moat"))]))

    half = W / 2 - 4 * mm
    two = Table([[[P("Katalysatoren", H2), _bullets(d.get("catalysts"), half)],
                  [P("Risiken", H2), _bullets(d.get("risks"), half)]]],
                colWidths=[W / 2, W / 2])
    two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [CondPageBreak(40 * mm), two]

    src = d.get("sources") or []
    if src:
        story += [CondPageBreak(30 * mm), P("Quellen", H2)] + [Paragraph(
            f'<link href="{escape(s["url"], {chr(34): "&quot;"})}" color="#4f46e5">{_t(s.get("title") or s["url"])[:90]}</link>',
            _st("src", fontSize=7.8, leading=10.5)) for s in src[:25] if str(s.get("url", "")).startswith(("http://", "https://"))]

    doc.build(story)
    return buf.getvalue()
