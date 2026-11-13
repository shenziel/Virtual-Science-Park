"""Load and validate a seed-data folder. Owner: Backend 1.

A seed folder has this layout (see fixtures/README.md):
    profiles/<company_id>.json, opportunities.json, recommendations.json, users.json

The API loads the folder named by the SEED_DIR environment variable
(default: fixtures). Set SEED_DIR=fixtures/mock to use the mock data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from contracts.models import Opportunity, Profile, Recommendation

FIXTURES = Path(__file__).resolve().parent
MOCK = FIXTURES / "mock"


@dataclass(frozen=True)
class Seed:
    profiles: dict[str, Profile]
    opportunities: dict[str, Opportunity]
    recommendations: list[Recommendation]
    users: list[dict]  # User fields + plaintext throwaway "password"; hash before storing


def _read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_seed(folder: Path | str | None = None) -> Seed:
    folder = Path(folder or os.environ.get("SEED_DIR") or FIXTURES)
    profiles = {}
    for f in sorted((folder / "profiles").glob("*.json")):
        p = Profile(**_read(f, {}))
        if p.company_id != f.stem:
            raise ValueError(f"{f}: company_id {p.company_id!r} must match the file name")
        profiles[p.company_id] = p
    opps_raw = _read(folder / "opportunities.json", [])
    opportunities = {o.id: o for o in (Opportunity(**o) for o in opps_raw)}
    if len(opportunities) != len(opps_raw):
        raise ValueError(f"{folder}: duplicate opportunity ids")
    recommendations = [Recommendation(**r) for r in _read(folder / "recommendations.json", [])]
    users = _read(folder / "users.json", [])
    return Seed(profiles, opportunities, recommendations, users)
