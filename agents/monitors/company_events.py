"""Discover dated public events on Blue Science Park member company websites."""
from __future__ import annotations

import json
import logging
import re
import urllib.robotparser
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from contracts.models import Opportunity, OpportunityType

from . import config
from .base import BaseMonitor, sanitize_opportunity_data, slugify

logger = logging.getLogger(__name__)
_EVENT_WORDS = re.compile(r"event|calendar|webinar|seminar|conference|workshop|meetup|agenda|eventkalender", re.I)
_FULL_DATE = re.compile(
    r"\b(?P<year>20\d{2})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})\b"
    r"|\b(?P<day2>\d{1,2})\s+(?P<month2>January|February|March|April|May|June|July|August|September|October|November|December|januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|december)\s+(?P<year2>20\d{2})\b",
    re.I,
)
_MONTHS = {name.lower(): i for i, names in enumerate((
    ("January", "januari"), ("February", "februari"), ("March", "mars"),
    ("April", "april"), ("May", "maj"), ("June", "juni"),
    ("July", "juli"), ("August", "augusti"), ("September", "september"),
    ("October", "oktober"), ("November", "november"), ("December", "december"),
), start=1) for name in names}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._href = ""
        self._anchor: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if tag == "a":
            self._href = attrs_map.get("href") or ""
            self._anchor = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor)))
            self._href = ""
            self._anchor = []

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.text.append(data.strip())
            if self._href:
                self._anchor.append(data.strip())


def _explicit_date(text: str) -> date | None:
    match = _FULL_DATE.search(text)
    if not match:
        return None
    try:
        if match.group("year"):
            return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
        return date(int(match.group("year2")), _MONTHS[match.group("month2").lower()], int(match.group("day2")))
    except (ValueError, KeyError):
        return None


class MemberCompanyEventsMonitor(BaseMonitor):
    """Fetch only public, robots-allowed event pages linked from member sites."""

    def __init__(self) -> None:
        super().__init__("Blue Science Park member companies", OpportunityType.event, config.BSP_EVENTS_SNAPSHOT_PATH)

    def _allowed_urls(self, homepage: str) -> set[str]:
        parsed = urlparse(homepage)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        raw = self.fetch_url(robots_url)
        if raw is None:
            logger.info("Skipping %s: robots.txt could not be checked.", parsed.netloc)
            return set()
        robots = urllib.robotparser.RobotFileParser(robots_url)
        robots.parse(raw.splitlines())
        return {homepage} if robots.can_fetch(config.USER_AGENT, homepage) else set()

    def _page_urls(self, homepage: str, html_text: str) -> list[str]:
        parser = _PageParser()
        parser.feed(html_text)
        host = urlparse(homepage).netloc.lower()
        candidates = []
        for href, label in parser.links:
            target = urljoin(homepage, href).split("#", 1)[0]
            parts = urlparse(target)
            if parts.scheme not in {"http", "https"} or parts.netloc.lower() != host:
                continue
            if _EVENT_WORDS.search(f"{parts.path} {label}") and target not in candidates:
                candidates.append(target)
        return candidates[: max(0, config.COMPANY_EVENT_MAX_PAGES - 1)]

    def fetch_opportunities(self, force_cache: bool = False) -> list[Opportunity]:
        if force_cache:
            return []
        try:
            companies = json.loads(config.MEMBER_COMPANIES_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load member company websites: %s", exc)
            return []

        results: list[Opportunity] = []
        seen: set[str] = set()
        for company in companies:
            name, homepage = str(company.get("name") or "").strip(), str(company.get("website") or "").strip()
            if not name or not homepage or not self._allowed_urls(homepage):
                continue
            home_html = self.fetch_url(homepage)
            if not home_html:
                continue
            parser = _PageParser()
            parser.feed(home_html)
            urls = [homepage, *self._page_urls(homepage, home_html)]
            for url in urls:
                if url in seen:
                    continue
                if url != homepage:
                    allowed = self._allowed_urls(url)
                    if not allowed:
                        # Check the target path against the same host robots rules.
                        continue
                page = home_html if url == homepage else self.fetch_url(url)
                if not page:
                    continue
                parsed = _PageParser()
                parsed.feed(page)
                text = " ".join(parsed.text)
                if url == homepage and not _EVENT_WORDS.search(text):
                    continue
                event_day = _explicit_date(text)
                title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
                title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", title_match.group(1))).strip() if title_match else ""
                if not title or not event_day or event_day < date.today():
                    continue
                opportunity = sanitize_opportunity_data(
                    {"id": slugify(f"{company.get('company_id', name)}-{title}"), "title": f"{name}: {title}",
                     "url": url, "event_date": event_day, "topics": [name, "event"]},
                    default_type=self.default_type, source=name, is_simulated=False,
                )
                if opportunity:
                    results.append(opportunity)
                    seen.add(url)
        return results
