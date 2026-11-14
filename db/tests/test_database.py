import sqlite3

import pytest
from argon2 import PasswordHasher

from contracts.models import ClaimKind, Profile, Visibility
from db import database as db
from db.seed import seed_db
from fixtures.loader import MOCK, load_seed

pytestmark = pytest.mark.skipif(not MOCK.exists(), reason="tests run against fixtures/mock")


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    seed_db(c, MOCK)
    yield c
    c.close()


def test_db_path_parsing():
    assert db.db_path("sqlite:////data/vsp.db") == "/data/vsp.db"
    assert db.db_path("sqlite:///vsp.db") == "vsp.db"
    with pytest.raises(ValueError):
        db.db_path("postgres://x")


def test_seed_counts_and_roundtrip(conn):
    seed = load_seed(MOCK)
    assert {c["company_id"] for c in db.list_companies(conn)} == set(seed.profiles)
    for cid, original in seed.profiles.items():
        stored = db.get_profile(conn, cid)
        assert isinstance(stored, Profile)
        assert [c.model_dump() for c in stored.claims] == [c.model_dump() for c in original.claims]
        assert stored.missing_fields == original.missing_fields
        assert stored.visibility == original.visibility
    assert len(db.list_opportunities(conn)) == len(seed.opportunities)


def test_seed_is_idempotent(conn):
    before = db.get_profile(conn, "nordsense").claims
    seed_db(conn, MOCK)
    assert db.get_profile(conn, "nordsense").claims == before


def test_unknown_company_raises(conn):
    with pytest.raises(db.NotFound):
        db.get_profile(conn, "nope")
    with pytest.raises(db.NotFound):
        db.set_visibility(conn, "nope", Visibility.published)


# --- user edits


def test_edit_makes_claim_user_confirmed(conn):
    c = db.update_claim_value(conn, "nordsense", "tech-1", "wireless vibration sensors")
    assert c.kind == ClaimKind.user_confirmed and c.confidence == 1.0 and c.evidence_url is None
    stored = {x.id: x for x in db.get_profile(conn, "nordsense").claims}["tech-1"]
    assert stored == c


def test_edit_unknown_claim_raises(conn):
    with pytest.raises(db.NotFound):
        db.update_claim_value(conn, "nordsense", "nope", "x")


def test_add_claim_gets_new_id_and_clears_missing_field(conn):
    assert "collaborations" in [f.value for f in db.get_profile(conn, "nordsense").missing_fields]
    a = db.add_claim(conn, "nordsense", "collaborations", "pilot with a sawmill")
    b = db.add_claim(conn, "nordsense", "development_priorities", "testing is a priority now")
    assert (a.id, b.id) == ("user-1", "user-2")
    p = db.get_profile(conn, "nordsense")
    assert "collaborations" not in [f.value for f in p.missing_fields]
    assert p.claims[-1].value == "testing is a priority now"


def test_agent_rerun_never_overwrites_user_confirmed(conn):
    db.update_claim_value(conn, "nordsense", "tech-1", "edited by user")
    db.add_claim(conn, "nordsense", "development_priorities", "testing is a priority now")
    seed_db(conn, MOCK)  # simulates the profiler running again
    claims = {c.id: c for c in db.get_profile(conn, "nordsense").claims}
    assert claims["tech-1"].value == "edited by user"
    assert claims["tech-1"].kind == ClaimKind.user_confirmed
    assert claims["user-1"].value == "testing is a priority now"


def test_agent_rerun_keeps_visibility_choice(conn):
    db.set_visibility(conn, "greenloop", Visibility.published)
    seed_db(conn, MOCK)
    assert db.get_profile(conn, "greenloop").visibility == Visibility.published


def test_new_agent_profile_starts_private(conn):
    p = load_seed(MOCK).profiles["medtrace"].model_copy(update={"company_id": "newco", "visibility": Visibility.private})
    assert db.upsert_profile(conn, p).visibility == Visibility.private


# --- recommendations, feedback


def test_recommendations_best_first(conn):
    scores = [r.score for r in db.list_recommendations(conn, "medtrace")]
    assert scores == sorted(scores, reverse=True) and scores


def test_replace_recommendations_rejects_other_company(conn):
    rec = db.list_recommendations(conn, "medtrace")[0]
    with pytest.raises(ValueError):
        db.replace_recommendations(conn, "nordsense", [rec])


def test_feedback_saved_and_validated(conn):
    db.add_feedback(conn, "nordsense", "sim-testbed-lab", "relevant")
    assert conn.execute("SELECT verdict FROM feedback").fetchone()[0] == "relevant"
    with pytest.raises(ValueError):
        db.add_feedback(conn, "nordsense", "sim-testbed-lab", "love it")


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_feedback(conn, "nordsense", "no-such-opportunity", "save")


# --- users


def test_passwords_are_hashed(conn):
    user, h = db.get_user_credentials(conn, "demo@nordsense.example.com")
    assert user.company_id == "nordsense"
    assert "demo-nordsense-2026" not in h and h.startswith("$argon2")
    assert PasswordHasher().verify(h, "demo-nordsense-2026")


def test_email_lookup_is_case_insensitive(conn):
    assert db.get_user_credentials(conn, "DEMO@NordSense.example.com") is not None
    assert db.get_user_credentials(conn, "nobody@example.com") is None


def test_get_user_has_no_hash(conn):
    assert "password_hash" not in db.get_user(conn, "u-admin").model_dump()
