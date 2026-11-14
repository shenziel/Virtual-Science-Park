"""Virtual Science Park SQLite schema. Owner: Backend 1.

Kept as a constant (not a .sql file read at runtime) so no file content ever
reaches SQL execution. Idempotent: db.database.init_db() runs it on every start.
"""

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    company_id     TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    website        TEXT NOT NULL,
    visibility     TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'published')),
    is_simulated   INTEGER NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL,
    missing_fields TEXT NOT NULL DEFAULT '[]'  -- JSON list of ProfileField
);

-- One row per claim, so single claims can be edited.
CREATE TABLE IF NOT EXISTS claims (
    company_id      TEXT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    id              TEXT NOT NULL,
    field           TEXT NOT NULL,
    value           TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('stated', 'inferred', 'user_confirmed')),
    evidence_url    TEXT,
    snippet         TEXT,
    retrieved_at    TEXT NOT NULL,
    confidence      REAL NOT NULL,
    cached_snapshot INTEGER NOT NULL DEFAULT 0,
    position        INTEGER NOT NULL,  -- keeps the profiler's order
    PRIMARY KEY (company_id, id)
);

-- Opportunities and recommendations are written whole by agents: stored as validated JSON.
CREATE TABLE IF NOT EXISTS opportunities (
    id   TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    company_id     TEXT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    score          REAL NOT NULL,
    data           TEXT NOT NULL,
    PRIMARY KEY (company_id, opportunity_id)
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,  -- argon2; never returned by the API
    role          TEXT NOT NULL CHECK (role IN ('company', 'admin')),
    company_id    TEXT REFERENCES companies(company_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id     TEXT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    opportunity_id TEXT NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    verdict        TEXT NOT NULL CHECK (verdict IN ('save', 'relevant', 'not_relevant')),
    created_at     TEXT NOT NULL
);
"""
