"""
Opportunity Monitors package.
Owner: Backend 3 (agents/monitors/)

Monitors public funding and events sources for Blue Science Park members:
1. VinnovaFundingMonitor: public funding calls
2. BSPEventsMonitor: public science park events & webinars
"""
from __future__ import annotations

import logging
from typing import List

from contracts.models import Opportunity

from .bsp_events import BSPEventsMonitor
from .vinnova import VinnovaFundingMonitor

logger = logging.getLogger(__name__)


def fetch_all_opportunities(force_cache: bool = False) -> List[Opportunity]:
    """
    Fetch opportunities from all active monitors (Funding + Events).
    Falls back to labelled cached snapshots when offline.
    """
    funding_monitor = VinnovaFundingMonitor()
    events_monitor = BSPEventsMonitor()

    funding_opps = funding_monitor.fetch_opportunities(force_cache=force_cache)
    events_opps = events_monitor.fetch_opportunities(force_cache=force_cache)

    combined: List[Opportunity] = []
    seen_ids = set()

    for opp in funding_opps + events_opps:
        if opp.id not in seen_ids:
            seen_ids.add(opp.id)
            combined.append(opp)

    logger.info(
        "Fetched %d total opportunities (%d funding, %d events).",
        len(combined),
        len(funding_opps),
        len(events_opps),
    )
    return combined


__all__ = [
    "VinnovaFundingMonitor",
    "BSPEventsMonitor",
    "fetch_all_opportunities",
]
