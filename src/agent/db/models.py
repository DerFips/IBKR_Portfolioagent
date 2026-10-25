from datetime import datetime, timezone
from sqlalchemy import (Column, Integer, String, Float, Boolean,
                        DateTime, Date, Text, ForeignKey, UniqueConstraint, Index)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    timestamp    = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    market_view  = Column(String(32), default="neutral")
    summary      = Column(Text, default="")
    raw_response = Column(Text, default="")
    snapshots    = relationship("PortfolioSnapshot", back_populates="run",
                                cascade="all, delete-orphan")
    actions      = relationship("ActionRecord", back_populates="run",
                                cascade="all, delete-orphan")


class PortfolioSnapshot(Base):
    __tablename__  = "portfolio_snapshots"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    run_id         = Column(Integer, ForeignKey("agent_runs.id"), nullable=False)
    symbol         = Column(String(16), nullable=False)
    quantity       = Column(Float, default=0)
    avg_cost       = Column(Float, default=0)
    current_price  = Column(Float, default=0)
    market_value   = Column(Float, default=0)
    unrealized_pnl = Column(Float, default=0)
    weight         = Column(Float, default=0)
    currency       = Column(String(8), default="USD")
    sector         = Column(String(64), default="")
    conid          = Column(Integer, default=0)
    isin           = Column(String(16), default="")
    wkn            = Column(String(8), default="")
    exchange       = Column(String(32), default="")
    ret_1m         = Column(Float, nullable=True)     # Kennzahlen aus der Kurshistorie
    ret_3m         = Column(Float, nullable=True)
    ret_6m         = Column(Float, nullable=True)
    volatility     = Column(Float, nullable=True)     # annualisiert, in %
    high_52w       = Column(Float, nullable=True)
    low_52w        = Column(Float, nullable=True)
    run            = relationship("AgentRun", back_populates="snapshots")


class ActionRecord(Base):
    __tablename__  = "action_records"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    run_id         = Column(Integer, ForeignKey("agent_runs.id"), nullable=False)
    symbol         = Column(String(16), nullable=False)
    action         = Column(String(16), nullable=False)
    confidence     = Column(Float, default=0.0)
    rationale      = Column(Text, default="")
    risk_level     = Column(String(16), default="MEDIUM")
    approved       = Column(Boolean, default=False)
    executed       = Column(Boolean, default=False)
    risk_blocked   = Column(Boolean, default=False)
    conid          = Column(Integer, default=0)
    isin           = Column(String(16), default="")
    wkn            = Column(String(8), default="")
    run            = relationship("AgentRun", back_populates="actions")


class DailyNav(Base):
    __tablename__   = "daily_nav"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    date            = Column(Date, unique=True, nullable=False)
    net_liquidation = Column(Float, default=0)
    cash            = Column(Float, default=0)
    equity_value    = Column(Float, default=0)
    position_count  = Column(Integer, default=0)


class OrderRecord(Base):
    __tablename__ = "order_records"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    symbol      = Column(String(16), nullable=False)
    action      = Column(String(16), nullable=False)
    quantity    = Column(Float, default=0)
    price       = Column(Float, default=0)
    fill_price  = Column(Float, nullable=True)
    status      = Column(String(32), default="PENDING")
    dry_run     = Column(Boolean, default=True)
    commission  = Column(Float, nullable=True)
    conid       = Column(Integer, default=0)
    isin        = Column(String(16), default="")
    wkn         = Column(String(8), default="")


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    id     = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(16), unique=True, nullable=False)
    active = Column(Boolean, default=True)
    conid  = Column(Integer, default=0)
    isin   = Column(String(16), default="")
    wkn    = Column(String(8), default="")


class AlertRule(Base):
    __tablename__  = "alert_rules"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    symbol         = Column(String(16), nullable=False)
    condition      = Column(String(32), nullable=False)
    threshold      = Column(Float, nullable=False)
    triggered      = Column(Boolean, default=False)
    last_triggered = Column(DateTime, nullable=True)


class SentimentRecord(Base):
    __tablename__ = "sentiment_records"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    symbol    = Column(String(16), nullable=False)
    score     = Column(Float, default=0.0)
    source    = Column(String(64), default="")
    headline  = Column(Text, default="")


class Setting(Base):
    __tablename__ = "settings"
    key   = Column(String(128), primary_key=True)
    value = Column(Text, default="")


class ScanResult(Base):
    """Letztes Ergebnis je Markt-Scan (market | discover | penny), ueberlebt Neustarts."""
    __tablename__ = "scan_results"
    kind      = Column(String(32), primary_key=True)
    timestamp = Column(String(40), default="")
    payload   = Column(Text, default="{}")


class CompanyAnalysis(Base):
    """Unternehmensanalysen pro ISIN (Verlauf bleibt erhalten)."""
    __tablename__ = "company_analyses"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    isin      = Column(String(16), nullable=False, index=True)
    name      = Column(String(128), default="")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    provider  = Column(String(64), default="")
    live      = Column(Boolean, default=False)
    payload   = Column(Text, default="{}")


class PriceBar(Base):
    """Tagesschlusskurse (aus IBKR) fuer Kennzahlen, Korrelationen und Benchmark."""
    __tablename__ = "price_bars"
    id     = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False)
    date   = Column(Date, nullable=False)
    close  = Column(Float, nullable=False)
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_price_symbol_date"),
                      Index("ix_price_symbol", "symbol"))


class CalendarEvent(Base):
    """Termine: aus Analysen extrahiert (Zahlen, Hauptversammlung ...) oder manuell."""
    __tablename__ = "calendar_events"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    date        = Column(Date, nullable=False, index=True)
    title       = Column(String(200), nullable=False)
    kind        = Column(String(16), default="other")      # earnings|dividend|agm|other
    isin        = Column(String(16), default="")
    symbol      = Column(String(32), default="")
    source      = Column(String(16), default="manual")     # analysis|manual
    analysis_id = Column(Integer, nullable=True)
    approx      = Column(Boolean, default=False)           # nur Monat bekannt
    note        = Column(Text, default="")
