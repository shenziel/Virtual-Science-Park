"""
Funding Monitor: Vinnova calls.
Owner: Backend 3 (agents/monitors/)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
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
        """Parse normalized records (used for fixtures and direct feed inputs)."""
        try:
            data = json.loads(text)
            items = data if isinstance(data, list) else data.get("utlysningar", [])
            return self.parse_feed(items, cached_snapshot=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse normalized Vinnova response (%s).", exc)
            return []

    @staticmethod
    def _as_items(text: str, key: str) -> List[dict[str, Any]]:
        """Decode one documented Vinnova API list response."""
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get(key), list):
            return [item for item in payload[key] if isinstance(item, dict)]
        return []

    def parse_api_responses(self, calls_text: str, rounds_text: str) -> List[Opportunity]:
        """Join Vinnova's public calls and application rounds from the live API."""
        calls = self._as_items(calls_text, "utlysningar")
        rounds = self._as_items(rounds_text, "ansokningsomgangar")
        if not calls or not rounds:
            return []

        calls_by_id = {
            str(call.get("Diarienummer", "")).strip(): call
            for call in calls
            if call.get("Diarienummer")
        }
        today = date.today()
        opportunities: List[Opportunity] = []

        for round_item in rounds:
            if round_item.get("Publik") not in (1, "1", True):
                continue
            call_id = str(round_item.get("DiarienummerUtlysning", "")).strip()
            call = calls_by_id.get(call_id)
            if not call or call.get("Publik") not in (1, "1", True):
                continue

            deadline = round_item.get("Stangningsdatum")
            parsed_deadline = sanitize_opportunity_data(
                {
                    "id": re.sub(
                        r"[^a-z0-9-]+",
                        "-",
                        str(round_item.get("Diarienummer", "")).lower(),
                    ).strip("-"),
                    "title": (
                        round_item.get("TitelEngelska")
                        or round_item.get("Titel")
                        or call.get("TitelEngelska")
                        or call.get("Titel")
                    ),
                    "url": f"https://data.vinnova.se/api/ansokningsomgangar/{round_item.get('Diarienummer')}",
                    "published": call.get("Publiceringsdatum"),
                    "deadline": deadline,
                    "audience": self._eligibility_text(round_item),
                    "eligibility_text": self._eligibility_text(round_item),
                    "topics": [
                        value.strip()
                        for value in (
                            round_item.get("TitelEngelska") or round_item.get("Titel"),
                            call.get("BeskrivningEngelska") or call.get("Beskrivning"),
                        )
                        if isinstance(value, str) and value.strip()
                    ],
                },
                default_type=self.default_type,
                source=self.source,
                cached_snapshot=False,
                is_simulated=False,
            )
            # Funding discovery is for actionable rounds. Do not turn closed
            # calls into opportunities just because their publication date exists.
            if parsed_deadline and parsed_deadline.deadline and parsed_deadline.deadline >= today:
                opportunities.append(parsed_deadline)

        return opportunities

    @staticmethod
    def _eligibility_text(round_item: dict[str, Any]) -> str | None:
        """Read the public audience text (Vinnovas WebTextLista item 2)."""
        texts = round_item.get("WebTextLista") or []
        for item in texts:
            if not isinstance(item, dict) or str(item.get("TextID", "")) != "2":
                continue
            value = item.get("TextEn") or item.get("TextSv")
            return value.strip() if isinstance(value, str) and value.strip() else None
        return None

    def fetch_opportunities(self, force_cache: bool = False) -> List[Opportunity]:
        """
        Fetch real calls and their application rounds from Vinnova's public API.
        Missing or invalid live data produces an empty result; never substitute mock data.
        """
        if force_cache:
            return self.load_cached_snapshot()

        calls_url = f"{config.VINNOVA_API_URL}/{config.VINNOVA_UPDATED_SINCE}"
        rounds_url = f"{config.VINNOVA_ROUNDS_API_URL}/{config.VINNOVA_UPDATED_SINCE}"
        calls_text = self.fetch_url(calls_url)
        rounds_text = self.fetch_url(rounds_url)
        if not calls_text or not rounds_text:
            return []
        return self.parse_api_responses(calls_text, rounds_text)
