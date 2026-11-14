"""Shared FastAPI dependencies: database connection and the calling user. Owner: Backend 1.

Every endpoint that needs to know who is calling uses `current_user` (login
required) or `optional_user` (visitors allowed). Authorization is decided here
and in the endpoints, server-side, on every request: never in the UI.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from contracts.models import User
from db import database

# auto_error=False: we return our own 401 (with WWW-Authenticate) and allow visitors.
bearer = HTTPBearer(auto_error=False, description="Token from POST /auth/login")

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not logged in or session expired",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = database.connect()
    try:
        yield conn
    finally:
        conn.close()


def bearer_token(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str | None:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        return None
    return creds.credentials


def optional_user(
    token: str | None = Depends(bearer_token),
    conn: sqlite3.Connection = Depends(get_conn),
) -> User | None:
    """The logged-in user, or None for a visitor. An invalid token is treated as a visitor."""
    return database.get_session_user(conn, token) if token else None


def current_user(
    token: str | None = Depends(bearer_token),
    conn: sqlite3.Connection = Depends(get_conn),
) -> User:
    """The logged-in user; 401 otherwise."""
    user = database.get_session_user(conn, token) if token else None
    if user is None:
        raise UNAUTHORIZED
    return user
