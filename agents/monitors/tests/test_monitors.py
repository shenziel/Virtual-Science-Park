"""
Pytest suite for agents/monitors/

Validates that:
- Funding monitor (Vinnova) produces valid Opportunity objects of type 'funding'
- Events monitor (Blue Science Park) produces valid Opportunity objects of type 'event'
- Opportunities missing live URLs or dates are dropped (never guessed)
- Offline fetches never substitute unverified opportunity snapshots
- Aggregated fetch_all_opportunities() returns valid opportunities adhering to contracts/models.py
"""
from __future__ import annotations

import os
import sys
from datetime import date
from typing import Any

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from contracts.models import Opportunity, OpportunityFormat, OpportunityType


TODAY = date(2026, 11, 13)


class TestDropIncompleteOpportunities:
    """AGENTS.md §5: Every opportunity needs a live url and a date. Drop items that have neither rather than guessing."""

    def test_drop_when_missing_url(self):
        from agents.monitors.base import sanitize_opportunity_data

        raw = {
            "title": "Innovative IoT Grant",
            "url": "",  # Missing URL
            "published": "2026-11-01",
            "deadline": "2026-12-01",
            "type": "funding",
            "source": "Vinnova",
            "topics": ["IoT"],
        }
        opp = sanitize_opportunity_data(raw, default_type=OpportunityType.funding, source="Vinnova")
        assert opp is None, "Item without URL must be dropped"

    def test_drop_when_missing_all_dates(self):
        from agents.monitors.base import sanitize_opportunity_data

        raw = {
            "title": "Industrial Summit",
            "url": "https://example.com/summit",
            "published": None,
            "deadline": None,
            "event_date": None,
            "type": "event",
            "source": "Blue Science Park",
            "topics": ["industry"],
        }
        opp = sanitize_opportunity_data(raw, default_type=OpportunityType.event, source="Blue Science Park")
        assert opp is None, "Item without any date must be dropped"

    def test_accept_when_valid_with_url_and_deadline(self):
        from agents.monitors.base import sanitize_opportunity_data

        raw = {
            "title": "Grant Call 2026",
            "url": "https://vinnova.se/calls/grant-2026",
            "deadline": "2026-12-15",
            "type": "funding",
            "source": "Vinnova",
            "topics": ["energy", "cleantech"],
        }
        opp = sanitize_opportunity_data(raw, default_type=OpportunityType.funding, source="Vinnova")
        assert opp is not None
        assert opp.url == "https://vinnova.se/calls/grant-2026"
        assert opp.deadline == date(2026, 12, 15)
        assert opp.type == OpportunityType.funding
        # Validates against Pydantic schema
        Opportunity.model_validate(opp.model_dump())

    def test_accept_when_valid_with_event_date(self):
        from agents.monitors.base import sanitize_opportunity_data

        raw = {
            "title": "Tech Meetup",
            "url": "https://bluesciencepark.se/events/tech-meetup",
            "event_date": "2026-12-05",
            "format": "in_person",
            "type": "event",
            "source": "Blue Science Park",
            "topics": ["AI", "networking"],
        }
        opp = sanitize_opportunity_data(raw, default_type=OpportunityType.event, source="Blue Science Park")
        assert opp is not None
        assert opp.event_date == date(2026, 12, 5)
        assert opp.format == OpportunityFormat.in_person
        assert opp.type == OpportunityType.event
        Opportunity.model_validate(opp.model_dump())


class TestVinnovaFundingMonitor:
    def test_parse_sample_vinnova_feed(self):
        from agents.monitors.vinnova import VinnovaFundingMonitor

        sample_feed = [
            {
                "id": "vinnova-call-101",
                "title": "Cirkulär ekonomi och biobaserade material",
                "url": "https://www.vinnova.se/en/calls-for-proposals/cirkular-ekonomi-2026/",
                "published": "2026-10-10",
                "deadline": "2027-02-15",
                "audience": "SMEs and universities",
                "eligibility_text": "Swedish businesses in partnership with research institutes.",
                "topics": ["circular economy", "bio-based materials", "sustainability"],
            },
            {
                "title": "Invalid Call - No URL",
                "url": None,
                "deadline": "2026-12-01",
                "topics": ["invalid"],
            },
            {
                "title": "Invalid Call - No Date",
                "url": "https://www.vinnova.se/call-no-date",
                "topics": ["invalid"],
            },
        ]
        monitor = VinnovaFundingMonitor()
        opportunities = monitor.parse_feed(sample_feed)

        # Only 1 valid opportunity should be extracted
        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp.type == OpportunityType.funding
        assert opp.source == "Vinnova"
        assert opp.url == "https://www.vinnova.se/en/calls-for-proposals/cirkular-ekonomi-2026/"
        assert opp.deadline == date(2027, 2, 15)
        assert "circular economy" in opp.topics
        Opportunity.model_validate(opp.model_dump())

    def test_no_mock_funding_when_live_data_is_not_requested(self):
        from agents.monitors.vinnova import VinnovaFundingMonitor

        monitor = VinnovaFundingMonitor()
        # Funding has no fabricated offline snapshot.
        opportunities = monitor.load_cached_snapshot()
        assert opportunities == []


class TestBSPEventsMonitor:
    def test_parse_sample_bsp_feed(self):
        from agents.monitors.bsp_events import BSPEventsMonitor

        sample_feed = [
            {
                "title": "AI & IoT in Manufacturing Seminar",
                "url": "https://www.bluesciencepark.se/evenemang/ai-iot-seminar-2026/",
                "event_date": "2026-11-28",
                "format": "in_person",
                "audience": "Engineers and industry managers",
                "eligibility_text": "Open to all member companies",
                "topics": ["AI", "industrial IoT", "sensors"],
            },
            {
                "title": "Virtual Tech Talk",
                "url": "https://www.bluesciencepark.se/evenemang/virtual-tech-talk/",
                "event_date": "2026-12-10",
                "format": "online",
                "topics": ["software", "cloud"],
            },
            {
                "title": "Undated Event",
                "url": "https://www.bluesciencepark.se/undated",
                "format": "online",
                "topics": ["test"],
            },
        ]
        monitor = BSPEventsMonitor()
        opportunities = monitor.parse_feed(sample_feed)

        # 2 valid events should be extracted
        assert len(opportunities) == 2
        for opp in opportunities:
            assert opp.type == OpportunityType.event
            assert opp.source == "Blue Science Park"
            assert opp.url.startswith("https://")
            assert opp.event_date is not None
            Opportunity.model_validate(opp.model_dump())

    def test_no_dead_event_snapshot_is_served(self):
        from agents.monitors.bsp_events import BSPEventsMonitor

        monitor = BSPEventsMonitor()
        opportunities = monitor.load_cached_snapshot()
        assert opportunities == []


class TestFetchAllOpportunities:
    """Checks end-to-end integration of all monitors."""

    def test_cached_fetch_does_not_return_dead_or_mock_sources(self):
        from agents.monitors import fetch_all_opportunities

        # There are no verified offline opportunity snapshots.
        opportunities = fetch_all_opportunities(force_cache=True)
        assert opportunities == []

    def test_unique_ids(self):
        from agents.monitors import fetch_all_opportunities

        opportunities = fetch_all_opportunities(force_cache=True)
        ids = [opp.id for opp in opportunities]
        assert len(ids) == len(set(ids)), f"Duplicate opportunity IDs found: {ids}"
