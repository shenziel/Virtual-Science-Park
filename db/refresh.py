"""Refresh opportunities from the monitors into SQLite. Owner: Backend 1.

    python -m db.refresh        # one refresh against DATABASE_URL

The API runs this at startup (before serving requests) unless
OPPORTUNITY_REFRESH=off, and BSP admins can trigger it with
POST /admin/opportunities/refresh.

Rules:
- Every item is validated against contracts.models.Opportunity; invalid ones are dropped.
- is_simulated and cached_snapshot are stored exactly as the monitors set them.
- Vinnova must be live: a Vinnova item marked cached_snapshot or is_simulated is
  dropped. There is no fallback to mock fixtures or snapshots for Vinnova. If
  nothing live comes back, Vinnova stays empty and the failure is logged.
- If the monitors fail entirely, the result is empty and the failure is logged.
- The fetched set replaces all stored opportunities (seeded mock ones included),
  then every company is re-ranked against it.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from contracts.models import Opportunity, Profile, Recommendation, RefreshResult
from db import database

log = logging.getLogger("db.refresh")

VINNOVA_SOURCE = "Vinnova"

FetchFn = Callable[[], Iterable[Any]]
MatchFn = Callable[[Profile, Sequence[Opportunity]], list[Recommendation]]


def _default_fetch() -> list[Any]:
    from agents.monitors import fetch_all_opportunities  # looked up per call (tests patch it)

    return fetch_all_opportunities()


def _default_match(profile: Profile, opps: Sequence[Opportunity]) -> list[Recommendation]:
    from agents.matcher import match

    return match(profile, opps)


def collect_opportunities(fetch_fn: FetchFn | None = None) -> tuple[list[Opportunity], RefreshResult]:
    """Fetch, validate and filter. Never raises for monitor failures."""
    result = RefreshResult()
    try:
        raw = list((fetch_fn or _default_fetch)())
    except Exception:  # noqa: BLE001 - a broken source must not take the API down
        log.exception("monitor fetch failed; opportunities stay empty (no fallback to mock data)")
        result.failed = True
        raw = []

    opps: list[Opportunity] = []
    seen: set[str] = set()
    for item in raw:
        try:
            data = item.model_dump() if isinstance(item, BaseModel) else item
            opp = Opportunity.model_validate(data)
        except ValidationError:
            result.dropped_invalid += 1
            continue
        if opp.source == VINNOVA_SOURCE and (opp.cached_snapshot or opp.is_simulated):
            result.dropped_vinnova_not_live += 1
            continue
        if opp.id in seen:
            result.dropped_duplicate += 1
            continue
        seen.add(opp.id)
        opps.append(opp)

    result.fetched = len(raw)
    result.vinnova = sum(o.source == VINNOVA_SOURCE for o in opps)
    result.stored = len(opps)
    if result.dropped_invalid:
        log.warning("dropped %d opportunities that failed contract validation", result.dropped_invalid)
    if result.dropped_vinnova_not_live:
        log.warning("dropped %d Vinnova items that were not live (snapshot or simulated)",
                    result.dropped_vinnova_not_live)
    if result.vinnova == 0:
        log.warning("live Vinnova fetch returned no calls; Vinnova results stay empty")
    return opps, result


def refresh_opportunities(
    conn: sqlite3.Connection,
    fetch_fn: FetchFn | None = None,
    match_fn: MatchFn | None = None,
) -> RefreshResult:
    """Collect from the monitors, store as the full opportunity set, re-rank every company."""
    opps, result = collect_opportunities(fetch_fn)
    result.removed = database.replace_opportunities(conn, opps)
    matcher = match_fn or _default_match
    for company in database.list_companies(conn):
        cid = company["company_id"]
        try:
            database.replace_recommendations(conn, cid, matcher(database.get_profile(conn, cid), opps))
            result.rematched.append(cid)
        except Exception:  # noqa: BLE001 - one company must not block the others
            log.exception("re-ranking %s after the opportunity refresh failed", cid)
            result.rematch_failed.append(cid)
    log.info("opportunity refresh: %s", result.model_dump())
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    conn = database.connect()
    try:
        database.init_db(conn)
        result = refresh_opportunities(conn)
    finally:
        conn.close()
    print(result.model_dump_json(indent=2))
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
