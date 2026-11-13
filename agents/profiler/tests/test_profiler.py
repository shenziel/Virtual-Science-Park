import pytest
from datetime import date
from agents.profiler.models import Claim, CompanyProfile
from agents.profiler.profiler import ProfilerAgent

def test_claim_validation():
    claim = Claim(
        field="technologies",
        value="industrial IoT sensors",
        kind="stated",
        evidence_url="https://example.com/about",
        snippet="We develop industrial IoT sensors for smart manufacturing.",
        retrieved_at="2026-11-13",
        confidence=0.9
    )
    assert claim.field == "technologies"
    assert claim.kind == "stated"
    assert claim.confidence == 0.9

def test_company_profile_validation():
    claim = Claim(
        field="products_services",
        value="Smart grid software",
        kind="stated",
        evidence_url="https://example.com/products",
        snippet="Our smart grid software optimizes energy flow.",
        retrieved_at="2026-11-13",
        confidence=1.0
    )
    profile = CompanyProfile(
        company_id="comp-1",
        company_name="Example AB",
        website_url="https://example.com",
        claims=[claim],
        is_cached=True,
        cache_note="cached snapshot"
    )
    assert profile.company_id == "comp-1"
    assert len(profile.claims) == 1
    assert profile.is_cached is True

def test_profiler_missing_fields_handling():
    agent = ProfilerAgent(llm_client=None) # mock mode
    # Test fallback/mock profile generation when offline or no API key
    profile = agent.profile_company(
        company_id="comp-2",
        company_name="Test Corp",
        website_url="https://testcorp.se",
        html_content="<html><body>Test Corp provides green tech solutions.</body></html>"
    )
    assert isinstance(profile, CompanyProfile)
    assert len(profile.claims) > 0
    # Verify all 6 profile areas are covered (or flagged as missing/uncertain if not found)
    covered_fields = {c.field for c in profile.claims}
    required_fields = {
        "products_services",
        "technologies_expertise",
        "markets_industries",
        "geographic_focus",
        "development_priorities",
        "topics_opportunities"
    }
    for field in required_fields:
        assert field in covered_fields
