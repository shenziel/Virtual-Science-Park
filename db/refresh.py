"""Refresh opportunities from the monitors into SQLite. Owner: Backend 1.

    python -m db.refresh        # one refresh against DATABASE_URL

The API runs this at startup (before serving requests) unless
OPPORTUNITY_REFRESH=off, and BSP admins can trigger it with
POST /admin/opportunities/refresh.

Rules:
- Every item is validated against contracts.models.Opportunity; invalid ones are dropped.
- is_simulated and cached_snapshot are stored exactly as the monitors set them.
- Vinnova items from the monitors must be live: one they return marked
  cached_snapshot or is_simulated is dropped. There is never a fallback to the
  mock fixtures. If nothing live comes back, the failure is logged (see below
  for what is kept or loaded instead).
- If the monitors fail entirely, the result is empty and the failure is logged.
- The fetched set replaces all stored opportunities (seeded mock ones included),
  then every company is re-ranked against it.
- Except: when a source returns nothing (a timeout, an outage), its stored items
  are kept instead of deleted, so one slow request can't wipe the opportunities
  and every company's ranking. Only items that are live (not simulated, not a
  cached snapshot) and still current (deadline or event date not passed) are
  kept, and a warning is logged. A source that answers replaces its own items
  as before, so items gone at the source are still removed.
- If such a source has nothing stored either (e.g. a fresh database), its
  current items are loaded from the dated real snapshot fixtures/opportunities.json
  (written by db.ingest), labelled cached_snapshot so the UI shows the badge.
  Simulated items never come from it. OPPORTUNITY_FALLBACK=off turns this off.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from contracts.models import Opportunity, Profile, Recommendation, RefreshResult
from db import database

log = logging.getLogger("db.refresh")

VINNOVA_SOURCE = "Vinnova"
SNAPSHOT_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "opportunities.json"

FetchFn = Callable[[], Iterable[Any]]
FallbackFn = Callable[[], Iterable[Opportunity]]
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
        log.warning("live Vinnova fetch returned no calls; using stored items or the snapshot if any")
    return opps, result


def _still_current(opp: Opportunity, today: date) -> bool:
    if opp.deadline:
        return opp.deadline >= today
    if opp.event_date:
        return opp.event_date >= today
    return True


def keep_unanswered(previous: Iterable[Opportunity], fetched: Sequence[Opportunity],
                    today: date | None = None) -> list[Opportunity]:
    """Stored items worth keeping because their source returned nothing this time."""
    today = today or date.today()
    answered = {o.source for o in fetched}
    return [o for o in previous
            if o.source not in answered and not o.is_simulated and not o.cached_snapshot
            and _still_current(o, today)]


def load_snapshot() -> list[Opportunity]:
    """The real opportunities saved by db.ingest, relabelled as a cached snapshot.

    Empty when OPPORTUNITY_FALLBACK=off or the file is missing or unreadable.
    """
    if (os.environ.get("OPPORTUNITY_FALLBACK") or "on").strip().lower() == "off":
        return []
    try:
        raw = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("opportunity snapshot file is missing or unreadable; no fallback")
        return []
    snap = []
    for item in raw if isinstance(raw, list) else []:
        try:
            opp = Opportunity.model_validate(item)
        except ValidationError:
            continue
        if not opp.is_simulated:
            snap.append(opp.model_copy(update={"cached_snapshot": True}))
    return snap


def refresh_opportunities(
    conn: sqlite3.Connection,
    fetch_fn: FetchFn | None = None,
    match_fn: MatchFn | None = None,
    fallback_fn: FallbackFn | None = None,
) -> RefreshResult:
    """Collect from the monitors, store as the full opportunity set, re-rank every company."""
    opps, result = collect_opportunities(fetch_fn)
    kept = keep_unanswered(database.list_opportunities(conn), opps)
    if kept:
        result.kept = len(kept)
        sources = ", ".join(sorted({o.source for o in kept}))
        log.warning("kept %d stored opportunities from sources that returned nothing this time (%s)",
                    len(kept), sources)
        opps = opps + kept
    covered = {o.source for o in opps}
    ids = {o.id for o in opps}
    today = date.today()
    snapshot = [o for o in (fallback_fn or load_snapshot)()
                if o.source not in covered and o.id not in ids and not o.is_simulated
                and _still_current(o, today)]
    if snapshot:
        snapshot = [o.model_copy(update={"cached_snapshot": True}) for o in snapshot]
        result.from_snapshot = len(snapshot)
        log.warning("loaded %d opportunities from the dated cached snapshot (%s); their sources returned nothing",
                    len(snapshot), ", ".join(sorted({o.source for o in snapshot})))
        opps = opps + snapshot
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
