"""Run the agents on the real companies and write the results to fixtures/. Owner: Backend 1.

    python -m db.ingest                       # all companies, all agents
    python -m db.ingest --only cleura         # one company (others keep their files)
    python -m db.ingest --html cmarine=pages/cmarine.html   # hand-saved page
    python -m db.ingest --skip-profiler       # reuse saved profiles, refresh the rest
    python -m db.ingest --dry-run             # validate and report, write nothing
    python -m db.ingest --seed                # also load the result into the database

Pipeline: fixtures/companies.json -> profiler -> monitors -> matcher ->
validate against contracts.models -> fixtures/profiles/<id>.json,
opportunities.json, recommendations.json.

The agents only return contract objects; this module is the only writer of
fixtures/. Everything is validated before anything is written, and each file
is written atomically, so a failed run never leaves fixtures/ half-updated.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from contracts.models import Opportunity, Profile, Recommendation
from fixtures.loader import FIXTURES, MOCK

log = logging.getLogger("db.ingest")

# The agents, as plain functions, so tests can pass fakes.
ProfileFn = Callable[[dict, Profile | None, Path | None], Profile]
FetchFn = Callable[[], list[Opportunity]]
MatchFn = Callable[[Profile, Sequence[Opportunity]], list[Recommendation]]


class IngestError(RuntimeError):
    pass


@dataclass
class Report:
    profiled: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    opportunities: int = 0
    recommendations: int = 0
    written: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"profiled: {', '.join(self.profiled) or '-'}",
            f"reused previous profile: {', '.join(self.reused) or '-'}",
            f"opportunities: {self.opportunities}, recommendations: {self.recommendations}",
        ]
        lines += [f"FAILED {cid}: {why}" for cid, why in self.failed.items()]
        lines.append(f"written: {', '.join(self.written) or 'nothing'}")
        return "\n".join(lines)


# ----------------------------------------------------------------- agents


def default_profile_fn() -> ProfileFn:
    from agents.profiler.profiler import ProfilerAgent

    agent = ProfilerAgent()

    def run(company: dict, existing: Profile | None, html: Path | None) -> Profile:
        if html is not None:
            return agent.profile_from_snapshot(
                company["company_id"], company["name"], company["website"], html, existing=existing
            )
        return agent.profile_company(
            company["company_id"], company["name"], company["website"], existing=existing
        )

    return run


def default_fetch_fn() -> FetchFn:
    """The monitors, through the same validation and live-Vinnova rules as the API refresh."""
    from db.refresh import collect_opportunities

    return lambda: collect_opportunities()[0]


def default_match_fn() -> MatchFn:
    from agents.matcher import match

    return match


# ------------------------------------------------------------------- I/O


def load_companies(path: Path) -> list[dict]:
    companies = json.loads(path.read_text(encoding="utf-8"))
    for c in companies:
        missing = {"company_id", "name", "website"} - set(c)
        if missing:
            raise IngestError(f"{path}: entry {c!r} is missing {sorted(missing)}")
    return companies


def _read_model(path: Path, model: type[BaseModel]):
    return model.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _dump(models: Sequence[BaseModel]) -> str:
    return json.dumps([m.model_dump(mode="json") for m in models], indent=2, ensure_ascii=False) + "\n"


# ------------------------------------------------------------------ checks


def check_consistency(profiles: dict[str, Profile], opps: list[Opportunity], recs: list[Recommendation]) -> None:
    """Cross-references the contracts can't check one object at a time."""
    opp_ids = [o.id for o in opps]
    if len(opp_ids) != len(set(opp_ids)):
        raise IngestError("duplicate opportunity ids from the monitors")
    for r in recs:
        if r.company_id not in profiles:
            raise IngestError(f"recommendation for unknown company {r.company_id!r}")
        if r.opportunity_id not in set(opp_ids):
            raise IngestError(f"recommendation points to unknown opportunity {r.opportunity_id!r}")
        unknown = set(r.matched_claims) - {c.id for c in profiles[r.company_id].claims}
        if unknown:
            raise IngestError(f"{r.company_id}/{r.opportunity_id} cites unknown claims {sorted(unknown)}")


# --------------------------------------------------------------- pipeline


