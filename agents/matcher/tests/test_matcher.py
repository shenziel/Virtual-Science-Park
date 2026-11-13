"""
Pytest suite for agents/matcher/

Covers:
- Pydantic model validation (contract compliance)
- topic_overlap_score, timeline_score, location_format_score
- match() ranking and user_confirmed boost
- Deterministic `why` generation
- Two companies with different profiles get different rankings (demo requirement)
"""
from __future__ import annotations

import sys
import os
from datetime import date, timedelta

import pytest

# Make the package importable when pytest runs from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from agents.matcher.models import (
    Claim,
    ClaimKind,
    CompanyProfile,
    Opportunity,
    OpportunityFormat,
    OpportunityType,
    Recommendation,
)
from agents.matcher.matcher import (
    _location_format_score,
    _timeline_score,
    _topic_overlap_score,
    _build_why_deterministic,
    match,
)
import agents.matcher.config as config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TODAY = date(2026, 11, 13)


def _make_iot_profile() -> CompanyProfile:
    """Company focused on industrial IoT sensors."""
    return CompanyProfile(
        company_id="company-iot",
        company_name="SensorTech AB",
        claims=[
            Claim(id="c1", field="technologies", value="industrial IoT sensors",
                  kind=ClaimKind.stated, confidence=0.95),
            Claim(id="c2", field="markets", value="manufacturing",
                  kind=ClaimKind.stated, confidence=0.9),
            Claim(id="c3", field="expertise", value="wireless sensor networks",
                  kind=ClaimKind.inferred, confidence=0.8),
            Claim(id="c4", field="priorities", value="IoT platform expansion",
                  kind=ClaimKind.user_confirmed, confidence=1.0),
        ],
    )


def _make_biotech_profile() -> CompanyProfile:
    """Company focused on biotech / life sciences."""
    return CompanyProfile(
        company_id="company-bio",
        company_name="BioMed Innovations",
        claims=[
            Claim(id="b1", field="technologies", value="CRISPR gene editing",
                  kind=ClaimKind.stated, confidence=0.95),
            Claim(id="b2", field="markets", value="pharmaceuticals",
                  kind=ClaimKind.stated, confidence=0.9),
            Claim(id="b3", field="expertise", value="clinical trials",
                  kind=ClaimKind.inferred, confidence=0.75),
        ],
    )


def _make_iot_opportunity(*, days_until_deadline: int = 20) -> Opportunity:
    return Opportunity(
        id="opp-iot-fund",
        type=OpportunityType.funding,
        title="Vinnova IoT & Industry 4.0 Grant",
        url="https://vinnova.se/en/calls/iot-grant",
        source="Vinnova",
        published=TODAY,
        deadline=TODAY + timedelta(days=days_until_deadline),
        topics=["IoT", "sensors", "manufacturing", "wireless"],
        is_simulated=True,
    )


def _make_biotech_opportunity() -> Opportunity:
    return Opportunity(
        id="opp-bio-event",
        type=OpportunityType.event,
        title="Nordic Life Science Summit 2026",
        url="https://bsp.se/events/life-science-2026",
        source="Blue Science Park",
        event_date=TODAY + timedelta(days=45),
        topics=["biotech", "pharma", "clinical research", "gene therapy"],
        is_simulated=True,
    )


def _make_online_opportunity() -> Opportunity:
    return Opportunity(
        id="opp-online",
        type=OpportunityType.event,
        title="Global Innovation Webinar",
        url="https://example.com/webinar",
        source="Example",
        event_date=TODAY + timedelta(days=10),
        format=OpportunityFormat.online,
        topics=["innovation", "technology"],
        is_simulated=True,
    )


# ---------------------------------------------------------------------------
# 1. Model validation (contract compliance)
# ---------------------------------------------------------------------------

class TestClaimValidation:
    def test_valid_claim(self):
        c = Claim(field="technologies", value="IoT", kind=ClaimKind.stated)
        assert c.kind == ClaimKind.stated

    def test_confidence_out_of_range(self):
        with pytest.raises(Exception):
            Claim(field="f", value="v", kind=ClaimKind.inferred, confidence=1.5)

    def test_confidence_lower_bound(self):
        with pytest.raises(Exception):
            Claim(field="f", value="v", kind=ClaimKind.inferred, confidence=-0.1)

    def test_all_kinds_accepted(self):
        for kind in ClaimKind:
            c = Claim(field="f", value="v", kind=kind)
            assert c.kind == kind


