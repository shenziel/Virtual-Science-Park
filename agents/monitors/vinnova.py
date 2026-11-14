"""
Funding Monitor: Vinnova calls.
Owner: Backend 3 (agents/monitors/)
"""
from __future__ import annotations

import json
import logging
from typing import Any, List

from contracts.models import Opportunity, OpportunityType

from . import config
from .base import BaseMonitor, sanitize_opportunity_data

logger = logging.getLogger(__name__)


class VinnovaFundingMonitor(BaseMonitor):
    """Monitor for Vinnova public funding calls and grants."""

    def __init__(self):
        super().__init__(
            source="Vinnova",
            default_type=OpportunityType.funding,
            snapshot_path=config.VINNOVA_SNAPSHOT_PATH,
        )

    def parse_feed(self, items: List[dict[str, Any]], cached_snapshot: bool = False) -> List[Opportunity]:
        """Normalize a list of call dictionaries into Opportunity objects."""
        opportunities: List[Opportunity] = []
        for item in items:
            opp = sanitize_opportunity_data(
                item,
                default_type=self.default_type,
                source=self.source,
                cached_snapshot=cached_snapshot,
                is_simulated=item.get("is_simulated", False),
            )
            if opp is not None:
                opportunities.append(opp)
        return opportunities

    def parse_response(self, text: str) -> List[Opportunity]:
        """Parses Vinnova API JSON or feed response."""
        try:
            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("utlysningar", [])
            return self.parse_feed(items, cached_snapshot=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse Vinnova response (%s); falling back to snapshot.", exc)
            return []

    def fetch_opportunities(self, force_cache: bool = False) -> List[Opportunity]:
        """
        Fetch calls from live Vinnova endpoint or load cached snapshot.
        Always gracefully falls back to dated cached snapshot if network is unavailable.
        """
        if force_cache:
            return self.load_cached_snapshot()

        raw_text = self.fetch_url(config.VINNOVA_API_URL)
        if raw_text:
            parsed = self.parse_response(raw_text)
            if parsed:
                return parsed

        return self.load_cached_snapshot()
