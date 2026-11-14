"""SQLite access layer. Owner: Backend 1.

Every read returns contract models from `contracts.models`, and every write
validates through them first, so the database never holds an off-contract row.
Permission checks are NOT done here: `api/` checks the session before calling.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from contracts.models import (
    Claim,
    ClaimKind,
    FeedbackVerdict,
    Opportunity,
    Profile,
    ProfileField,
    Recommendation,
    Role,
    User,
    Visibility,
)

SCHEMA = Path(__file__).with_name("schema.sql")
DEFAULT_URL = "sqlite:///vsp.db"


def db_path(url: str | None = None) -> str:
    """`sqlite:////data/vsp.db` -> `/data/vsp.db`; `sqlite:///vsp.db` -> `vsp.db`; `:memory:` stays."""
    url = url or os.environ.get("DATABASE_URL") or DEFAULT_URL
    if url == ":memory:":
        return url
    if not url.startswith("sqlite:///"):
        raise ValueError(f"only sqlite:/// URLs are supported, got {url!r}")
    return url.removeprefix("sqlite:///")


def connect(url: str | None = None) -> sqlite3.Connection:
    path = db_path(url)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class NotFound(LookupError):
    pass


# ------------------------------------------------------------------ profiles


def _claim_from_row(r: sqlite3.Row) -> Claim:
    return Claim(
        id=r["id"], field=r["field"], value=r["value"], kind=r["kind"],
        evidence_url=r["evidence_url"], snippet=r["snippet"], retrieved_at=r["retrieved_at"],
        confidence=r["confidence"], cached_snapshot=bool(r["cached_snapshot"]),
    )


def _insert_claim(conn: sqlite3.Connection, company_id: str, c: Claim, position: int) -> None:
    conn.execute(
        "INSERT INTO claims (company_id, id, field, value, kind, evidence_url, snippet,"
        " retrieved_at, confidence, cached_snapshot, position) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (company_id, c.id, c.field.value, c.value, c.kind.value, c.evidence_url, c.snippet,
         c.retrieved_at.isoformat(), c.confidence, int(c.cached_snapshot), position),
    )


def upsert_profile(conn: sqlite3.Connection, profile: Profile) -> Profile:
    """Save agent output for a company.

    - user_confirmed claims already stored are kept, and win over agent claims with the same id.
    - An existing company keeps its visibility; a new one starts with the profile's (default private).
    """
    profile = Profile.model_validate(profile.model_dump())
    cid = profile.company_id
    with conn:
        existing = conn.execute("SELECT visibility FROM companies WHERE company_id=?", (cid,)).fetchone()
        kept = [
            _claim_from_row(r)
            for r in conn.execute(
                "SELECT * FROM claims WHERE company_id=? AND kind=? ORDER BY position",
                (cid, ClaimKind.user_confirmed.value),
            )
        ]
        kept_ids = {c.id for c in kept}
        claims = [c for c in profile.claims if c.id not in kept_ids] + kept
        covered = {c.field for c in claims}
        missing = [f for f in profile.missing_fields if f not in covered]
        visibility = existing["visibility"] if existing else profile.visibility.value
        merged = profile.model_copy(update={
            "claims": claims, "missing_fields": missing,
            "visibility": Visibility(visibility), "updated_at": datetime.now(timezone.utc),
        })
        Profile.model_validate(merged.model_dump())  # still on contract after merging

        conn.execute(
            "INSERT INTO companies (company_id, name, website, visibility, is_simulated, updated_at, missing_fields)"
            " VALUES (?,?,?,?,?,?,?) ON CONFLICT(company_id) DO UPDATE SET name=excluded.name,"
            " website=excluded.website, is_simulated=excluded.is_simulated,"
            " updated_at=excluded.updated_at, missing_fields=excluded.missing_fields",
            (cid, merged.name, merged.website, visibility, int(merged.is_simulated),
             merged.updated_at.isoformat(timespec="seconds"), json.dumps([f.value for f in missing])),
        )
        conn.execute("DELETE FROM claims WHERE company_id=?", (cid,))
        for i, c in enumerate(claims):
            _insert_claim(conn, cid, c, i)
    return get_profile(conn, cid)


def list_companies(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT company_id, name, visibility, is_simulated FROM companies ORDER BY name")
    return [{**dict(r), "is_simulated": bool(r["is_simulated"])} for r in rows]


def get_profile(conn: sqlite3.Connection, company_id: str) -> Profile:
    r = conn.execute("SELECT * FROM companies WHERE company_id=?", (company_id,)).fetchone()
    if r is None:
        raise NotFound(company_id)
    claims = conn.execute("SELECT * FROM claims WHERE company_id=? ORDER BY position", (company_id,))
    return Profile(
        company_id=r["company_id"], name=r["name"], website=r["website"], visibility=r["visibility"],
        is_simulated=bool(r["is_simulated"]), updated_at=r["updated_at"],
        claims=[_claim_from_row(c) for c in claims], missing_fields=json.loads(r["missing_fields"]),
    )


def _touch(conn: sqlite3.Connection, company_id: str) -> None:
    conn.execute("UPDATE companies SET updated_at=? WHERE company_id=?", (_now(), company_id))


def update_claim_value(conn: sqlite3.Connection, company_id: str, claim_id: str, value: str) -> Claim:
    """A user edit: the claim becomes user_confirmed, so agent re-runs keep it."""
    claim = Claim(
        id=claim_id, field=_claim_field(conn, company_id, claim_id), value=value,
        kind=ClaimKind.user_confirmed, evidence_url=None, snippet=None,
        retrieved_at=date.today(), confidence=1.0,
    )
    with conn:
        conn.execute(
            "UPDATE claims SET value=?, kind=?, evidence_url=NULL, snippet=NULL, retrieved_at=?,"
            " confidence=1.0, cached_snapshot=0 WHERE company_id=? AND id=?",
            (claim.value, claim.kind.value, claim.retrieved_at.isoformat(), company_id, claim_id),
        )
        _touch(conn, company_id)
    return claim


def _claim_field(conn: sqlite3.Connection, company_id: str, claim_id: str) -> str:
    r = conn.execute("SELECT field FROM claims WHERE company_id=? AND id=?", (company_id, claim_id)).fetchone()
    if r is None:
        raise NotFound(f"{company_id}/{claim_id}")
    return r["field"]


def add_claim(conn: sqlite3.Connection, company_id: str, field: ProfileField, value: str) -> Claim:
    """A user-added claim (e.g. a new priority). Clears the field from missing_fields."""
    profile = get_profile(conn, company_id)
    used = {c.id for c in profile.claims}
    n = 1
    while f"user-{n}" in used:
        n += 1
    claim = Claim(
        id=f"user-{n}", field=field, value=value, kind=ClaimKind.user_confirmed,
        retrieved_at=date.today(), confidence=1.0,
    )
    missing = [f.value for f in profile.missing_fields if f != claim.field]
    with conn:
        pos = conn.execute("SELECT COALESCE(MAX(position)+1, 0) FROM claims WHERE company_id=?", (company_id,)).fetchone()[0]
        _insert_claim(conn, company_id, claim, pos)
        conn.execute("UPDATE companies SET missing_fields=? WHERE company_id=?", (json.dumps(missing), company_id))
        _touch(conn, company_id)
    return claim


def set_visibility(conn: sqlite3.Connection, company_id: str, visibility: Visibility) -> Profile:
    with conn:
        cur = conn.execute("UPDATE companies SET visibility=? WHERE company_id=?", (Visibility(visibility).value, company_id))
        if cur.rowcount == 0:
            raise NotFound(company_id)
        _touch(conn, company_id)
    return get_profile(conn, company_id)


# ------------------------------------------------- opportunities + matches


def upsert_opportunities(conn: sqlite3.Connection, opportunities: list[Opportunity]) -> None:
    rows = [(o.id, Opportunity.model_validate(o.model_dump()).model_dump_json()) for o in opportunities]
    with conn:
        conn.executemany("INSERT INTO opportunities (id, data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", rows)


def list_opportunities(conn: sqlite3.Connection) -> list[Opportunity]:
    return [Opportunity.model_validate_json(r["data"]) for r in conn.execute("SELECT data FROM opportunities ORDER BY id")]


def replace_recommendations(conn: sqlite3.Connection, company_id: str, recs: list[Recommendation]) -> None:
    """Replace a company's ranking with fresh matcher output."""
    for r in recs:
        if r.company_id != company_id:
            raise ValueError(f"recommendation for {r.company_id!r} passed for {company_id!r}")
    with conn:
        conn.execute("DELETE FROM recommendations WHERE company_id=?", (company_id,))
        conn.executemany(
            "INSERT INTO recommendations (company_id, opportunity_id, score, data) VALUES (?,?,?,?)",
            [(r.company_id, r.opportunity_id, r.score, Recommendation.model_validate(r.model_dump()).model_dump_json()) for r in recs],
        )


