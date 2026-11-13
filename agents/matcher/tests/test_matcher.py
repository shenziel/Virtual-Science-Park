"""
Pytest suite for agents/matcher/

Uses contracts.models as the shared source of truth — same as production.

Covers:
- topic_overlap_score, timeline_score, location_format_score
- match() ranking and user_confirmed boost
- Deterministic `why` generation
- Two companies with different profiles get visibly different rankings (demo req)
- Recommendation validates against contracts.models.Recommendation
"""
from __future__ import annotations

import sys
import os
from datetime import date, datetime, timedelta, timezone

# Make the package importable when pytest runs from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from contracts.models import (
    Claim,
    ClaimKind,
    Opportunity,
    OpportunityFormat,
    OpportunityType,
    Profile,
    ProfileField,
    Recommendation,
    Visibility,
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
# Constants
# ---------------------------------------------------------------------------

TODAY = date(2026, 11, 13)
NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Shared fixture builders
# ---------------------------------------------------------------------------

def _make_iot_profile() -> Profile:
    """IoT / industrial sensors company."""
    return Profile(
        company_id="nordsense",
        name="NordSense AB",
        website="https://nordsense.example.com",
        visibility=Visibility.published,
        is_simulated=True,
        updated_at=NOW,
        claims=[
            Claim(
                id="tech-1",
                field=ProfileField.technologies,
                value="industrial IoT sensors",
                kind=ClaimKind.stated,
                evidence_url="https://nordsense.example.com/about",
                snippet="Industrial IoT sensors are at the core of everything we build.",
                retrieved_at=TODAY,
                confidence=0.95,
            ),
            Claim(
                id="mkt-1",
                field=ProfileField.markets,
                value="Nordic process industry",
                kind=ClaimKind.stated,
                evidence_url="https://nordsense.example.com/about",
                snippet="We serve the Nordic process industry.",
                retrieved_at=TODAY,
                confidence=0.9,
            ),
            Claim(
                id="exp-1",
                field=ProfileField.expertise,
                value="predictive maintenance",
                kind=ClaimKind.inferred,
                evidence_url="https://nordsense.example.com/cases",
                retrieved_at=TODAY,
                confidence=0.75,
            ),
            Claim(
                id="prio-1",
                field=ProfileField.development_priorities,
                value="IoT platform expansion for mining sector",
                kind=ClaimKind.user_confirmed,
                retrieved_at=TODAY,
                confidence=1.0,
            ),
        ],
        missing_fields=[],
    )


def _make_biotech_profile() -> Profile:
    """Biotech / life sciences company."""
    return Profile(
        company_id="biomed",
        name="BioMed Innovations",
        website="https://biomed.example.com",
        visibility=Visibility.published,
        is_simulated=True,
        updated_at=NOW,
        claims=[
            Claim(
                id="tech-1",
                field=ProfileField.technologies,
                value="CRISPR gene editing",
                kind=ClaimKind.stated,
                evidence_url="https://biomed.example.com/tech",
                snippet="We use CRISPR gene editing to develop novel therapies.",
                retrieved_at=TODAY,
                confidence=0.95,
            ),
            Claim(
                id="mkt-1",
                field=ProfileField.markets,
                value="pharmaceutical companies",
                kind=ClaimKind.stated,
                evidence_url="https://biomed.example.com/about",
                snippet="Our customers are pharmaceutical companies worldwide.",
                retrieved_at=TODAY,
                confidence=0.9,
            ),
            Claim(
                id="exp-1",
                field=ProfileField.expertise,
                value="clinical trials management",
                kind=ClaimKind.inferred,
                evidence_url="https://biomed.example.com/services",
                retrieved_at=TODAY,
                confidence=0.75,
            ),
        ],
        missing_fields=[ProfileField.collaborations],
    )


def _make_iot_opportunity(*, days_until_deadline: int = 20) -> Opportunity:
    return Opportunity(
        id="sim-fund-industry-ai",
        type=OpportunityType.funding,
        title="Simulated: AI and sensors for efficient process industry",
        url="https://funding.example.com/calls/industry-ai",
        source="Simulated funding source",
        published=TODAY,
        deadline=TODAY + timedelta(days=days_until_deadline),
        topics=["industrial IoT", "predictive maintenance", "AI", "process industry"],
        retrieved_at=TODAY,
        is_simulated=True,
    )


