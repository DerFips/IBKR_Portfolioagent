"""Zeitplan fuer automatische Runs (AGENT_RUN_HOUR/MINUTE/DAYS), standardmaessig AUS."""
import asyncio
import logging
from datetime import date, datetime

log = logging.getLogger(__name__)
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_days(spec: str) -> set[int]:
    """'mon-fri', 'mon,wed,fri' oder 'sat-mon' -> Menge von Wochentagen (0=Montag)."""
    out: set[int] = set()
    for part in (spec or "").lower().replace(" ", "").split(","):
        if "-" in part:
            a, _, b = part.partition("-")
            if a in _DAYS and b in _DAYS:
                i, j = _DAYS.index(a), _DAYS.index(b)
                out.update({(i + k) % 7 for k in range((j - i) % 7 + 1)})
        elif part in _DAYS:
            out.add(_DAYS.index(part))
    return out


def is_due(now: datetime, hour: int, minute: int, days: set[int], last_run_day: date | None) -> bool:
    return (now.weekday() in days and last_run_day != now.date()
            and (now.hour, now.minute) >= (hour, minute))


async def loop() -> None:
    from .api.deps import SessionLocal
    from .api.routers import control_router
    from .db import repository as repo
    from .settings import Settings
    last: date | None = None
    while True:
        try:
            s = Settings()
            if s.agent_schedule_enabled and not control_router._run_state["running"]:
                if is_due(datetime.now(), s.agent_run_hour, s.agent_run_minute, parse_days(s.agent_run_days), last):
                    last = date.today()
                    db = SessionLocal()
                    try:
                        run = repo.create_run(db=db, market_view="running", summary="Laeuft (Zeitplan)...", raw="")
                        run_id = run.id
                    finally:
                        db.close()
                    log.info(f"Zeitplan: starte Run {run_id}")
                    asyncio.create_task(control_router._execute_run(run_id, SessionLocal))
        except Exception as e:
            log.error(f"Zeitplan-Fehler: {e}")
        await asyncio.sleep(30)