class TestOpportunityValidation:
    def test_opportunity_requires_url(self):
        with pytest.raises(Exception):
            Opportunity(
                type=OpportunityType.funding,
                title="Bad",
                url="",
                source="X",
                published=TODAY,
            )

    def test_opportunity_requires_date(self):
        with pytest.raises(Exception):
            Opportunity(
                type=OpportunityType.funding,
                title="No date",
                url="https://example.com",
                source="X",
            )

    def test_valid_opportunity(self):
        opp = _make_iot_opportunity()
        assert opp.id == "opp-iot-fund"
        assert opp.is_simulated is True

    def test_relevant_date_priority(self):
        opp = Opportunity(
            type=OpportunityType.funding,
            title="T",
            url="https://x.com",
            source="X",
            published=TODAY,
            deadline=TODAY + timedelta(days=10),
            event_date=TODAY + timedelta(days=20),
        )
        # deadline takes priority
        assert opp.relevant_date() == TODAY + timedelta(days=10)


class TestRecommendationValidation:
    def test_score_out_of_range(self):
        with pytest.raises(Exception):
            Recommendation(
                company_id="x", opportunity_id="y",
                score=1.5, why="…", matched_claims=[],
            )

    def test_valid_recommendation(self):
        r = Recommendation(
            company_id="c", opportunity_id="o",
            score=0.75, why="Good match.", matched_claims=["c1"],
        )
        assert "eligibility not confirmed" in r.caveats


# ---------------------------------------------------------------------------
# 2. Sub-scorer: topic overlap
# ---------------------------------------------------------------------------

class TestTopicOverlapScore:
    def test_perfect_overlap(self):
        profile = _make_iot_profile()
        opp = _make_iot_opportunity()
        score, matched = _topic_overlap_score(profile, opp)
        assert score > 0.0
        assert len(matched) > 0

    def test_no_overlap(self):
        profile = _make_biotech_profile()
        opp = _make_iot_opportunity()
        score, matched = _topic_overlap_score(profile, opp)
        # Biotech profile should not match IoT opportunity well
        assert score < 0.3

    def test_no_opportunity_topics(self):
        profile = _make_iot_profile()
        opp = Opportunity(
            id="x", type=OpportunityType.event, title="T",
            url="https://x.com", source="X", published=TODAY,
            topics=[],
        )
        score, matched = _topic_overlap_score(profile, opp)
        assert score == 0.0
        assert matched == []

    def test_user_confirmed_boosts_score(self):
        """user_confirmed claims must visibly increase the score."""
        base_profile = CompanyProfile(
            company_id="c1", company_name="Base",
            claims=[
                Claim(id="x1", field="priorities", value="IoT platform expansion",
                      kind=ClaimKind.stated, confidence=0.9),
            ],
        )
        boosted_profile = CompanyProfile(
            company_id="c2", company_name="Boosted",
            claims=[
                Claim(id="x2", field="priorities", value="IoT platform expansion",
                      kind=ClaimKind.user_confirmed, confidence=1.0),
            ],
        )
        opp = _make_iot_opportunity()
        base_score, _ = _topic_overlap_score(base_profile, opp)
        boosted_score, _ = _topic_overlap_score(boosted_profile, opp)
        assert boosted_score > base_score, (
            f"user_confirmed should boost score: {base_score} vs {boosted_score}"
        )


# ---------------------------------------------------------------------------
# 3. Sub-scorer: timeline
# ---------------------------------------------------------------------------