def _make_biotech_opportunity() -> Opportunity:
    return Opportunity(
        id="sim-event-biotech",
        type=OpportunityType.event,
        title="Simulated: Nordic Life Science Summit 2026",
        url="https://events.example.com/life-science",
        source="Simulated events source",
        event_date=TODAY + timedelta(days=45),
        topics=["biotech", "pharma", "clinical research", "gene therapy"],
        retrieved_at=TODAY,
        is_simulated=True,
    )


def _make_online_opportunity() -> Opportunity:
    return Opportunity(
        id="sim-event-webinar",
        type=OpportunityType.event,
        title="Simulated: Global Innovation Webinar",
        url="https://events.example.com/webinar",
        source="Simulated events source",
        event_date=TODAY + timedelta(days=10),
        format=OpportunityFormat.online,
        topics=["innovation", "technology", "IoT"],
        retrieved_at=TODAY,
        is_simulated=True,
    )


# ---------------------------------------------------------------------------
# 1. Topic overlap
# ---------------------------------------------------------------------------

class TestTopicOverlapScore:
    def test_iot_profile_matches_iot_opp(self):
        profile = _make_iot_profile()
        opp = _make_iot_opportunity()
        score, matched = _topic_overlap_score(profile, opp)
        assert score > 0.0
        assert len(matched) > 0

    def test_biotech_profile_low_match_on_iot_opp(self):
        profile = _make_biotech_profile()
        opp = _make_iot_opportunity()
        score, matched = _topic_overlap_score(profile, opp)
        assert score < 0.3

    def test_no_opportunity_topics_returns_zero(self):
        profile = _make_iot_profile()
        opp = Opportunity(
            id="sim-no-topics",
            type=OpportunityType.event,
            title="Simulated: No topic opp",
            url="https://events.example.com/no-topics",
            source="Simulated",
            published=TODAY,
            topics=[],
            retrieved_at=TODAY,
            is_simulated=True,
        )
        score, matched = _topic_overlap_score(profile, opp)
        assert score == 0.0
        assert matched == []

    def test_user_confirmed_boosts_score(self):
        """user_confirmed claims must produce a higher score than stated claims with same value."""
        stated_profile = Profile(
            company_id="stated-co",
            name="Stated Co",
            website="https://stated.example.com",
            visibility=Visibility.published,
            is_simulated=True,
            updated_at=NOW,
            claims=[
                Claim(
                    id="prio-1",
                    field=ProfileField.development_priorities,
                    value="IoT platform expansion",
                    kind=ClaimKind.stated,
                    evidence_url="https://stated.example.com/news",
                    snippet="IoT platform expansion is our focus.",
                    retrieved_at=TODAY,
                    confidence=0.9,
                ),
            ],
            missing_fields=[],
        )
        confirmed_profile = Profile(
            company_id="confirmed-co",
            name="Confirmed Co",
            website="https://confirmed.example.com",
            visibility=Visibility.published,
            is_simulated=True,
            updated_at=NOW,
            claims=[
                Claim(
                    id="prio-1",
                    field=ProfileField.development_priorities,
                    value="IoT platform expansion",
                    kind=ClaimKind.user_confirmed,
                    retrieved_at=TODAY,
                    confidence=1.0,
                ),
            ],
            missing_fields=[],
        )
        opp = _make_iot_opportunity()
        stated_score, _ = _topic_overlap_score(stated_profile, opp)
        confirmed_score, _ = _topic_overlap_score(confirmed_profile, opp)
        assert confirmed_score > stated_score, (
            f"user_confirmed should boost score: stated={stated_score}, confirmed={confirmed_score}"
        )


# ---------------------------------------------------------------------------
# 2. Timeline score
# ---------------------------------------------------------------------------

