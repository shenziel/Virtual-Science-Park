from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import auth
from db import database
from db.seed import seed_db


def prepare_database() -> None:
    """Create tables; seed from SEED_DIR when the database has no users yet."""
    conn = database.connect()
    try:
        database.init_db(conn)
        if database.count_users(conn) == 0:
            seed_db(conn)
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    prepare_database()
    yield


app = FastAPI(title="Virtual Science Park API", lifespan=lifespan)
app.include_router(auth.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