def list_recommendations(conn: sqlite3.Connection, company_id: str) -> list[Recommendation]:
    rows = conn.execute("SELECT data FROM recommendations WHERE company_id=? ORDER BY score DESC, opportunity_id", (company_id,))
    return [Recommendation.model_validate_json(r["data"]) for r in rows]


def add_feedback(conn: sqlite3.Connection, company_id: str, opportunity_id: str, verdict: FeedbackVerdict) -> None:
    with conn:
        conn.execute(
            "INSERT INTO feedback (company_id, opportunity_id, verdict, created_at) VALUES (?,?,?,?)",
            (company_id, opportunity_id, FeedbackVerdict(verdict).value, _now()),
        )


# --------------------------------------------------------------------- users


def upsert_user(conn: sqlite3.Connection, user: User, password_hash: str) -> None:
    User.model_validate(user.model_dump())
    with conn:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, role, company_id) VALUES (?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET email=excluded.email, password_hash=excluded.password_hash,"
            " role=excluded.role, company_id=excluded.company_id",
            (user.id, user.email, password_hash, user.role.value, user.company_id),
        )


def _user_from_row(r: sqlite3.Row) -> User:
    return User(id=r["id"], email=r["email"], role=Role(r["role"]), company_id=r["company_id"])


def get_user(conn: sqlite3.Connection, user_id: str) -> User:
    r = conn.execute("SELECT id, email, role, company_id FROM users WHERE id=?", (user_id,)).fetchone()
    if r is None:
        raise NotFound(user_id)
    return _user_from_row(r)


def get_user_credentials(conn: sqlite3.Connection, email: str) -> tuple[User, str] | None:
    """For login only: the user and their password hash. Never send the hash anywhere."""
    r = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    return (_user_from_row(r), r["password_hash"]) if r else None
