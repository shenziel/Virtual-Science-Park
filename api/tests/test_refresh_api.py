"""Startup refresh and POST /admin/opportunities/refresh, with fake monitors (no network)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import agents.monitors
from api.tests.conftest import auth, login
from contracts.models import Opportunity
from fixtures.loader import MOCK

pytestmark = pytest.mark.skipif(not MOCK.exists(), reason="seeds companies from fixtures/mock")

TODAY = date(2026, 11, 14)
LIVE_VINNOVA = Opportunity(id="vinnova-live-1", type="funding", title="Live call", url="https://www.vinnova.se/e/x",
                           source="Vinnova", deadline=date(2027, 2, 1), topics=["testing"], retrieved_at=TODAY)
BSP_CACHED = Opportunity(id="bsp-cached-1", type="event", title="Cached event", url="https://bsp.example.com/e",
                         source="Blue Science Park", event_date=date(2026, 12, 3), topics=["sensors"],
                         retrieved_at=TODAY, cached_snapshot=True)


@pytest.fixture
def started(db_url, monkeypatch):
    """Start the app with startup refresh ON and the given fake monitor result."""

    def start(fetch):
        monkeypatch.setenv("OPPORTUNITY_REFRESH", "startup")
        monkeypatch.setattr(agents.monitors, "fetch_all_opportunities", fetch)
        from api.main import app

        return TestClient(app)

    return start


def test_startup_refresh_runs_before_serving(started):
    with started(lambda: [LIVE_VINNOVA, BSP_CACHED]) as c:
        opps = {o["id"]: o for o in c.get("/opportunities").json()}
    assert set(opps) == {"vinnova-live-1", "bsp-cached-1"}  # mock opportunities replaced
    assert opps["bsp-cached-1"]["cached_snapshot"] is True and opps["bsp-cached-1"]["is_simulated"] is False
    assert opps["vinnova-live-1"]["cached_snapshot"] is False


def test_startup_with_failed_monitors_serves_empty_not_mock(started):
    def broken():
        raise TimeoutError("vinnova timed out")

    with started(broken) as c:
        assert c.get("/health").status_code == 200  # the API still starts
        assert c.get("/opportunities").json() == []
        assert c.get("/companies/nordsense/recommendations").json() == []


def test_startup_drops_non_live_vinnova(started):
    snapshot_vinnova = LIVE_VINNOVA.model_copy(update={"id": "vinnova-snap", "cached_snapshot": True})
    with started(lambda: [snapshot_vinnova, BSP_CACHED]) as c:
        assert [o["id"] for o in c.get("/opportunities").json()] == ["bsp-cached-1"]


def test_recommendations_only_reference_current_opportunities(started):
    with started(lambda: [LIVE_VINNOVA, BSP_CACHED]) as c:
        recs = c.get("/companies/nordsense/recommendations").json()
    assert {r["opportunity_id"] for r in recs} <= {"vinnova-live-1", "bsp-cached-1"}


def test_refresh_off_keeps_seeded_opportunities(client):
    assert len(client.get("/opportunities").json()) == 6


@pytest.mark.parametrize("who,status", [
    (None, 401),
    (("demo@nordsense.example.com", "demo-nordsense-2026"), 403),
    (("admin@bsp.example.com", "demo-admin-2026"), 200),
])
def test_admin_refresh_permissions(client, monkeypatch, who, status):
    monkeypatch.setattr(agents.monitors, "fetch_all_opportunities", lambda: [LIVE_VINNOVA, BSP_CACHED])
    headers = auth(login(client, *who)["access_token"]) if who else {}
    r = client.post("/admin/opportunities/refresh", headers=headers)
    assert r.status_code == status
    if status == 200:
        body = r.json()
        assert body["stored"] == 2 and body["vinnova"] == 1 and body["removed"] == 6 and body["failed"] is False
        assert sorted(body["rematched"]) == ["greenloop", "medtrace", "nordsense"]
        assert {o["id"] for o in client.get("/opportunities").json()} == {"vinnova-live-1", "bsp-cached-1"}
    else:
        assert len(client.get("/opportunities").json()) == 6  # nothing changed


def test_admin_refresh_reports_failure(client, monkeypatch):
    def broken():
        raise ConnectionError("down")

    monkeypatch.setattr(agents.monitors, "fetch_all_opportunities", broken)
    token = login(client, "admin@bsp.example.com", "demo-admin-2026")["access_token"]
    body = client.post("/admin/opportunities/refresh", headers=auth(token)).json()
    assert body["failed"] is True and body["stored"] == 0
    assert client.get("/opportunities").json() == []
