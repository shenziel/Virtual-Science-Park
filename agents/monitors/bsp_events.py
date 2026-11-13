"""
Events Monitor: Blue Science Park events.
Owner: Backend 3 (agents/monitors/)
"""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any, List

from contracts.models import Opportunity, OpportunityFormat, OpportunityType

from . import config
from .base import BaseMonitor, parse_date_safely, sanitize_opportunity_data

logger = logging.getLogger(__name__)


class BSPEventsMonitor(BaseMonitor):
    """Monitor for Blue Science Park public events and seminars."""

    def __init__(self):
        super().__init__(
            source="Blue Science Park",
            default_type=OpportunityType.event,
            snapshot_path=config.BSP_EVENTS_SNAPSHOT_PATH,
        )

    def parse_feed(self, items: List[dict[str, Any]], cached_snapshot: bool = False) -> List[Opportunity]:
        """Normalize a list of event dictionaries into Opportunity objects."""
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

    def parse_rss(self, xml_text: str) -> List[Opportunity]:
        """Parses standard RSS / Atom XML feed of events."""
        items: List[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
            # Support RSS 2.0 channel/item
            for item in root.findall(".//item"):
                title = item.findtext("title")
                link = item.findtext("link")
                pub_date = item.findtext("pubDate")
                desc = item.findtext("description") or ""

                # Extract format if mentioned
                fmt = OpportunityFormat.online if "online" in desc.lower() or "webinar" in (title or "").lower() else OpportunityFormat.in_person

                items.append({
                    "title": title,
                    "url": link,
                    "published": parse_date_safely(pub_date) or date.today(),
                    "event_date": parse_date_safely(pub_date),
                    "format": fmt,
                    "source": self.source,
                    "type": self.default_type,
                    "topics": [t.strip() for t in desc.split() if len(t.strip()) > 3][:5],
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse RSS XML (%s); falling back to snapshot.", exc)
            return []

        return self.parse_feed(items, cached_snapshot=False)

    def fetch_opportunities(self, force_cache: bool = False) -> List[Opportunity]:
        """
        Fetch events from live BSP events feed or load cached snapshot.
        Gracefully falls back to dated cached snapshot if network is unavailable.
        """
        if force_cache:
            return self.load_cached_snapshot()

        raw_text = self.fetch_url(config.BSP_EVENTS_FEED_URL)
        if raw_text:
            if raw_text.strip().startswith("<"):
                parsed = self.parse_rss(raw_text)
            else:
                try:
                    data = json.loads(raw_text)
                    items = data if isinstance(data, list) else data.get("events", [])
                    parsed = self.parse_feed(items, cached_snapshot=False)
                except Exception:
                    parsed = []
            if parsed:
                return parsed

        return self.load_cached_snapshot()