class TestTimelineScore:
    def test_very_soon_deadline_full_score(self):
        opp = _make_iot_opportunity(days_until_deadline=5)
        assert _timeline_score(opp, today=TODAY) == 1.0

    def test_deadline_at_boundary_full_score(self):
        opp = _make_iot_opportunity(days_until_deadline=config.TIMELINE_FULL_SCORE_DAYS)
        assert _timeline_score(opp, today=TODAY) == 1.0

    def test_far_future_zero_score(self):
        opp = _make_iot_opportunity(days_until_deadline=config.TIMELINE_ZERO_SCORE_DAYS + 10)
        assert _timeline_score(opp, today=TODAY) == 0.0

    def test_mid_range_between_zero_and_one(self):
        mid = (config.TIMELINE_FULL_SCORE_DAYS + config.TIMELINE_ZERO_SCORE_DAYS) // 2
        opp = _make_iot_opportunity(days_until_deadline=mid)
        score = _timeline_score(opp, today=TODAY)
        assert 0.0 < score < 1.0

    def test_expired_deadline_low_score(self):
        opp = _make_iot_opportunity(days_until_deadline=-5)
        assert _timeline_score(opp, today=TODAY) < 0.2


# ---------------------------------------------------------------------------
# 3. Location / format score
# ---------------------------------------------------------------------------

class TestLocationFormatScore:
    def test_online_always_full_score(self):
        profile = _make_iot_profile()
        opp = _make_online_opportunity()
        assert _location_format_score(profile, opp) == 1.0

    def test_no_geo_focus_in_person_moderate(self):
        profile = Profile(
            company_id="no-geo",
            name="No Geo Co",
            website="https://no-geo.example.com",
            visibility=Visibility.published,
            is_simulated=True,
            updated_at=NOW,
            claims=[
                Claim(
                    id="tech-1",
                    field=ProfileField.technologies,
                    value="AI analytics",
                    kind=ClaimKind.stated,
                    evidence_url="https://no-geo.example.com/tech",
                    snippet="AI analytics is our core.",
                    retrieved_at=TODAY,
                    confidence=0.9,
                ),
            ],
            missing_fields=[ProfileField.geographic_focus],
        )
        opp = Opportunity(
            id="sim-event-local",
            type=OpportunityType.event,
            title="Simulated: Local event",
            url="https://events.example.com/local",
            source="Simulated",
            published=TODAY,
            format=OpportunityFormat.in_person,
            topics=["AI"],
            retrieved_at=TODAY,
            is_simulated=True,
        )
        score = _location_format_score(profile, opp)
        assert 0.5 <= score <= 0.9

    def test_in_person_region_match_full_score(self):
        profile = _make_iot_profile()  # has geographic_focus: "Sweden, Finland and Norway"
        opp = Opportunity(
            id="sim-event-sweden",
            type=OpportunityType.event,
            title="Simulated: Swedish event",
            url="https://events.example.com/sweden",
            source="Simulated",
            published=TODAY,
            format=OpportunityFormat.in_person,
            audience="Open to companies in Sweden",
            topics=["IoT"],
            retrieved_at=TODAY,
            is_simulated=True,
        )
        # NOTE: _make_iot_profile has no geographic_focus — add one:
        from contracts.models import ProfileField as PF
        profile2 = Profile(
            company_id="nordic-co",
            name="Nordic Co",
            website="https://nordic.example.com",
            visibility=Visibility.published,
            is_simulated=True,
            updated_at=NOW,
            claims=[
                Claim(
                    id="geo-1",
                    field=PF.geographic_focus,
                    value="Sweden, Finland and Norway",
                    kind=ClaimKind.stated,
                    evidence_url="https://nordic.example.com/contact",
                    snippet="Offices and partners in Sweden, Finland and Norway.",
                    retrieved_at=TODAY,
                    confidence=0.9,
                ),
            ],
            missing_fields=[],
        )
        assert _location_format_score(profile2, opp) == 1.0

    def test_in_person_region_mismatch_low_score(self):
        from contracts.models import ProfileField as PF
        profile = Profile(
            company_id="norway-co",
            name="Norway Co",
            website="https://norway.example.com",
            visibility=Visibility.published,
            is_simulated=True,
            updated_at=NOW,
            claims=[
                Claim(
                    id="geo-1",
                    field=PF.geographic_focus,
                    value="norway",
                    kind=ClaimKind.stated,
                    evidence_url="https://norway.example.com/contact",
                    snippet="Offices in Norway.",
                    retrieved_at=TODAY,
                    confidence=0.9,
                ),
            ],
            missing_fields=[],
        )
        opp = Opportunity(
            id="sim-event-germany",
            type=OpportunityType.event,
            title="Simulated: German event",
            url="https://events.example.com/germany",
            source="Simulated",
            published=TODAY,
            format=OpportunityFormat.in_person,
            audience="Open to companies in Germany",
            topics=["tech"],
            retrieved_at=TODAY,
            is_simulated=True,
        )
        assert _location_format_score(profile, opp) < 0.5


