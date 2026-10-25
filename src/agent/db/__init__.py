from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .models import Base

_engine = None
_Session = None


def init_db(db_path: str = "data/portfolio.db"):
    global _engine, _Session
    import pathlib
    pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(_engine)
    _add_missing_columns(_engine)
    _Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def migrate() -> None:
    """Fehlende Tabellen/Spalten ergaenzen (z.B. nach dem Einspielen eines aelteren Backups)."""
    Base.metadata.create_all(_engine)
    _add_missing_columns(_engine)


def get_session() -> Session:
    if _Session is None:
        raise RuntimeError("init_db() wurde noch nicht aufgerufen")
    return _Session()


def SessionLocal() -> Session:
    """Neue DB-Session fuer BackgroundTasks."""
    return get_session()


def _add_missing_columns(engine) -> None:
    """Leichte Migration: neue Modell-Spalten in bestehende SQLite-Tabellen eintragen."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}'))
