"""POST /chat. Owner: Backend 1.

The company is the logged-in user's company, read from the session. It never
comes from the request body or from model output.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from api.chat import answer as answering
from api.chat.guardrail import FIXED_REPLIES, classify
from api.deps import current_user, get_conn
from contracts.models import ChatAction, ChatRequest, ChatResponse, User
from db import database

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_conn)) -> ChatResponse:
    if user.company_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The assistant is for company accounts")
    company_id = user.company_id

    companies = {c["company_id"]: c["name"] for c in database.list_companies(conn)}
    decision = classify(body.message, company_id, companies)
    if decision.action != ChatAction.answer:
        return ChatResponse(reply=FIXED_REPLIES[decision.reason], action=decision.action)

    try:
        profile = database.get_profile(conn, company_id)
    except database.NotFound:
        return ChatResponse(reply="Your company has no profile yet, so there is nothing to answer from.",
                            action=ChatAction.answer)
    opps = {o.id: o for o in database.list_opportunities(conn)}
    ctx = answering.build_context(profile, database.list_recommendations(conn, company_id), opps)
    others = [name for cid, name in companies.items() if cid != company_id]
    reply, sources = answering.answer(body.message, ctx, others)
    return ChatResponse(reply=reply, action=ChatAction.answer, sources=sources)