# ---------------------------------------------------------------------------
# 4. Full match() function
# ---------------------------------------------------------------------------

class TestMatchFunction:
    def test_returns_recommendations(self):
        profile = _make_iot_profile()
        opps = [_make_iot_opportunity(), _make_online_opportunity()]
        recs = match(profile, opps, today=TODAY)
        assert len(recs) > 0

    def test_sorted_by_score_descending(self):
        profile = _make_iot_profile()
        opps = [_make_iot_opportunity(), _make_online_opportunity(), _make_biotech_opportunity()]
        recs = match(profile, opps, today=TODAY)
        scores = [r.score for r in recs]
        assert scores == sorted(scores, reverse=True)

    def test_scores_in_valid_range(self):
        profile = _make_iot_profile()
        opps = [_make_iot_opportunity(), _make_online_opportunity()]
        for rec in match(profile, opps, today=TODAY):
            assert 0.0 <= rec.score <= 1.0

    def test_recommendation_has_why(self):
        profile = _make_iot_profile()
        recs = match(profile, [_make_iot_opportunity()], today=TODAY)
        assert len(recs) > 0
        assert len(recs[0].why) > 10

    def test_recommendation_has_eligibility_caveat(self):
        profile = _make_iot_profile()
        recs = match(profile, [_make_iot_opportunity()], today=TODAY)
        assert len(recs) > 0
        assert "eligibility not confirmed" in recs[0].caveats.lower()

    def test_matched_claims_reference_profile_claim_ids(self):
        profile = _make_iot_profile()
        claim_ids = {c.id for c in profile.claims}
        for rec in match(profile, [_make_iot_opportunity()], today=TODAY):
            for cid in rec.matched_claims:
                assert cid in claim_ids, f"Claim ID {cid!r} not found in profile"

    def test_matched_claims_min_length_one(self):
        """Contract requires matched_claims has at least 1 item."""
        profile = _make_iot_profile()
        for rec in match(profile, [_make_iot_opportunity()], today=TODAY):
            assert len(rec.matched_claims) >= 1

    def test_no_match_when_no_overlap(self):
        """An opportunity with zero topic overlap should not appear in results."""
        profile = _make_biotech_profile()
        # Only add an opp with no biotech-related topics
        opp = Opportunity(
            id="sim-event-agri",
            type=OpportunityType.event,
            title="Simulated: Agriculture summit",
            url="https://events.example.com/agri",
            source="Simulated",
            published=TODAY,
            topics=["agriculture", "farming", "crop science"],
            retrieved_at=TODAY,
            is_simulated=True,
        )
        recs = match(profile, [opp], today=TODAY)
        assert recs == []

    def test_empty_opportunities_returns_empty(self):
        profile = _make_iot_profile()
        assert match(profile, [], today=TODAY) == []

    def test_recommendation_validates_against_pydantic(self):
        """All returned objects must pass contracts.models.Recommendation validation."""
        profile = _make_iot_profile()
        opps = [_make_iot_opportunity(), _make_online_opportunity()]
        for rec in match(profile, opps, today=TODAY):
            validated = Recommendation.model_validate(rec.model_dump())
            assert validated.score == rec.score
            assert len(validated.matched_claims) >= 1

    def test_uses_fixture_opportunities(self):
        """Smoke test against the real fixture opportunities.json."""
        import json
        fixture_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "fixtures", "mock", "opportunities.json"
        )
        with open(fixture_path) as f:
            raw = json.load(f)
        opps = [Opportunity.model_validate(o) for o in raw]
        profile = _make_iot_profile()
        recs = match(profile, opps, today=TODAY)
        assert len(recs) > 0
        for rec in recs:
            Recommendation.model_validate(rec.model_dump())

    def test_uses_fixture_nordsense_profile(self):
        """Smoke test against the real nordsense fixture profile."""
        import json
        profile_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "fixtures", "mock", "profiles", "nordsense.json"
        )
        with open(profile_path) as f:
            raw = json.load(f)
        profile = Profile.model_validate(raw)
        opp = _make_iot_opportunity()
        recs = match(profile, [opp], today=TODAY)
        assert len(recs) > 0


