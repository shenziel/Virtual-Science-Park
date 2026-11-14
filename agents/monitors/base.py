"""
Base classes and sanitization logic for opportunity monitors.
Owner: Backend 3 (agents/monitors/)
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any, List, Optional

from contracts.models import Opportunity, OpportunityFormat, OpportunityType

from . import config

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Turn arbitrary text into a valid Slug (^[a-z0-9][a-z0-9-]*$)."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"opp-{cleaned}".strip("-")
    # Truncate to reasonable length
    return cleaned[:60].rstrip("-")


def parse_date_safely(value: Any) -> Optional[date]:
    """Parse date from date object or ISO date string (YYYY-MM-DD)."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        # Handle full ISO timestamps e.g. 2026-11-13T10:00:00Z
        if "T" in v:
            v = v.split("T")[0]
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None
    return None


def sanitize_opportunity_data(
    raw: dict[str, Any],
    default_type: OpportunityType,
    source: str,
    cached_snapshot: bool = False,
    is_simulated: bool = False,
) -> Optional[Opportunity]:
    """
    Validates and normalizes raw opportunity data into a canonical Opportunity model.
    AGENTS.md §5 rules:
    - Every opportunity needs a live url and a date. Drop items that have neither rather than guessing.
    - Returns None if the item fails the contract criteria.
    """
    title = str(raw.get("title") or "").strip()
    if not title:
        logger.debug("Dropped opportunity without title: %r", raw)
        return None

    url = str(raw.get("url") or "").strip()
    if not url or not re.match(r"^https?://\S+$", url):
        logger.debug("Dropped opportunity without valid live URL: title=%r, url=%r", title, url)
        return None

    published = parse_date_safely(raw.get("published"))
    deadline = parse_date_safely(raw.get("deadline"))
    event_date = parse_date_safely(raw.get("event_date"))

    # Must have at least one date
    if not (published or deadline or event_date):
        logger.debug("Dropped opportunity with no date: title=%r", title)
        return None

    raw_id = raw.get("id")
    if raw_id and re.match(r"^[a-z0-9][a-z0-9-]*$", str(raw_id)):
        opp_id = str(raw_id)
    else:
        opp_id = slugify(f"{source}-{title}")

    # Determine type
    opp_type = raw.get("type")
    if isinstance(opp_type, OpportunityType):
        final_type = opp_type
    elif isinstance(opp_type, str) and opp_type in OpportunityType.__members__:
        final_type = OpportunityType(opp_type)
    else:
        final_type = default_type

    # Format
    opp_format = raw.get("format")
    final_format: Optional[OpportunityFormat] = None
    if isinstance(opp_format, OpportunityFormat):
        final_format = opp_format
    elif isinstance(opp_format, str) and opp_format in OpportunityFormat.__members__:
        final_format = OpportunityFormat(opp_format)

    # Clean topics (list of non-empty strings)
    topics_raw = raw.get("topics") or []
    topics: List[str] = [str(t).strip() for t in topics_raw if str(t).strip()]

    retrieved_at = parse_date_safely(raw.get("retrieved_at")) or date.today()

    try:
        return Opportunity(
            id=opp_id,
            type=final_type,
            title=title,
            url=url,
            source=source,
            published=published,
            deadline=deadline,
            event_date=event_date,
            format=final_format,
            audience=raw.get("audience"),
            eligibility_text=raw.get("eligibility_text"),
            topics=topics,
            retrieved_at=retrieved_at,
            is_simulated=is_simulated,
            cached_snapshot=cached_snapshot,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Opportunity failed validation and was dropped: %s. Data: %r", exc, raw)
        return None


class BaseMonitor:
    """Base class for public opportunity monitors."""

    source: str
    default_type: OpportunityType
    snapshot_path: Path

    def __init__(self, source: str, default_type: OpportunityType, snapshot_path: Path):
        self.source = source
        self.default_type = default_type
        self.snapshot_path = snapshot_path

    def load_cached_snapshot(self) -> List[Opportunity]:
        """Loads opportunities from local cached snapshot file."""
        if not self.snapshot_path.is_file():
            logger.warning("Snapshot file not found: %s", self.snapshot_path)
            return []

        with open(self.snapshot_path, encoding="utf-8") as f:
            raw_items = json.load(f)

        opportunities: List[Opportunity] = []
        for item in raw_items:
            opp = sanitize_opportunity_data(
                item,
                default_type=self.default_type,
                source=self.source,
                cached_snapshot=True,
                is_simulated=item.get("is_simulated", False),
            )
            if opp is not None:
                opportunities.append(opp)

        logger.info(
            "Loaded %d opportunities from %s snapshot (%s).",
            len(opportunities),
            self.source,
            self.snapshot_path.name,
        )
        return opportunities

    def fetch_url(self, url: str) -> Optional[str]:
        """Fetch remote URL with identifying user agent and timeout."""
        headers = {"User-Agent": config.USER_AGENT, "Accept": "application/json, text/xml, */*"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=config.REQUEST_TIMEOUT_SECONDS) as response:
                return response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning(
                "Live network fetch from %s (%s) failed (%s).",
                self.source,
                url,
                exc,
            )
            return None
