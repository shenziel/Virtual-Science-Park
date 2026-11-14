import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import admin, auth, companies, opportunities
from db import database
from db.refresh import refresh_opportunities
from db.seed import seed_db


def prepare_database() -> None:
    """Create tables; seed from SEED_DIR when the database has no users yet.

    Then, unless OPPORTUNITY_REFRESH=off, refresh opportunities from the
    monitors so the API never serves seeded mock opportunities as current ones.
    This runs before the API accepts requests.
    """
    conn = database.connect()
    try:
        database.init_db(conn)
        if database.count_users(conn) == 0:
            seed_db(conn)
        if (os.environ.get("OPPORTUNITY_REFRESH") or "startup").strip().lower() != "off":
            refresh_opportunities(conn)
    finally:
        conn.close()


def ui_origins() -> list[str]:
    """Browser origins allowed to call the API (comma-separated UI_ORIGIN). Empty = none."""
    return [o.strip().rstrip("/") for o in (os.environ.get("UI_ORIGIN") or "").split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    prepare_database()
    yield


app = FastAPI(title="Virtual Science Park API", lifespan=lifespan)

# Only the UI's own origins; bearer tokens travel in the Authorization header, no cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ui_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(opportunities.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
