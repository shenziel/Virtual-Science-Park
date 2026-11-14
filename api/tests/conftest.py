import pytest
from fastapi.testclient import TestClient

from fixtures.loader import MOCK


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    """A fresh SQLite file per test, seeded from fixtures/mock on app startup."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("SEED_DIR", str(MOCK))
    # No network in tests: refresh tests enable it explicitly with fake monitors.
    monkeypatch.setenv("OPPORTUNITY_REFRESH", "off")
    # Never call a real model from tests, even if your .env holds keys.
    for key in ("CHAT_API_KEY", "MATCHER_API_KEY", "MODEL_API_KEY", "MONITOR_API_KEY"):
        monkeypatch.setenv(key, "")
    return url


@pytest.fixture
def client(db_url):
    from api.main import app

    with TestClient(app) as c:  # runs the startup hook (create tables, seed)
        yield c


def login(client, email="demo@nordsense.example.com", password="demo-nordsense-2026"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def auth(token):
    return {"Authorization": f"Bearer {token}"}
