"""Opportunities (monitors' output) and feedback on recommendations. Owner: Backend 1."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.deps import current_user, get_conn
from api.permissions import not_found
from contracts.models import FeedbackIn, Opportunity, User
from db import database

router = APIRouter(tags=["opportunities"])


@router.get("/opportunities", response_model=list[Opportunity])
def list_opportunities(conn: sqlite3.Connection = Depends(get_conn)) -> list[Opportunity]:
    """Public: every opportunity, with its source link, dates and simulated/cached labels."""
    return database.list_opportunities(conn)


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def give_feedback(
    body: FeedbackIn,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    """Save / relevant / not relevant. The company comes from the session, never the body."""
    if user.company_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Feedback is given by a company account")
    if body.opportunity_id not in {o.id for o in database.list_opportunities(conn)}:
        raise not_found("Opportunity")
    database.add_feedback(conn, user.company_id, body.opportunity_id, body.verdict)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