def run_ingest(
    out_dir: Path = FIXTURES,
    *,
    only: set[str] | None = None,
    html: dict[str, Path] | None = None,
    skip_profiler: bool = False,
    skip_monitors: bool = False,
    dry_run: bool = False,
    profile_fn: ProfileFn | None = None,
    fetch_fn: FetchFn | None = None,
    match_fn: MatchFn | None = None,
) -> Report:
    out_dir = Path(out_dir).resolve()
    if out_dir == MOCK.resolve() or MOCK.resolve() in out_dir.parents:
        raise IngestError("refusing to write agent output into fixtures/mock (simulated data only)")
    html = html or {}
    report = Report()

    companies = load_companies(out_dir / "companies.json")
    known = {c["company_id"] for c in companies}
    for name, wanted in (("--only", only or set()), ("--html", set(html))):
        if wanted - known:
            raise IngestError(f"{name} names unknown companies: {sorted(wanted - known)}")

    # 1. profiles: fresh for the selected companies, previous file for the rest
    profiles: dict[str, Profile] = {}
    run_profiler = None if skip_profiler else (profile_fn or default_profile_fn())
    for company in companies:
        cid = company["company_id"]
        previous = _read_model(out_dir / "profiles" / f"{cid}.json", Profile)
        if run_profiler is None or (only and cid not in only):
            if previous is not None:
                profiles[cid] = previous
                report.reused.append(cid)
            continue
        try:
            profile = Profile.model_validate(run_profiler(company, previous, html.get(cid)).model_dump())
            if profile.company_id != cid:
                raise IngestError(f"profiler returned company_id {profile.company_id!r}")
            profiles[cid] = profile
            report.profiled.append(cid)
        except Exception as exc:  # noqa: BLE001 - one company must not stop the others
            report.failed[cid] = f"{type(exc).__name__}: {exc}"
            if previous is not None:
                profiles[cid] = previous
                report.reused.append(cid)

    # 2. opportunities
    opps_path = out_dir / "opportunities.json"
    if skip_monitors:
        opps = [Opportunity.model_validate(o) for o in json.loads(opps_path.read_text(encoding="utf-8"))] if opps_path.exists() else []
    else:
        opps = [Opportunity.model_validate(o.model_dump()) for o in (fetch_fn or default_fetch_fn())()]
    opps.sort(key=lambda o: o.id)
    report.opportunities = len(opps)

    # 3. recommendations for every company we have a profile for
    matcher = match_fn or default_match_fn()
    recs: list[Recommendation] = []
    for cid in sorted(profiles):
        ranked = [Recommendation.model_validate(r.model_dump()) for r in matcher(profiles[cid], opps)]
        recs += sorted(ranked, key=lambda r: (-r.score, r.opportunity_id))
    report.recommendations = len(recs)

    # 4. validate everything together, then write
    check_consistency(profiles, opps, recs)
    if dry_run:
        return report
    for cid in report.profiled:
        _write_atomic(out_dir / "profiles" / f"{cid}.json", profiles[cid].model_dump_json(indent=2) + "\n")
        report.written.append(f"profiles/{cid}.json")
    if not skip_monitors:
        _write_atomic(opps_path, _dump(opps))
        report.written.append("opportunities.json")
    _write_atomic(out_dir / "recommendations.json", _dump(recs))
    report.written.append("recommendations.json")
    return report


# -------------------------------------------------------------------- CLI


def _parse_html(values: list[str]) -> dict[str, Path]:
    out = {}
    for v in values:
        cid, sep, path = v.partition("=")
        if not sep or not cid or not path:
            raise SystemExit(f"--html expects company_id=path, got {v!r}")
        out[cid] = Path(path)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the agents and write fixtures/ (Backend 1).")
    p.add_argument("--out", default=str(FIXTURES), help="seed folder to write (default: fixtures)")
    p.add_argument("--only", nargs="+", metavar="COMPANY_ID", help="profile only these companies")
    p.add_argument("--html", action="append", default=[], metavar="ID=PATH", help="hand-saved page for a company")
    p.add_argument("--skip-profiler", action="store_true", help="reuse saved profiles")
    p.add_argument("--skip-monitors", action="store_true", help="reuse saved opportunities")
    p.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    p.add_argument("--seed", action="store_true", help="also load the result into the database")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        report = run_ingest(
            Path(args.out),
            only=set(args.only) if args.only else None,
            html=_parse_html(args.html),
            skip_profiler=args.skip_profiler,
            skip_monitors=args.skip_monitors,
            dry_run=args.dry_run,
        )
    except IngestError as exc:
        print(f"ingest failed, nothing written: {exc}", file=sys.stderr)
        return 2
    print(report.summary())

    if args.seed and not args.dry_run:
        from db import database
        from db.seed import seed_db

        conn = database.connect()
        try:
            counts = seed_db(conn, args.out)
        finally:
            conn.close()
        print("seeded", ", ".join(f"{v} {k}" for k, v in counts.items()))
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
