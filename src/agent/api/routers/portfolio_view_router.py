"""Portfolio-Sicht: Verteilung, Risiko, Korrelationen, Verlauf vs. Benchmark, Stresstest, Gebuehren."""
from collections import defaultdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, func
from sqlalchemy.orm import Session

from ..deps import get_db
from ...analytics import metrics as M
from ...db.models import AgentRun, DailyNav, OrderRecord
from ...db.repository import get_series, get_snapshots
from ...settings import Settings

router = APIRouter(prefix="/api/portfolio-view", tags=["Portfolio-Sicht"])

COUNTRY = {"US": "USA", "DE": "Deutschland", "CH": "Schweiz", "FR": "Frankreich", "NL": "Niederlande",
           "GB": "Grossbritannien", "IE": "Irland", "LU": "Luxemburg", "CA": "Kanada", "JP": "Japan",
           "CN": "China", "KY": "Kaimaninseln", "DK": "Daenemark", "SE": "Schweden", "ES": "Spanien",
           "IT": "Italien", "AT": "Oesterreich", "AU": "Australien"}


def _latest_positions(db: Session):
    run = db.execute(select(AgentRun).order_by(desc(AgentRun.timestamp)).limit(1)).scalar_one_or_none()
    return (run, get_snapshots(db, run.id)) if run else (None, [])


def _group(pos, keyfn):
    total = sum(abs(p.market_value) for p in pos) or 1.0
    agg = defaultdict(float)
    for p in pos:
        agg[keyfn(p)] += abs(p.market_value)
    return sorted(({"name": k, "value": v, "pct": v / total * 100} for k, v in agg.items()),
                  key=lambda x: -x["value"])


def _bench(db, s: Settings):
    sym = (s.benchmark_symbol or "").strip().upper()
    return (sym, get_series(db, f"__BENCH__{sym}")) if sym else ("", [])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    s = Settings()
    run, pos = _latest_positions(db)
    if not pos:
        return {"empty": True}
    nav = db.execute(select(DailyNav).order_by(desc(DailyNav.date)).limit(1)).scalar_one_or_none()
    total = sum(abs(p.market_value) for p in pos) or 1.0
    weights = {p.symbol: abs(p.market_value) for p in pos}
    series = {p.symbol: get_series(db, p.symbol) for p in pos}
    series = {k: v for k, v in series.items() if len(v) > 30}
    bsym, bench = _bench(db, s)

    # Hypothetischer Verlauf: aktuelle Bestaende ueber das letzte Jahr rueckgerechnet
    hypo = M.portfolio_series(series, weights)
    bench_hypo = []
    if hypo and bench:
        dates = {d for d, _ in hypo}
        b = [(d, c) for d, c in bench if d in dates]
        bench_hypo = M.rebase(b)
        hypo = M.rebase([(d, v) for d, v in hypo if d >= (b[0][0] if b else hypo[0][0])])
    elif hypo:
        hypo = M.rebase(hypo)

    stored = [(r.date, r.net_liquidation) for r in db.execute(select(DailyNav).order_by(DailyNav.date)).scalars().all()]
    cm = M.corr_matrix(series)
    pairs = sorted(({"a": a, "b": b_, "corr": cm["matrix"][i][j]}
                    for i, a in enumerate(cm["symbols"]) for j, b_ in enumerate(cm["symbols"])
                    if j > i and cm["matrix"][i][j] is not None), key=lambda x: -x["corr"])
    top = sorted(pos, key=lambda p: -abs(p.market_value))
    hhi = sum((abs(p.market_value) / total * 100) ** 2 for p in pos)   # 0..10000
    fees = db.execute(select(func.coalesce(func.sum(OrderRecord.commission), 0.0), func.count(OrderRecord.id))
                      .where(OrderRecord.dry_run == False)).one()  # noqa: E712
    pf_beta = M.beta(hypo_raw, bench) if (hypo_raw := M.portfolio_series(series, weights)) and bench else None

    return {
        "run_timestamp": run.timestamp.isoformat(),
        "nav": nav.net_liquidation if nav else None, "cash": nav.cash if nav else None,
        "cash_pct": (nav.cash / nav.net_liquidation * 100) if nav and nav.net_liquidation else None,
        "equity_value": total, "position_count": len(pos),
        "allocation": {
            "sector": _group(pos, lambda p: p.sector or "Unbekannt"),
            "currency": _group(pos, lambda p: p.currency or "?"),
            "country": _group(pos, lambda p: COUNTRY.get((p.isin or "")[:2], (p.isin or "")[:2] or "Unbekannt")),
        },
        "concentration": {"top3_pct": sum(abs(p.market_value) for p in top[:3]) / total * 100,
                          "largest": top[0].symbol, "largest_pct": abs(top[0].market_value) / total * 100,
                          "hhi": hhi, "effective_positions": 10000 / hhi if hhi else None},
        "risk": {"portfolio_vol": M.annual_vol(M.portfolio_series(series, weights)),
                 "portfolio_drawdown": M.max_drawdown(M.portfolio_series(series, weights)),
                 "portfolio_beta": pf_beta, "covered": f"{len(series)}/{len(pos)}"},
        "positions": [{"symbol": p.symbol, "weight": abs(p.market_value) / total * 100, "sector": p.sector or "",
                       "ret_1m": p.ret_1m, "ret_3m": p.ret_3m, "ret_6m": p.ret_6m, "volatility": p.volatility,
                       "beta": M.beta(series[p.symbol], bench) if p.symbol in series and bench else None}
                      for p in top],
        "correlation": {**cm, "top_pairs": pairs[:5], "bottom_pairs": pairs[-3:][::-1] if len(pairs) > 5 else []},
        "history": {"benchmark": bsym,
                    "hypothetical": [(str(d), round(v, 2)) for d, v in hypo],
                    "benchmark_hypothetical": [(str(d), round(v, 2)) for d, v in bench_hypo],
                    "stored_nav": [(str(d), v) for d, v in stored]},
        "fees": {"total": fees[0], "orders": fees[1]},
    }


