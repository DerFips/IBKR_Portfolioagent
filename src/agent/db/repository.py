from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from .models import (AgentRun, PortfolioSnapshot, ActionRecord,
                     DailyNav, OrderRecord, WatchlistItem,
                     AlertRule, SentimentRecord, Setting)


def create_run(db: Session, market_view: str, summary: str, raw: str) -> AgentRun:
    r = AgentRun(market_view=market_view, summary=summary, raw_response=raw)
    db.add(r); db.commit(); db.refresh(r); return r

def update_run_summary(db: Session, run_id: int,
                       summary: str, market_view: str,
                       raw: str = "") -> None:
    run = db.get(AgentRun, run_id)
    if run:
        run.summary = summary; run.market_view = market_view
        if raw: run.raw_response = raw
        db.commit()

def get_runs(db: Session, limit: int = 50) -> list[AgentRun]:
    return db.execute(
        select(AgentRun).order_by(desc(AgentRun.timestamp)).limit(limit)
    ).scalars().all()

def get_run(db: Session, run_id: int) -> AgentRun | None:
    return db.execute(
        select(AgentRun).where(AgentRun.id == run_id)
    ).scalar_one_or_none()

def get_latest_run(db: Session) -> AgentRun | None:
    return db.execute(
        select(AgentRun).order_by(desc(AgentRun.timestamp)).limit(1)
    ).scalar_one_or_none()

def save_snapshots(db: Session, run_id: int, positions: list[dict]) -> None:
    for p in positions:
        db.add(PortfolioSnapshot(run_id=run_id, **p))
    db.commit()

def get_snapshots(db: Session, run_id: int) -> list[PortfolioSnapshot]:
    return db.execute(
        select(PortfolioSnapshot).where(PortfolioSnapshot.run_id == run_id)
    ).scalars().all()

def save_actions(db: Session, run_id: int, actions: list[dict]) -> list[ActionRecord]:
    recs = []
    for a in actions:
        recs.append(ActionRecord(
            run_id       = run_id,
            symbol       = a["symbol"],
            action       = a["action"],
            confidence   = a.get("confidence", 0.0),
            rationale    = a.get("rationale", ""),
            risk_level   = a.get("risk_level", "MEDIUM"),
            approved     = a.get("approved", False),
            executed     = a.get("executed", False),
            risk_blocked = a.get("risk_blocked", False),
            conid        = a.get("conid", 0),
            isin         = a.get("isin", ""),
            wkn          = a.get("wkn", ""),
        ))
        db.add(recs[-1])
    db.commit()
    return recs

def get_actions(db: Session, run_id: int) -> list[ActionRecord]:
    return db.execute(
        select(ActionRecord).where(ActionRecord.run_id == run_id)
    ).scalars().all()

def get_all_pending_actions(db: Session) -> list[ActionRecord]:
    return db.execute(
        select(ActionRecord).where(
            ActionRecord.approved == False,
            ActionRecord.executed == False,
            ActionRecord.risk_blocked == False,
        )
    ).scalars().all()

def approve_action(db: Session, action_id: int) -> ActionRecord | None:
    r = db.execute(
        select(ActionRecord).where(ActionRecord.id == action_id)
    ).scalar_one_or_none()
    if r: r.approved = True; db.commit()
    return r

def mark_executed(db: Session, action_id: int, risk_blocked: bool = False) -> None:
    r = db.execute(
        select(ActionRecord).where(ActionRecord.id == action_id)
    ).scalar_one_or_none()
    if r: r.executed = True; r.risk_blocked = risk_blocked; db.commit()

def upsert_daily_nav(db: Session, nav_date, net_liq: float,
                     cash: float, equity: float, pos_count: int) -> None:
    r = db.execute(
        select(DailyNav).where(DailyNav.date == nav_date)
    ).scalar_one_or_none()
    if r:
        r.net_liquidation = net_liq; r.cash = cash
        r.equity_value = equity; r.position_count = pos_count
    else:
        db.add(DailyNav(date=nav_date, net_liquidation=net_liq,
                        cash=cash, equity_value=equity, position_count=pos_count))
    db.commit()

def get_nav_history(db: Session, days: int = 90) -> list[DailyNav]:
    return db.execute(
        select(DailyNav).order_by(DailyNav.date).limit(days)
    ).scalars().all()

def save_order(db: Session, **kwargs) -> OrderRecord:
    r = OrderRecord(**kwargs); db.add(r); db.commit(); db.refresh(r); return r

def get_orders(db: Session, limit: int = 100) -> list[OrderRecord]:
    return db.execute(
        select(OrderRecord).order_by(desc(OrderRecord.timestamp)).limit(limit)
    ).scalars().all()

def get_watchlist(db: Session) -> list[WatchlistItem]:
    return db.execute(
        select(WatchlistItem).where(WatchlistItem.active == True)
    ).scalars().all()

def add_to_watchlist(db: Session, symbol: str, isin: str = "", wkn: str = "",
                     conid: int = 0) -> WatchlistItem:
    """Fuegt hinzu/reaktiviert; vorhandene Kennungen werden nur ergaenzt, nie geloescht."""
    i = db.execute(
        select(WatchlistItem).where(WatchlistItem.symbol == symbol.upper())
    ).scalar_one_or_none()
    if i:
        i.active = True
    else:
        i = WatchlistItem(symbol=symbol.upper())
        db.add(i)
    i.isin  = isin  or i.isin  or ""
    i.wkn   = wkn   or i.wkn   or ""
    i.conid = conid or i.conid or 0
    db.commit(); db.refresh(i); return i


