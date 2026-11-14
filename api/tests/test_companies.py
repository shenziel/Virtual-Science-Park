"""Companies, claims, visibility, recommendations, opportunities and feedback.

Mock data: nordsense + medtrace are published, greenloop is private.
Every write endpoint has visitor (401), other company (403), own and admin cases.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from api.tests.conftest import auth, login
from db import database
from fixtures.loader import MOCK

pytestmark = pytest.mark.skipif(not MOCK.exists(), reason="uses the mock demo data")

ACCOUNTS = {
    "admin": ("admin@bsp.example.com", "demo-admin-2026"),
    "nordsense": ("demo@nordsense.example.com", "demo-nordsense-2026"),
    "greenloop": ("demo@greenloop.example.com", "demo-greenloop-2026"),
    "medtrace": ("demo@medtrace.example.com", "demo-medtrace-2026"),
}


@pytest.fixture
def as_(client):
    """as_("nordsense") -> auth headers for that account; as_(None) -> visitor."""
    cache = {}

    def headers(who):
        if who is None:
            return {}
        if who not in cache:
            cache[who] = auth(login(client, *ACCOUNTS[who])["access_token"])
        return cache[who]

    return headers


def ids(resp):
    return {c["company_id"] for c in resp.json()}


# ------------------------------------------------------------ reading


@pytest.mark.parametrize("who,expected", [
    (None, {"nordsense", "medtrace"}),
    ("nordsense", {"nordsense", "medtrace"}),
    ("greenloop", {"nordsense", "medtrace", "greenloop"}),
    ("admin", {"nordsense", "medtrace", "greenloop"}),
])
def test_company_list_respects_visibility(client, as_, who, expected):
    r = client.get("/companies", headers=as_(who))
    assert r.status_code == 200 and ids(r) == expected
    assert all(c["is_simulated"] for c in r.json())


@pytest.mark.parametrize("who,status", [(None, 404), ("nordsense", 404), ("greenloop", 200), ("admin", 200)])
def test_private_profile_hidden_as_404(client, as_, who, status):
    assert client.get("/companies/greenloop/profile", headers=as_(who)).status_code == status
    assert client.get("/companies/greenloop/recommendations", headers=as_(who)).status_code == status


def test_published_profile_is_public_with_labels(client):
    p = client.get("/companies/nordsense/profile").json()
    assert p["visibility"] == "published" and p["is_simulated"] is True
    assert all(c["kind"] in {"stated", "inferred", "user_confirmed"} for c in p["claims"])
    assert all(c["evidence_url"] for c in p["claims"] if c["kind"] != "user_confirmed")


def test_unknown_company_is_404(client, as_):
    assert client.get("/companies/nope/profile", headers=as_("admin")).status_code == 404


def test_recommendations_best_first_with_caveat(client):
    recs = client.get("/companies/medtrace/recommendations").json()
    assert recs and [r["score"] for r in recs] == sorted((r["score"] for r in recs), reverse=True)
    assert all("eligibility not confirmed" in r["caveats"].lower() for r in recs)


def test_invalid_token_counts_as_visitor_on_public_reads(client):
    r = client.get("/companies", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 200 and ids(r) == {"nordsense", "medtrace"}


def test_opportunities_public_and_labelled(client):
    opps = client.get("/opportunities").json()
    assert len(opps) == 6 and all(o["is_simulated"] for o in opps)
    assert all(o["url"].startswith("http") for o in opps)


# ------------------------------------------------------- claim edits


@pytest.mark.parametrize("who,status", [(None, 401), ("medtrace", 403), ("greenloop", 403), ("nordsense", 200), ("admin", 200)])
def test_edit_claim_permissions(client, as_, who, status):
    r = client.patch("/companies/nordsense/claims/tech-1", json={"value": "wireless vibration sensors"}, headers=as_(who))
    assert r.status_code == status
    if status == 200:
        c = r.json()
        assert c["kind"] == "user_confirmed" and c["confidence"] == 1.0
        assert c["evidence_url"] is None and c["snippet"] is None


def test_edit_claim_403_does_not_reveal_missing_company(client, as_):
    r = client.patch("/companies/does-not-exist/claims/x", json={"value": "v"}, headers=as_("nordsense"))
    assert r.status_code == 403


def test_edit_unknown_claim_is_404(client, as_):
    r = client.patch("/companies/nordsense/claims/nope", json={"value": "v"}, headers=as_("nordsense"))
    assert r.status_code == 404


@pytest.mark.parametrize("body", [{"value": ""}, {"value": "x", "kind": "stated"}, {"value": "x", "company_id": "medtrace"}, {}])
def test_edit_claim_rejects_bad_bodies(client, as_, body):
    assert client.patch("/companies/nordsense/claims/tech-1", json=body, headers=as_("nordsense")).status_code == 422


@pytest.mark.parametrize("who,status", [(None, 401), ("medtrace", 403), ("nordsense", 201), ("admin", 201)])
def test_add_claim_permissions(client, as_, who, status):
    r = client.post("/companies/nordsense/claims",
                    json={"field": "development_priorities", "value": "testing is a priority now"}, headers=as_(who))
    assert r.status_code == status
    if status == 201:
        assert r.json()["kind"] == "user_confirmed" and r.json()["id"].startswith("user-")


def test_add_claim_clears_missing_field(client, as_):
    client.post("/companies/nordsense/claims", json={"field": "collaborations", "value": "pilot with a sawmill"},
                headers=as_("nordsense"))
    p = client.get("/companies/nordsense/profile").json()
    assert "collaborations" not in p["missing_fields"]


@pytest.mark.parametrize("body", [{"field": "ceo_salary", "value": "x"}, {"field": "topics", "value": "x", "company_id": "medtrace"}])
def test_add_claim_rejects_bad_bodies(client, as_, body):
    assert client.post("/companies/nordsense/claims", json=body, headers=as_("nordsense")).status_code == 422


# ------------------------------------------------------- re-ranking


def test_new_priority_changes_ranking(client, as_, db_url):
    """Demo step 2: a user_confirmed priority visibly affects the ranking."""
    from agents.matcher import match

    conn = database.connect(db_url)
    before = {r.opportunity_id: r.score for r in match(database.get_profile(conn, "nordsense"),
                                                       database.list_opportunities(conn))}
    r = client.post("/companies/nordsense/claims",
                    json={"field": "development_priorities", "value": "testing and validation is a priority now"},
                    headers=as_("nordsense"))
    assert r.status_code == 201
    after = {x["opportunity_id"]: x for x in client.get("/companies/nordsense/recommendations").json()}
    assert "sim-testbed-lab" in after
    assert after["sim-testbed-lab"]["score"] > before.get("sim-testbed-lab", 0.0)
    assert r.json()["id"] in after["sim-testbed-lab"]["matched_claims"]


def test_matcher_failure_keeps_edit_and_old_ranking(client, as_, monkeypatch):
    import agents.matcher

    old = client.get("/companies/nordsense/recommendations").json()

    def boom(*_a, **_k):
        raise RuntimeError("matcher down")

    monkeypatch.setattr(agents.matcher, "match", boom)
    r = client.patch("/companies/nordsense/claims/tech-1", json={"value": "edited"}, headers=as_("nordsense"))
    assert r.status_code == 200
    assert client.get("/companies/nordsense/recommendations").json() == old


# ------------------------------------------------------- visibility


@pytest.mark.parametrize("who,status", [(None, 401), ("nordsense", 403), ("greenloop", 200), ("admin", 200)])
def test_publish_permissions(client, as_, who, status):
    r = client.patch("/companies/greenloop/visibility", json={"visibility": "published"}, headers=as_(who))
    assert r.status_code == status
    if status == 200:
        assert r.json()["visibility"] == "published"
        assert client.get("/companies/greenloop/profile").status_code == 200  # now public


def test_unpublish_hides_again(client, as_):
    client.patch("/companies/nordsense/visibility", json={"visibility": "private"}, headers=as_("nordsense"))
    assert client.get("/companies/nordsense/profile").status_code == 404


def test_visibility_rejects_bad_value(client, as_):
    r = client.patch("/companies/nordsense/visibility", json={"visibility": "secret"}, headers=as_("nordsense"))
    assert r.status_code == 422


# ------------------------------------------------------------ feedback


@pytest.mark.parametrize("who,status", [(None, 401), ("admin", 403), ("nordsense", 204)])
def test_feedback_permissions(client, as_, db_url, who, status):
    r = client.post("/feedback", json={"opportunity_id": "sim-testbed-lab", "verdict": "relevant"}, headers=as_(who))
    assert r.status_code == status
    if status == 204:
        row = database.connect(db_url).execute("SELECT company_id, verdict FROM feedback").fetchone()
        assert tuple(row) == ("nordsense", "relevant")


def test_feedback_company_comes_from_session_not_body(client, as_):
    r = client.post("/feedback", json={"opportunity_id": "sim-testbed-lab", "verdict": "save", "company_id": "medtrace"},
                    headers=as_("nordsense"))
    assert r.status_code == 422


@pytest.mark.parametrize("body,status", [
    ({"opportunity_id": "no-such-opp", "verdict": "save"}, 404),
    ({"opportunity_id": "sim-testbed-lab", "verdict": "love it"}, 422),
])
def test_feedback_bad_input(client, as_, body, status):
    assert client.post("/feedback", json=body, headers=as_("nordsense")).status_code == status


# ---------------------------------------------------------------- CORS


def test_ui_origin_parsing(monkeypatch):
    from api.main import ui_origins

    monkeypatch.setenv("UI_ORIGIN", " http://localhost:8080/ , https://x.lovable.app ")
    assert ui_origins() == ["http://localhost:8080", "https://x.lovable.app"]
    monkeypatch.setenv("UI_ORIGIN", "")
    assert ui_origins() == []


def test_cors_allows_only_ui_origin(db_url, monkeypatch):
    import api.main

    monkeypatch.setenv("UI_ORIGIN", "http://localhost:8080")
    module = importlib.reload(api.main)
    try:
        with TestClient(module.app) as c:
            pre = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}
            ok = c.options("/auth/me", headers={"Origin": "http://localhost:8080", **pre})
            bad = c.options("/auth/me", headers={"Origin": "https://evil.example.com", **pre})
        assert ok.headers.get("access-control-allow-origin") == "http://localhost:8080"
        assert "authorization" in ok.headers.get("access-control-allow-headers", "").lower()
        assert "access-control-allow-origin" not in bad.headers
    finally:
        monkeypatch.delenv("UI_ORIGIN")
        importlib.reload(api.main)
