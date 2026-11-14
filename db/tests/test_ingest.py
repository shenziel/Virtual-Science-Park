"""db.ingest with fake agents: no network, no API keys."""

import json
from datetime import date
from pathlib import Path

import pytest

from contracts.models import Claim, Opportunity, Profile, Recommendation
from db import ingest
from fixtures.loader import MOCK, load_seed

TODAY = date(2026, 11, 14)
COMPANIES = [
    {"company_id": "alpha", "name": "Alpha AB", "website": "https://alpha.example.com"},
    {"company_id": "beta", "name": "Beta AB", "website": "https://beta.example.com"},
]
ALL_FIELDS = ["what_it_does", "products_services", "technologies", "expertise", "application_areas",
              "markets", "industries", "customer_groups", "geographic_focus", "development_priorities",
              "projects", "collaborations", "topics"]


def fake_profile(company, existing, html):
    cid = company["company_id"]
    claim = Claim(id="tech-1", field="technologies", value=f"{cid} sensors" + (" (snapshot)" if html else ""),
                  kind="stated", evidence_url=company["website"], snippet="We build sensors.",
                  retrieved_at=TODAY, confidence=0.9, cached_snapshot=html is not None)
    return Profile(company_id=cid, name=company["name"], website=company["website"],
                   updated_at="2026-11-14T10:00:00Z", claims=[claim],
                   missing_fields=[f for f in ALL_FIELDS if f != "technologies"])


def fake_fetch():
    return [Opportunity(id="call-1", type="funding", title="Sensor call", url="https://funding.example.com/1",
                        source="Test", deadline=date(2027, 1, 1), topics=["sensors"], retrieved_at=TODAY)]


def fake_match(profile, opps):
    return [Recommendation(company_id=profile.company_id, opportunity_id=o.id, score=0.5,
                           why="Matches your sensors (tech-1).", matched_claims=["tech-1"],
                           caveats="Potential match, eligibility not confirmed.") for o in opps]


@pytest.fixture
def out(tmp_path):
    d = tmp_path / "seed"
    (d / "profiles").mkdir(parents=True)
    (d / "companies.json").write_text(json.dumps(COMPANIES))
    (d / "users.json").write_text(json.dumps([
        {"id": "u-admin", "email": "admin@bsp.example.com", "role": "admin", "company_id": None, "password": "demo-admin-2026"}]))
    return d


def run(out, **kw):
    kw.setdefault("profile_fn", fake_profile)
    kw.setdefault("fetch_fn", fake_fetch)
    kw.setdefault("match_fn", fake_match)
    return ingest.run_ingest(out, **kw)


def test_full_run_writes_valid_seed_folder(out):
    report = run(out)
    assert report.profiled == ["alpha", "beta"] and not report.failed
    assert sorted(report.written) == ["opportunities.json", "profiles/alpha.json", "profiles/beta.json", "recommendations.json"]
    seed = load_seed(out)  # validates every file against contracts.models
    assert set(seed.profiles) == {"alpha", "beta"}
    assert len(seed.opportunities) == 1 and len(seed.recommendations) == 2


def test_dry_run_writes_nothing(out):
    report = run(out, dry_run=True)
    assert report.profiled == ["alpha", "beta"] and report.written == []
    assert not (out / "opportunities.json").exists() and not list((out / "profiles").iterdir())


def test_failed_company_keeps_previous_profile_and_others_continue(out):
    run(out)
    before = (out / "profiles" / "beta.json").read_text()

    def flaky(company, existing, html):
        if company["company_id"] == "beta":
            raise ConnectionError("site down")
        return fake_profile(company, existing, html)

    report = run(out, profile_fn=flaky)
    assert report.profiled == ["alpha"] and report.reused == ["beta"]
    assert "ConnectionError" in report.failed["beta"]
    assert (out / "profiles" / "beta.json").read_text() == before
    assert {r.company_id for r in load_seed(out).recommendations} == {"alpha", "beta"}


def test_only_profiles_selected_companies(out):
    run(out)
    report = run(out, only={"alpha"})
    assert report.profiled == ["alpha"] and report.reused == ["beta"]


def test_html_snapshot_is_passed_to_profiler(out, tmp_path):
    page = tmp_path / "beta.html"
    page.write_text("<html>Beta</html>")
    run(out, html={"beta": page})
    beta = load_seed(out).profiles["beta"]
    assert beta.claims[0].cached_snapshot is True and "(snapshot)" in beta.claims[0].value