class TestTimelineScore:
    def test_very_soon_deadline(self):
        opp = _make_iot_opportunity(days_until_deadline=5)
        score = _timeline_score(opp, today=TODAY)
        assert score == 1.0

    def test_deadline_at_full_score_boundary(self):
        opp = _make_iot_opportunity(days_until_deadline=config.TIMELINE_FULL_SCORE_DAYS)
        score = _timeline_score(opp, today=TODAY)
        assert score == 1.0

    def test_far_future_deadline(self):
        opp = _make_iot_opportunity(days_until_deadline=config.TIMELINE_ZERO_SCORE_DAYS + 10)
        score = _timeline_score(opp, today=TODAY)
        assert score == 0.0

    def test_mid_range_deadline(self):
        mid_days = (config.TIMELINE_FULL_SCORE_DAYS + config.TIMELINE_ZERO_SCORE_DAYS) // 2
        opp = _make_iot_opportunity(days_until_deadline=mid_days)
        score = _timeline_score(opp, today=TODAY)
        assert 0.0 < score < 1.0

    def test_expired_deadline_low_score(self):
        opp = _make_iot_opportunity(days_until_deadline=-5)
        score = _timeline_score(opp, today=TODAY)
        assert score < 0.2

    def test_no_date_returns_moderate(self):
        # Manufacture an opportunity with only published date far in the past
        # but no deadline/event_date, by patching relevant_date
        opp = Opportunity(
            id="nd", type=OpportunityType.funding, title="No date opp",
            url="https://x.com", source="X", published=TODAY,
            topics=["something"],
        )
        # Override relevant_date to return None for this test
        original = opp.relevant_date
        opp.relevant_date = lambda: None  # type: ignore[method-assign]
        score = _timeline_score(opp, today=TODAY)
        assert score == config.TIMELINE_NO_DATE_SCORE
        opp.relevant_date = original  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# 4. Sub-scorer: location / format
# ---------------------------------------------------------------------------

class TestLocationFormatScore:
    def test_online_always_full_score(self):
        profile = _make_iot_profile()
        opp = _make_online_opportunity()
        score = _location_format_score(profile, opp)
        assert score == 1.0

    def test_no_geo_focus_moderate(self):
        profile = CompanyProfile(
            company_id="c", company_name="C",
            claims=[Claim(id="x", field="technologies", value="AI", kind=ClaimKind.stated)],
        )
        opp = Opportunity(
            id="o", type=OpportunityType.event, title="T",
            url="https://x.com", source="X", published=TODAY,
            format=OpportunityFormat.in_person,
            topics=["AI"],
        )
        score = _location_format_score(profile, opp)
        assert 0.5 <= score <= 0.9

    def test_in_person_region_match(self):
        profile = CompanyProfile(
            company_id="c", company_name="C",
            claims=[
                Claim(id="g", field="geographic_focus", value="sweden",
                      kind=ClaimKind.stated),
            ],
        )
        opp = Opportunity(
            id="o", type=OpportunityType.event, title="T",
            url="https://x.com", source="X", published=TODAY,
            format=OpportunityFormat.in_person,
            audience="Open to companies in Sweden",
            topics=["tech"],
        )
        score = _location_format_score(profile, opp)
        assert score == 1.0

    def test_in_person_region_mismatch(self):
        profile = CompanyProfile(
            company_id="c", company_name="C",
            claims=[
                Claim(id="g", field="geographic_focus", value="norway",
                      kind=ClaimKind.stated),
            ],
        )
        opp = Opportunity(
            id="o", type=OpportunityType.event, title="T",
            url="https://x.com", source="X", published=TODAY,
            format=OpportunityFormat.in_person,
            audience="Open to companies in Germany",
            topics=["tech"],
        )
        score = _location_format_score(profile, opp)
        assert score < 0.5


# ---------------------------------------------------------------------------
# 5. Full match() function
# ---------------------------------------------------------------------------

class TestMatchFunction:
    def test_returns_recommendations(self):
        profile = _make_iot_profile()
        opps = [_make_iot_opportunity(), _make_biotech_opportunity()]
        recs = match(profile, opps, today=TODAY)
        assert len(recs) > 0

    def test_sorted_by_score_descending(self):
        profile = _make_iot_profile()
        opps = [_make_iot_opportunity(), _make_biotech_opportunity(), _make_online_opportunity()]
        recs = match(profile, opps, today=TODAY)
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_scores_in_range(self):
        profile = _make_iot_profile()
        opps = [_make_iot_opportunity(), _make_biotech_opportunity()]
        for rec in match(profile, opps, today=TODAY):
            assert 0.0 <= rec.score <= 1.0

    def test_recommendation_has_why(self):
        profile = _make_iot_profile()
        recs = match(profile, [_make_iot_opportunity()], today=TODAY)
        assert len(recs) > 0
        assert len(recs[0].why) > 10

    def test_recommendation_has_caveats(self):
        profile = _make_iot_profile()
        recs = match(profile, [_make_iot_opportunity()], today=TODAY)
        assert "eligibility not confirmed" in recs[0].caveats.lower()

    def test_matched_claims_reference_profile(self):
        profile = _make_iot_profile()
        claim_ids = {c.id for c in profile.claims}
        recs = match(profile, [_make_iot_opportunity()], today=TODAY)
        for rec in recs:
            for cid in rec.matched_claims:
                assert cid in claim_ids, f"Claim ID {cid!r} not in profile"

    def test_empty_opportunities(self):
        profile = _make_iot_profile()
        recs = match(profile, [], today=TODAY)
        assert recs == []

    def test_recommendation_validates_against_pydantic(self):
        """All returned objects must pass Pydantic validation."""
        profile = _make_iot_profile()
        opps = [_make_iot_opportunity(), _make_biotech_opportunity()]
        for rec in match(profile, opps, today=TODAY):
            # Reconstruct from dict — will raise if schema is violated
            validated = Recommendation.model_validate(rec.model_dump())
            assert validated.score == rec.score


