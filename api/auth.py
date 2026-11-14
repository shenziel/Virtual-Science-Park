"""Login, logout and "who am I". Owner: Backend 1.

Email + password login returns an opaque bearer token. Passwords are checked
against argon2 hashes and are never logged or returned.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.deps import UNAUTHORIZED, bearer_token, current_user, get_conn
from contracts.models import LoginRequest, LoginResponse, User
from db import database

router = APIRouter(prefix="/auth", tags=["auth"])

_hasher = PasswordHasher()
# Verified when the email is unknown, so both failure cases take similar time.
_DUMMY_HASH = _hasher.hash("not-a-real-password")

BAD_LOGIN = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Wrong email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


def session_ttl() -> timedelta:
    return timedelta(hours=float(os.environ.get("SESSION_TTL_HOURS") or 12))


def _password_ok(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, conn: sqlite3.Connection = Depends(get_conn)) -> LoginResponse:
    found = database.get_user_credentials(conn, body.email)
    if found is None:
        _password_ok(_DUMMY_HASH, body.password)
        raise BAD_LOGIN
    user, password_hash = found
    if not _password_ok(password_hash, body.password):
        raise BAD_LOGIN
    token, expires_at = database.create_session(conn, user.id, session_ttl())
    return LoginResponse(access_token=token, expires_at=expires_at, user=user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(
    _: User = Depends(current_user),
    token: str | None = Depends(bearer_token),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    if token is None:  # current_user already guarantees this; kept for type safety
        raise UNAUTHORIZED
    database.delete_session(conn, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=User)
def me(user: User = Depends(current_user)) -> User:
    return user
