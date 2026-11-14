"""
Events Monitor: Blue Science Park events.
Owner: Backend 3 (agents/monitors/)
"""
from __future__ import annotations

import json
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any, List

from contracts.models import Opportunity, OpportunityFormat, OpportunityType

from . import config
from .base import BaseMonitor, parse_date_safely, sanitize_opportunity_data

logger = logging.getLogger(__name__)

_MONTHS = {
    "january": 1, "jan": 1, "januari": 1,
    "february": 2, "feb": 2, "februari": 2,
    "march": 3, "mar": 3, "mars": 3,
    "april": 4, "apr": 4,
    "may": 5, "maj": 5,
    "june": 6, "jun": 6, "juni": 6,
    "july": 7, "jul": 7, "juli": 7,
    "august": 8, "aug": 8, "augusti": 8,
    "september": 9, "sep": 9,
    "october": 10, "oct": 10, "oktober": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH_PATTERN = "|".join(sorted((re.escape(m) for m in _MONTHS), key=len, reverse=True))


def _plain_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"(?i)<\s*(?:br|/p|/li|/h[1-6]|/div)[^>]*>", "\n", value)
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).replace("\xa0", " ").strip()


def _date_from_explicit_text(value: str) -> date | None:
    """Parse a full date only; never infer the year from a post's publish date."""
    patterns = (
        re.compile(r"\b(?P<year>20\d{2})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})\b"),
        re.compile(
            rf"\b(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_PATTERN})\.?\s+(?P<year>20\d{{2}})\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b(?P<month>{_MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(?P<year>20\d{{2}})\b",
            re.IGNORECASE,
        ),
    )
    for pattern in patterns:
        match = pattern.search(value)
        if not match:
            continue
        fields = match.groupdict()
        month_value = fields["month"]
        month = int(month_value) if month_value.isdigit() else _MONTHS[month_value.lower().rstrip(".")]
        try:
            return date(int(fields["year"]), month, int(fields["day"]))
        except ValueError:
            return None
    return None


def _extract_event_date(content: Any) -> date | None:
    """Extract an explicitly year-qualified date adjacent to a date label."""
    text = _plain_text(content)
    for match in re.finditer(r"(?i)\b(?:date|datum|when|när)\b\s*[:\-]?\s*([^\n]{1,160})", text):
        event_date = _date_from_explicit_text(match.group(1))
        if event_date:
            return event_date
    return None


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
        """Parse RSS entries only when their description gives a full event date."""
        items: List[dict[str, Any]] = []
        try:
            root = ET.fromstring(xml_text)
            # Support RSS 2.0 channel/item
            for item in root.findall(".//item"):
                title = item.findtext("title")
                link = item.findtext("link")
                pub_date = item.findtext("pubDate")
                desc = item.findtext("description") or ""
                event_date = _extract_event_date(desc)
                if not event_date or event_date < date.today():
                    continue

                # Only set a format when the source explicitly says online.
                fmt = (
                    OpportunityFormat.online
                    if "online" in desc.lower() or "webinar" in (title or "").lower()
                    else None
                )

                items.append({
                    "title": title,
                    "url": link,
                    "published": parse_date_safely(pub_date),
                    "event_date": event_date,
                    "format": fmt,
                    "source": self.source,
                    "type": self.default_type,
                    "topics": [t.strip() for t in desc.split() if len(t.strip()) > 3][:5],
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse Blue Science Park RSS XML (%s).", exc)
            return []

        return self.parse_feed(items, cached_snapshot=False)

    def parse_wp_events(self, records: List[dict[str, Any]]) -> List[Opportunity]:
        """Normalize Blue Science Park's public WordPress event records."""
        opportunities: List[Opportunity] = []
        today = date.today()
        for record in records:
            title_data = record.get("title") or {}
            title = _plain_text(
                title_data.get("rendered") if isinstance(title_data, dict) else title_data
            )
            url = str(record.get("link") or "").strip()
            content_data = record.get("content") or {}
            content = (
                content_data.get("rendered")
                if isinstance(content_data, dict)
                else content_data
            )
            excerpt_data = record.get("excerpt") or {}
            excerpt = _plain_text(
                excerpt_data.get("rendered") if isinstance(excerpt_data, dict) else excerpt_data
            )
            event_date = _extract_event_date(content)
            if not title or not event_date or event_date < today:
                continue

            published = parse_date_safely(record.get("date"))
            topics = [title]
            if excerpt:
                topics.append(excerpt[:500])
            opportunity = sanitize_opportunity_data(
                {
                    "id": f"bsp-event-{record.get('id')}",
                    "title": title,
                    "url": url,
                    "published": published,
                    "event_date": event_date,
                    "topics": topics,
                },
                default_type=self.default_type,
                source=self.source,
                cached_snapshot=False,
                is_simulated=False,
            )
            if opportunity:
                opportunities.append(opportunity)
        return opportunities

    def fetch_opportunities(self, force_cache: bool = False) -> List[Opportunity]:
        """
        Fetch events from Blue Science Park's public WordPress event collection.
        Only records with an explicitly dated, future event are returned.
        """
        if force_cache:
            return self.load_cached_snapshot()

        raw_text = self.fetch_url(config.BSP_EVENTS_FEED_URL)
        if raw_text:
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                return self.parse_rss(raw_text) if raw_text.lstrip().startswith("<") else []
            if isinstance(data, list):
                return self.parse_wp_events([item for item in data if isinstance(item, dict)])
        return []
