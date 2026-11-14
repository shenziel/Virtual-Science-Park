"""Company profiles, claim edits, publishing and recommendations. Owner: Backend 1."""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, status

from api.deps import current_user, get_conn, optional_user
from api.permissions import can_view, not_found, require_edit
from contracts.models import (
    Claim,
    ClaimCreate,
    ClaimPatch,
    CompanySummary,
    Profile,
    Recommendation,
    User,
    VisibilityPatch,
)
from db import database

log = logging.getLogger(__name__)
router = APIRouter(prefix="/companies", tags=["companies"])


def _visible_profile(conn: sqlite3.Connection, user: User | None, company_id: str) -> Profile:
    """The profile if this caller may see it. Hidden and missing look the same: 404."""
    try:
        profile = database.get_profile(conn, company_id)
    except database.NotFound:
        raise not_found() from None
    if not can_view(user, company_id, profile.visibility):
        raise not_found()
    return profile


def rematch(conn: sqlite3.Connection, company_id: str) -> None:
    """Re-rank a company's opportunities after its profile changed.

    A failure here must not undo the user's edit: the old ranking stays and the
    error is logged.
    """
    try:
        from agents.matcher import match

        profile = database.get_profile(conn, company_id)
        recs = match(profile, database.list_opportunities(conn))
        database.replace_recommendations(conn, company_id, recs)
    except Exception:  # noqa: BLE001 - keep the edit, report the matcher problem
        log.exception("re-matching %s failed; keeping the previous ranking", company_id)


@router.get("", response_model=list[CompanySummary])
def list_companies(
    user: User | None = Depends(optional_user),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[CompanySummary]:
    return [
        CompanySummary(**c)
        for c in database.list_companies(conn)
        if can_view(user, c["company_id"], c["visibility"])
    ]


@router.get("/{company_id}/profile", response_model=Profile)
def get_profile(
    company_id: str,
    user: User | None = Depends(optional_user),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Profile:
    return _visible_profile(conn, user, company_id)


@router.patch("/{company_id}/claims/{claim_id}", response_model=Claim)
def edit_claim(
    company_id: str,
    claim_id: str,
    body: ClaimPatch,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Claim:
    require_edit(user, company_id)
    try:
        claim = database.update_claim_value(conn, company_id, claim_id, body.value)
    except database.NotFound:
        raise not_found("Claim") from None
    rematch(conn, company_id)
    return claim


@router.post("/{company_id}/claims", response_model=Claim, status_code=status.HTTP_201_CREATED)
def add_claim(
    company_id: str,
    body: ClaimCreate,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Claim:
    require_edit(user, company_id)
    try:
        claim = database.add_claim(conn, company_id, body.field, body.value)
    except database.NotFound:
        raise not_found() from None
    rematch(conn, company_id)
    return claim


@router.patch("/{company_id}/visibility", response_model=Profile)
def set_visibility(
    company_id: str,
    body: VisibilityPatch,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Profile:
    require_edit(user, company_id)
    try:
        return database.set_visibility(conn, company_id, body.visibility)
    except database.NotFound:
        raise not_found() from None


@router.get("/{company_id}/recommendations", response_model=list[Recommendation])
def list_recommendations(
    company_id: str,
    user: User | None = Depends(optional_user),
    conn: sqlite3.Connection = Depends(get_conn),
) -> list[Recommendation]:
    _visible_profile(conn, user, company_id)
    return database.list_recommendations(conn, company_id)