def test_existing_profile_is_passed_to_profiler(out):
    run(out)
    seen = {}

    def spy(company, existing, html):
        seen[company["company_id"]] = existing
        return fake_profile(company, existing, html)

    run(out, profile_fn=spy)
    assert seen["alpha"] is not None and seen["alpha"].company_id == "alpha"


def test_skip_profiler_reuses_saved_profiles(out):
    run(out)

    def must_not_run(*_a):
        raise AssertionError("profiler should not run")

    report = run(out, skip_profiler=True, profile_fn=must_not_run)
    assert report.reused == ["alpha", "beta"] and report.profiled == []


def test_skip_monitors_reuses_saved_opportunities(out):
    run(out)

    def must_not_run():
        raise AssertionError("monitors should not run")

    report = run(out, skip_monitors=True, fetch_fn=must_not_run)
    assert report.opportunities == 1 and "opportunities.json" not in report.written


def test_bad_matcher_output_aborts_without_writing(out):
    def bad_match(profile, opps):
        r = fake_match(profile, opps)[0]
        return [r.model_copy(update={"matched_claims": ["does-not-exist"]})]

    with pytest.raises(ingest.IngestError, match="unknown claims"):
        run(out, match_fn=bad_match)
    assert not (out / "recommendations.json").exists() and not list((out / "profiles").iterdir())


def test_profiler_returning_wrong_company_is_a_failure(out):
    def wrong(company, existing, html):
        return fake_profile({**company, "company_id": "other"}, existing, html)

    report = run(out, only={"alpha"}, profile_fn=wrong)
    assert "alpha" in report.failed and report.written == ["opportunities.json", "recommendations.json"]


@pytest.mark.parametrize("kw,msg", [({"only": {"nope"}}, "--only"), ({"html": {"nope": Path("x.html")}}, "--html")])
def test_unknown_company_names_rejected(out, kw, msg):
    with pytest.raises(ingest.IngestError, match=msg):
        run(out, **kw)


def test_refuses_to_write_into_mock(tmp_path):
    if not MOCK.exists():
        pytest.skip("no mock folder")
    with pytest.raises(ingest.IngestError, match="mock"):
        ingest.run_ingest(MOCK, profile_fn=fake_profile, fetch_fn=fake_fetch, match_fn=fake_match)


def test_companies_file_must_have_required_keys(out):
    (out / "companies.json").write_text(json.dumps([{"company_id": "alpha"}]))
    with pytest.raises(ingest.IngestError, match="missing"):
        run(out)


def test_no_temp_files_left_behind(out):
    run(out)
    assert not [p for p in out.rglob(".*.tmp")]


def test_cli_html_argument_parsing():
    assert ingest._parse_html(["cmarine=pages/c.html"]) == {"cmarine": Path("pages/c.html")}
    with pytest.raises(SystemExit):
        ingest._parse_html(["no-equals-sign"])


def test_real_companies_file_is_loadable():
    from fixtures.loader import FIXTURES

    ids = [c["company_id"] for c in ingest.load_companies(FIXTURES / "companies.json")]
    assert ids == ["softhouse", "cleura", "cmarine"]


def test_default_fetch_applies_refresh_rules(monkeypatch):
    """Ingest uses the same monitor rules as the API refresh: live Vinnova only, labels kept."""
    import agents.monitors

    snapshot_vinnova = Opportunity(id="vinnova-snap", type="funding", title="Old call", url="https://www.vinnova.se/x",
                                   source="Vinnova", deadline=date(2027, 1, 1), retrieved_at=TODAY, cached_snapshot=True)
    cached_event = Opportunity(id="bsp-1", type="event", title="Event", url="https://bsp.example.com/1",
                               source="Blue Science Park", event_date=date(2026, 12, 3), retrieved_at=TODAY,
                               cached_snapshot=True)
    monkeypatch.setattr(agents.monitors, "fetch_all_opportunities", lambda: [snapshot_vinnova, cached_event])
    opps = ingest.default_fetch_fn()()
    assert [o.id for o in opps] == ["bsp-1"] and opps[0].cached_snapshot is True


def test_default_fetch_survives_monitor_failure(monkeypatch):
    import agents.monitors

    def broken():
        raise ConnectionError("down")

    monkeypatch.setattr(agents.monitors, "fetch_all_opportunities", broken)
    assert ingest.default_fetch_fn()() == []