# ---------------------------------------------------------------------------
# 5. DEMO REQUIREMENT: two companies get visibly different rankings
# ---------------------------------------------------------------------------

class TestDifferentProfilesDifferentRankings:
    """
    Two companies with different profiles must get visibly different rankings.
    This is an explicit demo requirement (AGENTS.md §1 point 4).
    """

    def test_iot_ranks_iot_opp_higher_than_biotech(self):
        iot = _make_iot_profile()
        bio = _make_biotech_profile()
        opp = _make_iot_opportunity()

        iot_recs = match(iot, [opp], today=TODAY)
        bio_recs = match(bio, [opp], today=TODAY)

        iot_score = iot_recs[0].score if iot_recs else 0.0
        bio_score = bio_recs[0].score if bio_recs else 0.0

        assert iot_score > bio_score, (
            f"IoT company should outscore biotech on IoT opp: iot={iot_score}, bio={bio_score}"
        )

    def test_biotech_ranks_bio_opp_higher_than_iot(self):
        iot = _make_iot_profile()
        bio = _make_biotech_profile()
        opp = _make_biotech_opportunity()

        iot_recs = match(iot, [opp], today=TODAY)
        bio_recs = match(bio, [opp], today=TODAY)

        iot_score = iot_recs[0].score if iot_recs else 0.0
        bio_score = bio_recs[0].score if bio_recs else 0.0

        assert bio_score > iot_score, (
            f"Biotech company should outscore IoT on biotech opp: bio={bio_score}, iot={iot_score}"
        )

    def test_user_confirmed_priority_visibly_affects_ranking(self):
        """
        Adding a user_confirmed claim that matches the opportunity must
        raise the score noticeably.
        """
        base = _make_biotech_profile()
        # Biotech company adds a user_confirmed IoT priority
        new_claim = Claim(
            id="prio-iot",
            field=ProfileField.development_priorities,
            value="IoT integration for connected clinical devices",
            kind=ClaimKind.user_confirmed,
            retrieved_at=TODAY,
            confidence=1.0,
        )
        boosted = Profile(
            company_id="biomed-boosted",
            name="BioMed + IoT Priority",
            website="https://biomed.example.com",
            visibility=Visibility.published,
            is_simulated=True,
            updated_at=NOW,
            claims=list(base.claims) + [new_claim],
            missing_fields=[],
        )
        opp = _make_iot_opportunity()

        base_recs = match(base, [opp], today=TODAY)
        boosted_recs = match(boosted, [opp], today=TODAY)

        base_score = base_recs[0].score if base_recs else 0.0
        boosted_score = boosted_recs[0].score if boosted_recs else 0.0

        assert boosted_score > base_score, (
            f"user_confirmed priority should raise score: base={base_score}, boosted={boosted_score}"
        )


# ---------------------------------------------------------------------------
# 6. Deterministic `why` builder
# ---------------------------------------------------------------------------

class TestWhyDeterministic:
    def test_why_mentions_company_name(self):
        profile = _make_iot_profile()
        opp = _make_iot_opportunity()
        claims = profile.claims[:2]
        why = _build_why_deterministic(profile, opp, claims)
        assert profile.name in why

    def test_why_mentions_opportunity_title(self):
        profile = _make_iot_profile()
        opp = _make_iot_opportunity()
        claims = profile.claims[:1]
        why = _build_why_deterministic(profile, opp, claims)
        assert opp.title in why

    def test_why_is_non_empty(self):
        profile = _make_iot_profile()
        opp = _make_iot_opportunity()
        why = _build_why_deterministic(profile, opp, profile.claims[:1])
        assert len(why) > 0
