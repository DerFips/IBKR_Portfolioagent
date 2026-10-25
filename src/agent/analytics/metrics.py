"""Kennzahlen aus Kursreihen (reine Python-Funktionen, ohne Zusatzpakete).

Eine Reihe ist eine nach Datum sortierte Liste von (date, close).
"""
import math
from statistics import mean, pstdev

Series = list[tuple]   # [(date, close), ...]


def returns(series: Series) -> list[tuple]:
    """Tagesrenditen als [(date, r)], r als Bruch."""
    return [(d1, c1 / c0 - 1) for (d0, c0), (d1, c1) in zip(series, series[1:]) if c0]


def period_return(series: Series, days: int) -> float | None:
    """Rendite ueber die letzten `days` Handelstage in %."""
    if len(series) <= days or not series[-days - 1][1]:
        return None
    return (series[-1][1] / series[-days - 1][1] - 1) * 100


def annual_vol(series: Series) -> float | None:
    """Annualisierte Volatilitaet in % (Stdabw. der Tagesrenditen * sqrt(252))."""
    r = [x for _, x in returns(series)]
    return pstdev(r) * math.sqrt(252) * 100 if len(r) >= 20 else None


def high_low(series: Series, days: int = 252) -> tuple[float, float] | None:
    w = [c for _, c in series[-days:]]
    return (max(w), min(w)) if w else None


def max_drawdown(series: Series) -> float | None:
    """Groesster Rueckgang vom Hoch in % (negativ)."""
    peak, worst = None, 0.0
    for _, c in series:
        peak = c if peak is None else max(peak, c)
        worst = min(worst, c / peak - 1)
    return worst * 100 if series else None


def _aligned(a: Series, b: Series) -> tuple[list[float], list[float]]:
    rb = dict(returns(b))
    pairs = [(r, rb[d]) for d, r in returns(a) if d in rb]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def correlation(a: Series, b: Series, min_obs: int = 30) -> float | None:
    x, y = _aligned(a, b)
    if len(x) < min_obs:
        return None
    mx, my = mean(x), mean(y)
    sx, sy = pstdev(x), pstdev(y)
    if not sx or not sy:
        return None
    return sum((i - mx) * (j - my) for i, j in zip(x, y)) / len(x) / (sx * sy)


def beta(asset: Series, bench: Series, min_obs: int = 30) -> float | None:
    """Beta = Cov(asset, bench) / Var(bench) auf Tagesrenditen."""
    x, y = _aligned(asset, bench)
    if len(x) < min_obs:
        return None
    my = mean(y)
    var = sum((j - my) ** 2 for j in y) / len(y)
    if not var:
        return None
    mx = mean(x)
    return sum((i - mx) * (j - my) for i, j in zip(x, y)) / len(x) / var


def rebase(series: Series, base: float = 100.0) -> list[tuple]:
    return [(d, c / series[0][1] * base) for d, c in series] if series and series[0][1] else []


def summarize(series: Series) -> dict:
    """Kennzahlen fuer Prompt und Snapshot (fehlende Werte = None)."""
    hl = high_low(series)
    last = series[-1][1] if series else None
    return {
        "ret_1m": period_return(series, 21), "ret_3m": period_return(series, 63),
        "ret_6m": period_return(series, 126), "volatility": annual_vol(series),
        "high_52w": hl[0] if hl else None, "low_52w": hl[1] if hl else None,
        "from_high_pct": (last / hl[0] - 1) * 100 if hl and last else None,
        "max_drawdown": max_drawdown(series[-252:]),
    }


def portfolio_series(series_by_symbol: dict[str, Series], weights: dict[str, float],
                     start_value: float = 100.0) -> list[tuple]:
    """Wertverlauf eines Depots mit festen Gewichten (aktuelle Bestaende rueckgerechnet).

    Nur Tage, an denen alle Titel einen Kurs haben; taegliche Renditen gewichtet summiert.
    """
    syms = [s for s in weights if s in series_by_symbol and len(series_by_symbol[s]) > 1]
    if not syms:
        return []
    rets = {s: dict(returns(series_by_symbol[s])) for s in syms}
    common = sorted(set.intersection(*[set(r) for r in rets.values()]))
    wsum = sum(weights[s] for s in syms) or 1.0
    value, out = start_value, []
    for d in common:
        value *= 1 + sum(weights[s] / wsum * rets[s][d] for s in syms)
        out.append((d, value))
    return out


def corr_matrix(series_by_symbol: dict[str, Series], min_obs: int = 30) -> dict:
    syms = [s for s, v in series_by_symbol.items() if len(v) > min_obs]
    m = [[1.0 if a == b else correlation(series_by_symbol[a], series_by_symbol[b], min_obs)
          for b in syms] for a in syms]
    return {"symbols": syms, "matrix": m}
