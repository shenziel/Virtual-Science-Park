"""Load a seed folder (fixtures/ or fixtures/mock/) into SQLite. Owner: Backend 1.

    python -m db.seed                    # uses SEED_DIR and DATABASE_URL
    python -m db.seed fixtures/mock      # explicit folder

Safe to run again: user_confirmed claims and visibility choices are kept
(see db.database.upsert_profile). Passwords are hashed with argon2.
"""

from __future__ import annotations

import sqlite3
import sys

from argon2 import PasswordHasher

from contracts.models import User
from db import database
from fixtures.loader import load_seed

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def seed_db(conn: sqlite3.Connection, folder=None) -> dict[str, int]:
    seed = load_seed(folder)
    database.init_db(conn)
    for profile in seed.profiles.values():
        database.upsert_profile(conn, profile)
    database.upsert_opportunities(conn, list(seed.opportunities.values()))
    by_company: dict[str, list] = {}
    for r in seed.recommendations:
        by_company.setdefault(r.company_id, []).append(r)
    for cid, recs in by_company.items():
        database.replace_recommendations(conn, cid, recs)
    for u in seed.users:
        user = User(**{k: v for k, v in u.items() if k != "password"})
        database.upsert_user(conn, user, hash_password(u["password"]))
    return {
        "profiles": len(seed.profiles),
        "opportunities": len(seed.opportunities),
        "recommendations": len(seed.recommendations),
        "users": len(seed.users),
    }


def main(argv: list[str]) -> None:
    conn = database.connect()
    counts = seed_db(conn, argv[1] if len(argv) > 1 else None)
    print("seeded", ", ".join(f"{v} {k}" for k, v in counts.items()))


if __name__ == "__main__":
    main(sys.argv)
