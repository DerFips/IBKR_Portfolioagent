import asyncio
import os
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, scheduler
from ..db import init_db, SessionLocal
from ..db.repository import encrypt_plain_secrets, get_all_settings
from ..settings import Settings
from .security import security_middleware
from .routers import (control_router, runs_router, portfolio_router,
                      actions_router, analytics_router, watchlist_router,
                      alerts_router, orders_router, settings_router,
                      market_router, analysis_router, calendar_router,
                      portfolio_view_router, backup_router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(Settings().db_path)
    db = SessionLocal()
    try:
        encrypt_plain_secrets(db)            # Altbestand im Klartext -> verschluesselt
        # Im Dashboard gespeicherte Einstellungen (inkl. API-Keys) nach Neustart wieder aktivieren
        for k, v in get_all_settings(db).items():
            os.environ[k] = v
    finally:
        db.close()
    market_router.restore_scans()
    tasks = [asyncio.create_task(backup_router.scheduler()), asyncio.create_task(scheduler.loop())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Portfolio-Agent API", version=__version__, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.middleware("http")(security_middleware)

for r in (control_router, runs_router, portfolio_router, actions_router, analytics_router,
          watchlist_router, alerts_router, orders_router, settings_router, market_router,
          analysis_router, calendar_router, portfolio_view_router, backup_router):
    app.include_router(r.router)

_static = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


@app.get("/")
def index():
    return FileResponse(str(_static / "dashboard.html"))