def find_known_ids(db: Session, symbol: str) -> dict:
    """Kennungen eines Symbols aus dem juengsten Portfolio-Snapshot, der sie kennt."""
    row = db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.symbol == symbol.upper(), PortfolioSnapshot.isin != "")
        .order_by(desc(PortfolioSnapshot.id)).limit(1)
    ).scalar_one_or_none()
    return {"isin": row.isin, "wkn": row.wkn or "", "conid": row.conid or 0} if row else {}


def remove_from_watchlist(db: Session, symbol: str) -> None:
    i = db.execute(
        select(WatchlistItem).where(WatchlistItem.symbol == symbol.upper())
    ).scalar_one_or_none()
    if i: i.active = False; db.commit()

def get_alerts(db: Session) -> list[AlertRule]:
    return db.execute(select(AlertRule)).scalars().all()

def create_alert(db: Session, symbol: str,
                 condition: str, threshold: float) -> AlertRule:
    r = AlertRule(symbol=symbol.upper(), condition=condition, threshold=threshold)
    db.add(r); db.commit(); db.refresh(r); return r

def trigger_alert(db: Session, alert_id: int) -> None:
    r = db.execute(
        select(AlertRule).where(AlertRule.id == alert_id)
    ).scalar_one_or_none()
    if r: r.triggered = True; r.last_triggered = datetime.utcnow(); db.commit()

def save_sentiment(db: Session, symbol: str, score: float,
                   source: str = "", headline: str = "") -> None:
    db.add(SentimentRecord(symbol=symbol.upper(), score=score,
                           source=source, headline=headline)); db.commit()

def get_latest_sentiments(db: Session, limit: int = 30) -> list[dict]:
    rows = db.execute(
        select(SentimentRecord)
        .order_by(desc(SentimentRecord.timestamp)).limit(limit)
    ).scalars().all()
    return [{"symbol": r.symbol, "score": r.score, "source": r.source,
             "headline": r.headline, "timestamp": r.timestamp.isoformat()}
            for r in rows]

def get_setting(db: Session, key: str) -> str | None:
    from .. import secrets
    r = db.execute(
        select(Setting).where(Setting.key == key)
    ).scalar_one_or_none()
    return secrets.decrypt(r.value) if r else None

def set_setting(db: Session, key: str, value: str) -> None:
    from .. import secrets
    stored = secrets.encrypt(value) if (secrets.is_secret_key(key) and value) else value
    r = db.execute(
        select(Setting).where(Setting.key == key)
    ).scalar_one_or_none()
    if r: r.value = stored
    else: db.add(Setting(key=key, value=stored))
    db.commit()

def get_all_settings(db: Session) -> dict[str, str]:
    """Alle Einstellungen im Klartext; nicht entschluesselbare Werte fehlen (-> .env gilt)."""
    import logging
    from .. import secrets
    out = {}
    for r in db.execute(select(Setting)).scalars().all():
        val = secrets.decrypt(r.value or "")
        if val is None:
            logging.getLogger(__name__).warning(
                f"Einstellung {r.key} nicht entschluesselbar (anderer Schluessel) – bitte neu eintragen")
            continue
        out[r.key] = val
    return out

def encrypt_plain_secrets(db: Session) -> int:
    """Migration: bisher im Klartext gespeicherte Geheimnisse verschluesseln."""
    from .. import secrets
    n = 0
    for r in db.execute(select(Setting)).scalars().all():
        if secrets.is_secret_key(r.key) and r.value and not r.value.startswith(secrets.PREFIX):
            r.value = secrets.encrypt(r.value); n += 1
    db.commit()
    return n


def save_scan(db: Session, kind: str, payload: dict) -> None:
    import json
    from .models import ScanResult
    row = db.get(ScanResult, kind) or ScanResult(kind=kind)
    row.timestamp = payload.get("timestamp") or ""
    row.payload   = json.dumps(payload, ensure_ascii=False)
    db.merge(row)
    db.commit()


def load_scan(db: Session, kind: str) -> dict | None:
    import json
    from .models import ScanResult
    row = db.get(ScanResult, kind)
    if not row:
        return None
    try:
        return json.loads(row.payload)
    except Exception:
        return None


def upsert_price_bars(db: Session, symbol: str, series: list[tuple]) -> None:
    """Tagesschlusskurse speichern (vorhandene Tage werden aktualisiert)."""
    from sqlalchemy.dialects.sqlite import insert
    from .models import PriceBar
    if not series:
        return
    rows = [{"symbol": symbol, "date": d, "close": c} for d, c in series]
    stmt = insert(PriceBar).values(rows)
    db.execute(stmt.on_conflict_do_update(index_elements=["symbol", "date"],
                                          set_={"close": stmt.excluded.close}))
    db.commit()


def get_series(db: Session, symbol: str, days: int = 400) -> list[tuple]:
    from .models import PriceBar
    rows = db.execute(select(PriceBar).where(PriceBar.symbol == symbol)
                      .order_by(desc(PriceBar.date)).limit(days)).scalars().all()
    return [(r.date, r.close) for r in reversed(rows)]