class StressIn(BaseModel):
    market_pct: float = Field(-20.0, ge=-90, le=90)
    sectors: dict[str, float] = Field(default_factory=dict)


@router.post("/stress")
def stress(body: StressIn, db: Session = Depends(get_db)):
    """Szenario: Markt (je Position mit ihrem Beta) plus optionale Branchenschocks in %."""
    s = Settings()
    run, pos = _latest_positions(db)
    if not pos:
        return {"empty": True}
    _, bench = _bench(db, s)
    nav = db.execute(select(DailyNav).order_by(desc(DailyNav.date)).limit(1)).scalar_one_or_none()
    rows, total_change = [], 0.0
    for p in pos:
        b = M.beta(get_series(db, p.symbol), bench) if bench else None
        beta, assumed = (b, False) if b is not None else (1.0, True)
        sector_shock = body.sectors.get(p.sector or "Unbekannt", 0.0)
        impact = beta * body.market_pct + sector_shock
        change = p.market_value * impact / 100
        total_change += change
        rows.append({"symbol": p.symbol, "sector": p.sector or "Unbekannt", "beta": beta, "beta_assumed": assumed,
                     "impact_pct": impact, "change": change, "value": p.market_value})
    base = nav.net_liquidation if nav and nav.net_liquidation else sum(abs(p.market_value) for p in pos)
    return {"rows": sorted(rows, key=lambda r: r["change"]), "total_change": total_change,
            "total_pct_of_nav": total_change / base * 100 if base else None, "base": base,
            "note": "Vereinfachtes Szenario: Beta aus 1 Jahr Tagesrenditen; ohne Benchmark-Daten wird Beta 1,0 angenommen."}
