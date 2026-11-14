"""BSP-admin-only operations. Owner: Backend 1."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from api.deps import current_user, get_conn
from contracts.models import RefreshResult, Role, User
from db.refresh import refresh_opportunities

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "BSP admins only")
    return user


@router.post("/opportunities/refresh", response_model=RefreshResult)
def refresh(_: User = Depends(require_admin), conn: sqlite3.Connection = Depends(get_conn)) -> RefreshResult:
    """Fetch from the monitors now, replace the stored opportunities and re-rank every company."""
    return refresh_opportunities(conn)
