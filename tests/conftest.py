import base64
import os
import pathlib
import sys
import tempfile

import pytest

# Vor dem Import der App: isolierte Test-Umgebung (nie die echte .env/Datenbank verwenden)
_TMP = tempfile.mkdtemp(prefix="portfolio-agent-test-")
os.environ.update({
    "DB_PATH": f"{_TMP}/portfolio.db",
    "DASHBOARD_PASSWORD": "testpw",
    "BACKUP_ENABLED": "false",
    "IBKR_DRY_RUN": "true",
    "LLM_PROVIDER": "ollama",
})
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

AUTH = {"Authorization": "Basic " + base64.b64encode(b"user:testpw").decode()}


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from src.agent.api.main import app
    with TestClient(app) as c:
        c.headers.update(AUTH)
        yield c


@pytest.fixture()
def db(client):
    from src.agent.db import get_session
    s = get_session()
    yield s
    s.close()
