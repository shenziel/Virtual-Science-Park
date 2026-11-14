"""Polite, cached page fetching for the profiler.

Rules from AGENTS.md §5 that this module enforces:

* an identifying ``User-Agent`` on every request;
* a delay between requests to the same host;
* ``robots.txt`` is obeyed — a disallowed URL raises and is never fetched;
* pages are cached on disk so the demo works offline, and the date a page was
  retrieved is stored next to it (a cached page keeps its original date);
* a page saved by hand is accepted as a ``cached snapshot`` and labelled.

Nothing here invents content: if a page cannot be fetched, this module raises.
A placeholder HTML page written on failure would turn a network error into fake
evidence, so there is none.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Mapping
from urllib import request
from urllib.parse import urlsplit

from . import config
from .paths import UnsafePathError, check_url, contained, readable_file

logger = logging.getLogger(__name__)

Transport = Callable[[str, str, float], tuple[str, bytes]]


class FetchError(RuntimeError):
    """The page could not be fetched and no cached copy exists."""


def _require_http_url(url: str) -> None:
    """Reject anything that is not an http(s) URL before it is used.

    ``urllib`` would happily read ``file:///etc/passwd``, so the scheme check is
    what keeps a URL from a model answer or a command line out of the filesystem.
    """
    try:
        check_url(url)
    except UnsafePathError as exc:
        raise FetchError(str(exc)) from exc


class RobotsDenied(FetchError):
    """``robots.txt`` disallows fetching this URL."""


@dataclass(frozen=True)
class SourcePage:
    """A page the profiler may quote.

    ``cached`` is True when the HTML came from the on-disk cache or from a page
    saved by hand. Every claim made from such a page is flagged
    ``cached_snapshot=True`` so the UI can show a badge.
    """

    url: str
    html: str
    retrieved_at: date
    cached: bool
    note: str = ""


def http_transport(url: str, user_agent: str, timeout: float) -> tuple[str, bytes]:
    """Default transport: a single GET, no cookies, no login, no paywall."""
    req = request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 (https only)
        return response.geturl(), response.read(config.MAX_PAGE_BYTES)


class CachedFetcher:
    """Fetches pages once, then serves them from ``PAGE_CACHE_DIR``."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        user_agent: str | None = None,
        min_interval: float | None = None,
        timeout: float | None = None,
        transport: Transport | None = None,
        today: Callable[[], date] = date.today,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = Path(cache_dir or config.PAGE_CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent or config.USER_AGENT
        self.min_interval = (
            config.MIN_REQUEST_INTERVAL_SECONDS if min_interval is None else min_interval
        )
        self.timeout = config.REQUEST_TIMEOUT_SECONDS if timeout is None else timeout
        self.transport = transport or http_transport
        self.today = today
        self.clock = clock
        self.sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, object] = {}

    # -- public ------------------------------------------------------------

    def fetch(self, url: str) -> SourcePage:
        """Return the page, from cache when possible.

        Raises ``RobotsDenied`` or ``FetchError`` and never fabricates content.
        ``url`` is untrusted (it can come from a model or the command line), so
        it is checked before it reaches the transport or the cache.
        """
        _require_http_url(url)
        html_path, meta_path = self._paths(url)
        if html_path.exists():
            return SourcePage(
                url=url,
                html=html_path.read_text(encoding="utf-8"),
                retrieved_at=self._cached_date(meta_path),
                cached=True,
                note="cached snapshot",
            )

        if not self._robots_allows(url):
            raise RobotsDenied(f"robots.txt disallows fetching {url}")

        self._throttle(url)
        try:
            final_url, body = self.transport(url, self.user_agent, self.timeout)
        except Exception as exc:  # noqa: BLE001 - reported, not hidden
            raise FetchError(f"could not fetch {url}: {exc}") from exc

        html = body.decode("utf-8", errors="replace")
        retrieved_at = self.today()
        html_path.write_text(html, encoding="utf-8")
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "final_url": final_url,
                    "retrieved_at": retrieved_at.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        logger.info("Fetched %s (%d chars)", url, len(html))
        return SourcePage(url=url, html=html, retrieved_at=retrieved_at, cached=False)

    def load_snapshot(self, url: str, path: str | Path) -> SourcePage:
        """Use HTML saved by hand (a site that blocks scraping or is all JavaScript).

        ``path`` is named explicitly by the operator, so it is not joined to the
        cache; it is resolved and must be a regular file. The snapshot is always
        labelled as cached.
        """
        _require_http_url(url)
        try:
            snapshot = readable_file(path)
        except UnsafePathError as exc:
            raise FetchError(str(exc)) from exc
        html = snapshot.read_text(encoding="utf-8", errors="replace")
        return SourcePage(
            url=url,
            html=html,
            retrieved_at=self.today(),
            cached=True,
            note=f"cached snapshot from {snapshot.name}",
        )

    # -- internals ---------------------------------------------------------

    def _paths(self, url: str) -> tuple[Path, Path]:
        """Cache paths for a URL: a hash plus a containment check, never the URL."""
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        try:
            return (
                contained(self.cache_dir, f"{digest}.html"),
                contained(self.cache_dir, f"{digest}.json"),
            )
        except UnsafePathError as exc:  # pragma: no cover - defensive
            raise FetchError(str(exc)) from exc

    def _cached_date(self, meta_path: Path) -> date:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return date.fromisoformat(meta["retrieved_at"])
        except (OSError, ValueError, KeyError, TypeError):
            # Cache written before dates were recorded: the honest answer is
            # today, and the page is labelled as cached either way.
            return self.today()

    def _throttle(self, url: str) -> None:
        if self.min_interval <= 0:
            return
        host = urlsplit(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (self.clock() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = self.clock()

    def _robots_allows(self, url: str) -> bool:
        from urllib import robotparser

        # fetch() already checked this; repeating it keeps the method safe on its
        # own and means the robots URL is built from a validated scheme and host.
        parts = check_url(url)
        host = parts.netloc
        parser = self._robots.get(host)
        if parser is None:
            parser = robotparser.RobotFileParser()
            robots_url = f"{parts.scheme.lower()}://{host}/robots.txt"
            try:
                self._throttle(robots_url)
                _, body = self.transport(robots_url, self.user_agent, self.timeout)
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
            except Exception as exc:  # noqa: BLE001
                # No robots.txt (or it is unreachable) means no restrictions.
                logger.info("robots.txt unavailable for %s (%s); assuming allowed", host, exc)
                parser.parse([])
            self._robots[host] = parser
        return bool(parser.can_fetch(self.user_agent, url))  # type: ignore[attr-defined]


def source_note(page: SourcePage) -> Mapping[str, object]:
    """Small dict for logs and the README, not part of any contract."""
    return {
        "url": page.url,
        "retrieved_at": page.retrieved_at.isoformat(),
        "cached": page.cached,
        "note": page.note,
    }
