import pytest

from contracts.models import Claim, ClaimKind, Profile, ProfileField, Visibility

from agents.profiler.extract import ExtractionError
from agents.profiler.fetch import CachedFetcher
from agents.profiler.profiler import ProfilerAgent
from agents.profiler.tests.conftest import PAGE_HTML, PAGE_URL, TODAY, FakeLLM, FakeTransport

COMPANY_ID = "nordsense"
NAME = "NordSense AB"


def make_agent(tmp_path, llm=None, transport=None, **kwargs) -> ProfilerAgent:
    fetcher = CachedFetcher(
        cache_dir=tmp_path / "pages",
        transport=transport or FakeTransport(),
        min_interval=0.0,
        today=lambda: TODAY,
    )
    return ProfilerAgent(
        llm=llm,
        fetcher=fetcher,
        cache_dir=tmp_path / "profiles",
        **kwargs,
    )


def test_profile_validates_against_the_contract(tmp_path):
    profile = make_agent(tmp_path).profile_company(COMPANY_ID, NAME, PAGE_URL)

    assert isinstance(profile, Profile)
    assert profile.company_id == COMPANY_ID
    assert profile.name == NAME
    assert profile.visibility is Visibility.private  # agent output starts private
    assert profile.is_simulated is False
    assert profile.claims
    for claim in profile.claims:
        assert str(claim.evidence_url) == PAGE_URL
        assert claim.kind in {ClaimKind.stated, ClaimKind.inferred}
        if claim.kind is ClaimKind.stated:
            assert claim.snippet


def test_every_profile_area_is_covered_or_reported_missing(tmp_path):
    profile = make_agent(tmp_path).profile_company(COMPANY_ID, NAME, PAGE_URL)

    covered = {c.field for c in profile.claims}
    missing = set(profile.missing_fields)
    assert covered.isdisjoint(missing)
    assert covered | missing == set(ProfileField)


def test_live_claims_are_not_labelled_cached(tmp_path):
    profile = make_agent(tmp_path).profile_company(COMPANY_ID, NAME, PAGE_URL)
    assert all(c.cached_snapshot is False for c in profile.claims)


def test_claims_from_supplied_html_are_labelled_cached(tmp_path):
    profile = make_agent(tmp_path).profile_company(
        COMPANY_ID, NAME, PAGE_URL, html_content=PAGE_HTML
    )
    assert profile.claims
    assert all(c.cached_snapshot is True for c in profile.claims)


def test_snapshot_file_is_labelled_cached(tmp_path):
    snapshot = tmp_path / "nordsense.html"
    snapshot.write_text(PAGE_HTML, encoding="utf-8")
    profile = make_agent(tmp_path).profile_from_snapshot(COMPANY_ID, NAME, PAGE_URL, snapshot)
    assert profile.claims
    assert all(c.cached_snapshot is True for c in profile.claims)


def test_user_confirmed_claims_survive_a_rerun_and_are_never_overwritten(tmp_path):
    agent = make_agent(tmp_path)
    first = agent.profile_company(COMPANY_ID, NAME, PAGE_URL)

    confirmed = Claim(
        id="geo-1",
        field=ProfileField.geographic_focus,
        value="Karlskrona, Sweden only",
        kind=ClaimKind.user_confirmed,
        evidence_url=None,
        snippet=None,
        retrieved_at=TODAY,
        confidence=1.0,
    )
    # The company user edited the existing claim, so the API marked it confirmed.
    existing = first.model_copy(
        update={"claims": [c for c in first.claims if c.id != "geo-1"] + [confirmed]}
    )

    second = agent.profile_company(COMPANY_ID, NAME, PAGE_URL, existing=existing)

    kept = [c for c in second.claims if c.id == "geo-1"]
    assert len(kept) == 1
    assert kept[0].kind is ClaimKind.user_confirmed
    assert kept[0].value == "Karlskrona, Sweden only"
    assert ProfileField.geographic_focus not in second.missing_fields
    assert len(second.claims) > 1  # the rest of the profile was refreshed


def test_published_visibility_is_not_reset_by_a_rerun(tmp_path):
    agent = make_agent(tmp_path)
    first = agent.profile_company(COMPANY_ID, NAME, PAGE_URL)
    published = first.model_copy(update={"visibility": Visibility.published})

    second = agent.profile_company(COMPANY_ID, NAME, PAGE_URL, existing=published)
    assert second.visibility is Visibility.published


def test_save_and_load_roundtrip(tmp_path):
    agent = make_agent(tmp_path)
    profile = agent.profile_company(COMPANY_ID, NAME, PAGE_URL)

    path = agent.save(profile)
    assert path.exists()

    loaded = agent.load(COMPANY_ID)
    assert loaded is not None
    assert loaded.company_id == profile.company_id
    assert loaded.claims == profile.claims
    assert loaded.missing_fields == profile.missing_fields


def test_load_returns_none_for_an_unknown_company(tmp_path):
    assert make_agent(tmp_path).load("nobody") is None


@pytest.mark.parametrize(
    ("company_id", "website"),
    [("Not A Slug", PAGE_URL), ("nordsense", "ftp://nordsense.example")],
)
def test_bad_inputs_are_rejected(tmp_path, company_id, website):
    with pytest.raises(ValueError):
        make_agent(tmp_path).profile_company(company_id, NAME, website)


def test_llm_failure_falls_back_to_the_deterministic_extractor(tmp_path):
    llm = FakeLLM("not json", "still not json")
    profile = make_agent(tmp_path, llm=llm).profile_company(COMPANY_ID, NAME, PAGE_URL)

    assert profile.claims  # the demo keeps working
    assert all(c.kind is not ClaimKind.user_confirmed for c in profile.claims)


def test_llm_failure_raises_when_the_fallback_is_disabled(tmp_path):
    llm = FakeLLM("not json", "still not json")
    agent = make_agent(tmp_path, llm=llm, fallback_on_llm_error=False)
    with pytest.raises(ExtractionError):
        agent.profile_company(COMPANY_ID, NAME, PAGE_URL)