# ---------------------------------------------------------------------------
# 6. DEMO REQUIREMENT: two companies get different rankings
# ---------------------------------------------------------------------------

class TestDifferentProfilesDifferentRankings:
    """
    Two companies with different profiles must get visibly different rankings.
    This is an explicit demo requirement (AGENTS.md §1 point 4).
    """

    def test_iot_ranks_iot_opp_higher_than_biotech_does(self):
        iot_profile = _make_iot_profile()
        bio_profile = _make_biotech_profile()
        iot_opp = _make_iot_opportunity()

        iot_recs = match(iot_profile, [iot_opp], today=TODAY)
        bio_recs = match(bio_profile, [iot_opp], today=TODAY)

        iot_score = iot_recs[0].score if iot_recs else 0.0
        bio_score = bio_recs[0].score if bio_recs else 0.0

        assert iot_score > bio_score, (
            f"IoT company should score higher on IoT opportunity: "
            f"iot={iot_score}, bio={bio_score}"
        )

    def test_biotech_ranks_bio_opp_higher_than_iot_does(self):
        iot_profile = _make_iot_profile()
        bio_profile = _make_biotech_profile()
        bio_opp = _make_biotech_opportunity()

        iot_recs = match(iot_profile, [bio_opp], today=TODAY)
        bio_recs = match(bio_profile, [bio_opp], today=TODAY)

        iot_score = iot_recs[0].score if iot_recs else 0.0
        bio_score = bio_recs[0].score if bio_recs else 0.0

        assert bio_score > iot_score, (
            f"Biotech company should score higher on biotech opportunity: "
            f"bio={bio_score}, iot={iot_score}"
        )

    def test_user_confirmed_priority_visibly_affects_ranking(self):
        """
        Adding a user_confirmed claim that matches the opportunity must
        raise the score noticeably.
        """
        base_profile = _make_biotech_profile()  # no IoT claims
        priority_profile = CompanyProfile(
            company_id="bio-with-iot-priority",
            company_name="BioMed + IoT Priority",
            claims=list(base_profile.claims) + [
                Claim(
                    id="priority-iot",
                    field="priorities",
                    value="IoT integration for clinical devices",
                    kind=ClaimKind.user_confirmed,
                    confidence=1.0,
                )
            ],
        )
        opp = _make_iot_opportunity()

        base_recs = match(base_profile, [opp], today=TODAY)
        priority_recs = match(priority_profile, [opp], today=TODAY)

        base_score = base_recs[0].score if base_recs else 0.0
        priority_score = priority_recs[0].score if priority_recs else 0.0

        assert priority_score > base_score, (
            f"user_confirmed priority should raise score: "
            f"base={base_score}, with_priority={priority_score}"
        )


# ---------------------------------------------------------------------------
# 7. `why` deterministic builder
# ---------------------------------------------------------------------------

class TestWhyDeterministic:
    def test_why_mentions_company(self):
        profile = _make_iot_profile()
        opp = _make_iot_opportunity()
        claims = profile.claims[:2]
        why = _build_why_deterministic(profile, opp, claims, 0.75)
        assert profile.company_name in why

    def test_why_mentions_opportunity(self):
        profile = _make_iot_profile()
        opp = _make_iot_opportunity()
        claims = profile.claims[:1]
        why = _build_why_deterministic(profile, opp, claims, 0.6)
        assert opp.title in why

    def test_why_no_matched_claims(self):
        profile = _make_iot_profile()
        opp = _make_iot_opportunity()
        why = _build_why_deterministic(profile, opp, [], 0.3)
        assert "No specific claims" in why
