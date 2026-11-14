"""Profiler agent — builds a contract-valid ``Profile`` for one company.

Pipeline:

1. fetch the company's official website (cached, robots.txt-aware, rate-limited);
2. extract claims with the LLM prompt, or with the deterministic signals;
3. check every claim against the page (verbatim quotes, allowed fields, evidence);
4. list every profile area it could not support in ``missing_fields``;
5. keep ``user_confirmed`` claims from a previous run, never overwrite them;
6. validate as ``contracts.models.Profile`` and cache the result for offline use.

Usage (validates, caches and prints the profile):

    python -m agents.profiler.profiler \\
        --company-id acme --name "Acme AB" --website https://acme.se

Use ``--html`` for a page saved by hand (the claims are labelled
``cached_snapshot``). ``--out`` writes the JSON somewhere else, e.g. for
Backend 1 to drop into ``fixtures/profiles/``.

Owner: Backend 2. Edits nothing outside ``agents/profiler/``.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from contracts.models import Claim, ClaimKind, Profile, Visibility

from . import config
from .extract import ExtractionError, ExtractionResult, Extractor
from .fetch import CachedFetcher, FetchError, SourcePage
from .llm import default_client
from .paths import UnsafePathError, check_url, contained, readable_file, writable_file

logger = logging.getLogger(__name__)

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ProfilerAgent:
    """Profiles one company at a time. Stateless between runs except for caches."""

    def __init__(
        self,
        llm=None,
        fetcher: CachedFetcher | None = None,
        extractor: Extractor | None = None,
        cache_dir: Path | None = None,
        fallback_on_llm_error: bool = True,
    ) -> None:
        self.llm = llm if llm is not None else default_client()
        self.cache_dir = Path(cache_dir or config.CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fetcher = fetcher or CachedFetcher()
        self.extractor = extractor or Extractor(llm=self.llm)
        self.fallback_on_llm_error = fallback_on_llm_error

    # -- public ------------------------------------------------------------

    def profile_company(
        self,
        company_id: str,
        name: str,
        website: str,
        html_content: str | None = None,
        existing: Profile | None = None,
        retrieved_at: date | None = None,
        is_simulated: bool = False,
    ) -> Profile:
        """Profile a company and return a validated ``Profile``.

        ``html_content`` is for a page saved by hand: it is treated as a cached
        snapshot. ``existing`` is the profile from a previous run — its
        ``user_confirmed`` claims survive.
        """
        _check_slug(company_id)
        _check_url(website)
        if not name.strip():
            raise ValueError("company name must not be empty")

        if html_content is not None:
            page = SourcePage(
                url=website,
                html=html_content,
                retrieved_at=retrieved_at or date.today(),
                cached=True,
                note="cached snapshot (supplied HTML)",
            )
        else:
            page = self.fetcher.fetch(website)
            if retrieved_at is not None:
                page = SourcePage(
                    url=page.url,
                    html=page.html,
                    retrieved_at=retrieved_at,
                    cached=page.cached,
                    note=page.note,
                )

        return self._build(
            company_id=company_id,
            name=name,
            website=website,
            page=page,
            existing=existing,
            is_simulated=is_simulated,
        )

    def profile_from_snapshot(
        self,
        company_id: str,
        name: str,
        website: str,
        path: str | Path,
        existing: Profile | None = None,
    ) -> Profile:
        """Profile from an HTML file saved by hand (site blocks scraping or is JS-only)."""
        _check_slug(company_id)
        _check_url(website)
        page = self.fetcher.load_snapshot(website, path)
        return self._build(
            company_id=company_id,
            name=name,
            website=website,
            page=page,
            existing=existing,
            is_simulated=False,
        )

    def save(self, profile: Profile) -> Path:
        """Validate once more, then cache the profile so the demo works offline.

        The file name comes from the validated ``company_id`` (a slug) and is
        then checked to be inside the cache directory, so it cannot escape it.
        """
        validated = Profile.model_validate(profile.model_dump())
        path = contained(self.cache_dir, f"{validated.company_id}.json")
        path.write_text(validated.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, company_id: str) -> Profile | None:
        """Return the cached profile for a company, validated, or ``None``.

        ``company_id`` may come from a request body, so a value such as
        ``../../etc/passwd`` must fail validation instead of naming a file.
        """
        _check_slug(company_id)
        path = contained(self.cache_dir, f"{company_id}.json")
        if not path.exists():
            return None
        return Profile.model_validate_json(path.read_text(encoding="utf-8"))

    # -- internals ---------------------------------------------------------

    def _build(
        self,
        company_id: str,
        name: str,
        website: str,
        page: SourcePage,
        existing: Profile | None,
        is_simulated: bool,
    ) -> Profile:
        result = self._extract(page, name)
        claims = _merge_with_confirmed(existing, result.claims)
        covered = {c.field for c in claims}

        profile = Profile(
            company_id=company_id,
            name=name.strip(),
            website=website,
            visibility=_kept_visibility(existing),
            is_simulated=is_simulated,
            updated_at=datetime.now(timezone.utc),
            claims=claims,
            missing_fields=[f for f in result.missing_fields if f not in covered],
        )
        logger.info(
            "Profiled %s: %d claims (%d stated), %d missing fields, source %s",
            company_id,
            len(profile.claims),
            sum(1 for c in profile.claims if c.kind == ClaimKind.stated),
            len(profile.missing_fields),
            "cache" if page.cached else "live",
        )
        return profile

    def _extract(self, page: SourcePage, name: str) -> ExtractionResult:
        try:
            return self.extractor.extract(page, name)
        except ExtractionError as exc:
            if not self.fallback_on_llm_error:
                raise
            logger.error(
                "LLM extraction failed for %s (%s); using the deterministic extractor.",
                page.url,
                exc,
            )
            return Extractor(llm=None).extract(page, name)


# -- helpers ---------------------------------------------------------------


def _check_slug(company_id: str) -> None:
    if not _SLUG.match(company_id or ""):
        raise ValueError(f"company_id must match {_SLUG.pattern}: {company_id!r}")


def _check_url(url: str) -> None:
    """Reject anything but an http(s) URL with a host."""
    try:
        check_url(url)
    except UnsafePathError as exc:
        raise ValueError(f"website must be an http(s) URL: {url!r}") from exc


def _kept_visibility(existing: Profile | None) -> Visibility:
    """A re-run must not un-publish a profile the company chose to publish."""
    return existing.visibility if existing is not None else Visibility.private


def _merge_with_confirmed(existing: Profile | None, new_claims: list[Claim]) -> list[Claim]:
    """Keep every ``user_confirmed`` claim; a new claim never reuses its id."""
    if existing is None:
        return list(new_claims)
    confirmed = [c for c in existing.claims if c.kind == ClaimKind.user_confirmed]
    taken = {c.id for c in confirmed}
    return confirmed + [c for c in new_claims if c.id not in taken]


# -- CLI -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Profile a company from its website.")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--website", required=True)
    parser.add_argument("--html", help="hand-saved HTML file, used as a cached snapshot")
    parser.add_argument("--existing", help="previous profile JSON, keeps user_confirmed claims")
    parser.add_argument("--out", help="write the profile here instead of stdout")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    agent = ProfilerAgent()
    try:
        existing = None
        if args.existing:
            source = readable_file(args.existing)
            existing = Profile.model_validate_json(source.read_text(encoding="utf-8"))
        html_path = readable_file(args.html) if args.html else None

        if html_path:
            profile = agent.profile_from_snapshot(
                args.company_id, args.name, args.website, html_path, existing=existing
            )
        else:
            profile = agent.profile_company(
                args.company_id, args.name, args.website, existing=existing
            )

        path = agent.save(profile)
        payload = profile.model_dump_json(indent=2)
        if args.out:
            target = writable_file(args.out)
            target.write_text(payload, encoding="utf-8")
            print(f"wrote {target}", file=sys.stderr)
        else:
            print(payload)
    except (ValueError, OSError, FetchError, ExtractionError) as exc:
        # A bad URL or path is an operator mistake, not a crash: say what is
        # wrong and exit non-zero without a traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"cached {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
