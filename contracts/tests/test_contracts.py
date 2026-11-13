from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from contracts.export_schemas import HERE, render
from contracts.models import (
    SCHEMAS,
    Claim,
    ClaimCreate,
    Opportunity,
    Profile,
    Recommendation,
    User,
)

TODAY = date(2026, 11, 13)


def claim(**kw):
    base = dict(
        id="tech-1",
        field="technologies",
        value="industrial IoT sensors",
        kind="stated",
        evidence_url="https://example.com/about",
        snippet="We build industrial IoT sensors.",
        retrieved_at=TODAY,
        confidence=0.9,
    )
    return Claim(**{**base, **kw})


@pytest.mark.parametrize("name", SCHEMAS)
def test_json_schema_files_match_models(name):
    path = HERE / f"{name}.json"
    assert path.read_text(encoding="utf-8") == render(name), "run: python -m contracts.export_schemas"


# --- claims


def test_stated_claim_ok():
    assert claim().kind.value == "stated"


def test_stated_claim_needs_snippet():
    with pytest.raises(ValidationError, match="snippet"):
        claim(snippet=None)


@pytest.mark.parametrize("kind", ["stated", "inferred"])
def test_agent_claims_need_evidence_url(kind):
    with pytest.raises(ValidationError, match="evidence_url"):
        claim(kind=kind, evidence_url=None)


def test_user_confirmed_claim_needs_no_url():
    assert claim(kind="user_confirmed", evidence_url=None, snippet=None).evidence_url is None


@pytest.mark.parametrize("bad", [{"confidence": 1.5}, {"value": "  "}, {"field": "ceo_salary"}, {"extra": 1}])
def test_claim_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        claim(**bad)


def test_evidence_url_must_be_http():
    with pytest.raises(ValidationError):
        claim(evidence_url="javascript:alert(1)")


# --- profile


def profile(**kw):
    base = dict(
        company_id="acme",
        name="Acme AB",
        website="https://example.com",
        updated_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        claims=[claim()],
    )
    return Profile(**{**base, **kw})


def test_profile_defaults_to_private():
    assert profile().visibility.value == "private"


def test_profile_rejects_duplicate_claim_ids():
    with pytest.raises(ValidationError, match="duplicate"):
        profile(claims=[claim(), claim()])


def test_profile_field_cannot_be_both_covered_and_missing():
    with pytest.raises(ValidationError, match="covered and missing"):
        profile(missing_fields=["technologies"])


# --- opportunity


def opportunity(**kw):
    base = dict(
        id="vinnova-1",
        type="funding",
        title="Innovation call",
        url="https://www.vinnova.se/e/x",
        source="Vinnova",
        deadline=TODAY,
        retrieved_at=TODAY,
    )
    return Opportunity(**{**base, **kw})


def test_opportunity_ok():
    assert opportunity().is_simulated is False


def test_opportunity_needs_a_date():
    with pytest.raises(ValidationError, match="at least one"):
        opportunity(deadline=None)


def test_opportunity_needs_url():
    with pytest.raises(ValidationError):
        opportunity(url="")


# --- recommendation


def rec(**kw):
    base = dict(
        company_id="acme",
        opportunity_id="vinnova-1",
        score=0.7,
        why="Matches your stated focus on industrial IoT sensors (tech-1).",
        matched_claims=["tech-1"],
        caveats="Potential match, eligibility not confirmed.",
    )
    return Recommendation(**{**base, **kw})


def test_recommendation_ok():
    assert rec().score == 0.7


def test_recommendation_needs_eligibility_caveat():
    with pytest.raises(ValidationError, match="eligibility"):
        rec(caveats="Great fit!")


def test_recommendation_needs_matched_claims():
    with pytest.raises(ValidationError):
        rec(matched_claims=[])


# --- API payloads


def test_claim_create_cannot_set_kind_or_company():
    with pytest.raises(ValidationError):
        ClaimCreate(field="development_priorities", value="testing", kind="stated")
    with pytest.raises(ValidationError):
        ClaimCreate(field="development_priorities", value="testing", company_id="other")


def test_user_role_company_link():
    User(id="u1", email="a@example.com", role="company", company_id="acme")
    User(id="u2", email="b@example.com", role="admin")
    with pytest.raises(ValidationError):
        User(id="u3", email="c@example.com", role="company")
    with pytest.raises(ValidationError):
        User(id="u4", email="d@example.com", role="admin", company_id="acme")
