from datetime import date

import pytest

from agents.profiler.fetch import CachedFetcher, FetchError, RobotsDenied
from agents.profiler.tests.conftest import (
    PAGE_HTML,
    PAGE_URL,
    TODAY,
    FakeClock,
    FakeTransport,
)


def test_fetch_sends_identifying_user_agent(transport, fetcher):
    fetcher.fetch(PAGE_URL)
    assert transport.calls
    for _, user_agent in transport.calls:
        assert "Profiler" in user_agent
        assert "bluesciencepark" in user_agent.lower()  # a contact URL


def test_fetch_caches_and_second_call_does_not_hit_network(transport, fetcher):
    first = fetcher.fetch(PAGE_URL)
    assert first.cached is False
    assert first.html == PAGE_HTML

    second = fetcher.fetch(PAGE_URL)
    assert second.cached is True
    assert second.note == "cached snapshot"
    assert transport.page_calls == [PAGE_URL]  # fetched exactly once


def test_cached_page_keeps_its_original_retrieval_date(tmp_path, transport):
    first = CachedFetcher(
        cache_dir=tmp_path / "pages", transport=transport, min_interval=0.0, today=lambda: TODAY
    )
    assert first.fetch(PAGE_URL).retrieved_at == TODAY

    later = CachedFetcher(
        cache_dir=tmp_path / "pages",
        transport=transport,
        min_interval=0.0,
        today=lambda: date(2027, 1, 1),
    )
    cached = later.fetch(PAGE_URL)
    assert cached.cached is True
    assert cached.retrieved_at == TODAY


def test_robots_disallow_raises_and_never_fetches_the_page(tmp_path):
    transport = FakeTransport(robots="User-agent: *\nDisallow: /\n")
    fetcher = CachedFetcher(cache_dir=tmp_path / "pages", transport=transport, min_interval=0.0)
    with pytest.raises(RobotsDenied):
        fetcher.fetch(PAGE_URL)
    assert transport.page_calls == []


def test_missing_robots_txt_means_allowed(tmp_path):
    transport = FakeTransport(robots=None)
    fetcher = CachedFetcher(cache_dir=tmp_path / "pages", transport=transport, min_interval=0.0)
    assert fetcher.fetch(PAGE_URL).html == PAGE_HTML


def test_requests_to_one_host_are_throttled(tmp_path):
    transport = FakeTransport()
    transport.pages["https://nordsense.example/team"] = PAGE_HTML
    clock = FakeClock()
    fetcher = CachedFetcher(
        cache_dir=tmp_path / "pages",
        transport=transport,
        min_interval=2.0,
        clock=clock,
        sleep=clock.sleep,
    )
    fetcher.fetch(PAGE_URL)
    fetcher.fetch("https://nordsense.example/team")

    assert len(clock.sleeps) == 2
    assert all(sleep >= 1.9 for sleep in clock.sleeps)


def test_fetch_failure_raises_and_writes_no_cache(tmp_path):
    transport = FakeTransport(pages={})  # every page 404s
    fetcher = CachedFetcher(cache_dir=tmp_path / "pages", transport=transport, min_interval=0.0)
    with pytest.raises(FetchError):
        fetcher.fetch(PAGE_URL)
    assert list((tmp_path / "pages").glob("*.html")) == []


def test_load_snapshot_is_labelled_cached(tmp_path):
    snapshot = tmp_path / "nordsense.html"
    snapshot.write_text(PAGE_HTML, encoding="utf-8")
    fetcher = CachedFetcher(
        cache_dir=tmp_path / "pages", transport=FakeTransport(), min_interval=0.0
    )
    page = fetcher.load_snapshot(PAGE_URL, snapshot)
    assert page.cached is True
    assert "cached snapshot" in page.note
    assert page.retrieved_at == date.today()
