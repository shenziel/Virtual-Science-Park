"""db.refresh: monitors -> validated opportunities in SQLite, with fake monitors (no network)."""

import logging
from datetime import date

import pytest

from contracts.models import Opportunity
from db import database
from db.refresh import collect_opportunities, refresh_opportunities
from db.seed import seed_db
from fixtures.loader import MOCK

pytestmark = pytest.mark.skipif(not MOCK.exists(), reason="seeds companies from fixtures/mock")

TODAY = date(2026, 11, 14)


def opp(id_, source="Vinnova", **kw):
    base = dict(id=id_, type="funding" if source == "Vinnova" else "event", title=f"Title {id_}",
                url=f"https://{source.lower().replace(' ', '')}.example.com/{id_}", source=source,
                deadline=date(2027, 2, 1), topics=["testing", "sensors"], retrieved_at=TODAY)
    return Opportunity(**{**base, **kw})


LIVE_VINNOVA = opp("vinnova-live-1")
BSP_CACHED = opp("bsp-cached-1", source="Blue Science Park", cached_snapshot=True)
BSP_SIMULATED = opp("bsp-sim-1", source="Blue Science Park", is_simulated=True)


@pytest.fixture
def conn():
    c = database.connect(":memory:")
    seed_db(c, MOCK)  # companies + the six simulated mock opportunities
    yield c
    c.close()


def stored(conn):
    return {o.id: o for o in database.list_opportunities(conn)}


# ------------------------------------------------------- collect


def test_labels_are_preserved(conn):
    refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA, BSP_CACHED, BSP_SIMULATED])
    s = stored(conn)
    assert s["bsp-cached-1"].cached_snapshot is True and s["bsp-cached-1"].is_simulated is False
    assert s["bsp-sim-1"].is_simulated is True
    assert s["vinnova-live-1"].cached_snapshot is False and s["vinnova-live-1"].is_simulated is False


@pytest.mark.parametrize("not_live", [
    opp("vinnova-snap", cached_snapshot=True),
    opp("vinnova-sim", is_simulated=True),
])
def test_vinnova_must_be_live(conn, not_live):
    result = refresh_opportunities(conn, fetch_fn=lambda: [not_live, BSP_CACHED])
    assert not_live.id not in stored(conn)
    assert result.dropped_vinnova_not_live == 1 and result.vinnova == 0


def test_no_live_vinnova_stays_empty_and_is_logged(conn, caplog):
    with caplog.at_level(logging.WARNING, logger="db.refresh"):
        result = refresh_opportunities(conn, fetch_fn=lambda: [BSP_CACHED])
    assert result.vinnova == 0
    assert not [o for o in stored(conn).values() if o.source == "Vinnova"]
    assert "live Vinnova fetch returned no calls" in caplog.text


def test_monitor_failure_gives_empty_result_not_mock(conn, caplog):
    assert len(stored(conn)) == 6  # mock opportunities from the seed

    def broken():
        raise ConnectionError("vinnova down")

    with caplog.at_level(logging.ERROR, logger="db.refresh"):
        result = refresh_opportunities(conn, fetch_fn=broken)
    assert result.failed is True and result.stored == 0
    assert stored(conn) == {}  # no fallback to the mock fixtures
    assert database.list_recommendations(conn, "nordsense") == []
    assert "monitor fetch failed" in caplog.text


def test_seeded_mock_opportunities_are_replaced(conn):
    result = refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA])
    assert set(stored(conn)) == {"vinnova-live-1"}
    assert result.removed == 6


def test_invalid_items_dropped_others_kept(conn):
    bad_no_date = {"id": "no-date", "type": "event", "title": "x", "url": "https://x.example.com",
                   "source": "Blue Science Park", "retrieved_at": "2026-11-14"}
    bad_no_url = {"id": "no-url", "type": "funding", "title": "x", "url": "", "source": "Vinnova",
                  "deadline": "2027-01-01", "retrieved_at": "2026-11-14"}
    result = refresh_opportunities(conn, fetch_fn=lambda: [bad_no_date, bad_no_url, LIVE_VINNOVA])
    assert set(stored(conn)) == {"vinnova-live-1"}
    assert result.dropped_invalid == 2 and result.fetched == 3


def test_duplicates_dropped(conn):
    result = refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA, LIVE_VINNOVA])
    assert result.dropped_duplicate == 1 and result.stored == 1


def test_collect_accepts_dicts_and_models():
    opps, result = collect_opportunities(lambda: [LIVE_VINNOVA.model_dump(mode="json"), BSP_CACHED])
    assert [o.id for o in opps] == ["vinnova-live-1", "bsp-cached-1"] and not result.failed


# ---------------------------------------------------- re-ranking


def test_every_company_is_reranked_against_new_set(conn):
    result = refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA, BSP_CACHED])
    assert sorted(result.rematched) == ["greenloop", "medtrace", "nordsense"]
    current = set(stored(conn))
    for cid in result.rematched:
        assert {r.opportunity_id for r in database.list_recommendations(conn, cid)} <= current


def test_refresh_is_idempotent(conn):
    refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA, BSP_CACHED])
    first = stored(conn)
    result = refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA, BSP_CACHED])
    assert stored(conn) == first and result.removed == 0


def test_rematch_failure_for_one_company_does_not_stop_refresh(conn):
    from agents.matcher import match

    def picky(profile, opps):
        if profile.company_id == "greenloop":
            raise RuntimeError("matcher broke")
        return match(profile, opps)

    result = refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA], match_fn=picky)
    assert result.rematch_failed == ["greenloop"]
    assert sorted(result.rematched) == ["medtrace", "nordsense"]
    assert set(stored(conn)) == {"vinnova-live-1"}


def test_stale_opportunity_removed_with_its_feedback(conn):
    refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA, BSP_CACHED])
    database.add_feedback(conn, "nordsense", "bsp-cached-1", "save")
    refresh_opportunities(conn, fetch_fn=lambda: [LIVE_VINNOVA])  # BSP item gone at the source
    assert "bsp-cached-1" not in stored(conn)
    assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
