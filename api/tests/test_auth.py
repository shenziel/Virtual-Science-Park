from datetime import datetime, timedelta, timezone

import pytest

from api.tests.conftest import auth, login
from db import database
from fixtures.loader import MOCK

pytestmark = pytest.mark.skipif(not MOCK.exists(), reason="auth tests use the mock demo accounts")


# --- login


def test_login_returns_bearer_token_and_user(client):
    body = login(client)
    assert body["token_type"] == "bearer" and len(body["access_token"]) >= 32
    assert body["user"] == {"id": "u-nordsense", "email": "demo@nordsense.example.com",
                            "role": "company", "company_id": "nordsense"}
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(timezone.utc)


def test_login_never_returns_password_or_hash(client):
    text = client.post("/auth/login", json={"email": "admin@bsp.example.com",
                                            "password": "demo-admin-2026"}).text
    assert "demo-admin-2026" not in text and "argon2" not in text and "password" not in text


def test_login_email_is_case_insensitive(client):
    assert login(client, email="DEMO@NordSense.example.com")["user"]["id"] == "u-nordsense"


@pytest.mark.parametrize("email,password", [
    ("demo@nordsense.example.com", "wrong-password"),
    ("nobody@example.com", "demo-nordsense-2026"),
])
def test_bad_login_is_401_with_same_message(client, email, password):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 401
    assert r.json() == {"detail": "Wrong email or password"}
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("body", [
    {"email": "demo@nordsense.example.com"},
    {"email": "", "password": "x"},
    {"email": "demo@nordsense.example.com", "password": "demo-nordsense-2026", "company_id": "medtrace"},
    {"email": "demo@nordsense.example.com", "password": "demo-nordsense-2026", "role": "admin"},
])
def test_login_rejects_malformed_or_extra_fields(client, body):
    assert client.post("/auth/login", json=body).status_code == 422


def test_token_is_stored_hashed(client, db_url):
    token = login(client)["access_token"]
    conn = database.connect(db_url)
    stored = [r[0] for r in conn.execute("SELECT token_hash FROM sessions")]
    assert stored and token not in stored and len(stored[0]) == 64


# --- /auth/me


def test_me_with_token(client):
    token = login(client, "admin@bsp.example.com", "demo-admin-2026")["access_token"]
    r = client.get("/auth/me", headers=auth(token))
    assert r.status_code == 200
    assert r.json() == {"id": "u-admin", "email": "admin@bsp.example.com", "role": "admin", "company_id": None}


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer not-a-real-token"},
    {"Authorization": "Basic dXNlcjpwYXNz"},
    {"Authorization": "Bearer "},
])
def test_me_without_valid_token_is_401(client, headers):
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_expired_token_is_401(client, db_url):
    conn = database.connect(db_url)
    token, _ = database.create_session(conn, "u-nordsense", timedelta(seconds=-1))
    assert client.get("/auth/me", headers=auth(token)).status_code == 401
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0  # cleaned up


def test_each_login_gets_its_own_token(client):
    a, b = login(client)["access_token"], login(client)["access_token"]
    assert a != b
    assert client.get("/auth/me", headers=auth(a)).status_code == 200
    assert client.get("/auth/me", headers=auth(b)).status_code == 200


# --- logout


def test_logout_revokes_only_that_token(client):
    a, b = login(client)["access_token"], login(client)["access_token"]
    assert client.post("/auth/logout", headers=auth(a)).status_code == 204
    assert client.get("/auth/me", headers=auth(a)).status_code == 401
    assert client.get("/auth/me", headers=auth(b)).status_code == 200


def test_logout_without_token_is_401(client):
    assert client.post("/auth/logout").status_code == 401


# --- startup


def test_startup_seeds_empty_database(client, db_url):
    conn = database.connect(db_url)
    assert database.count_users(conn) == 4
    assert {c["company_id"] for c in database.list_companies(conn)} == {"nordsense", "greenloop", "medtrace"}


def test_openapi_documents_bearer_auth(client):
    spec = client.get("/openapi.json").json()
    assert "HTTPBearer" in spec["components"]["securitySchemes"]
    assert "LoginResponse" in spec["components"]["schemas"]
