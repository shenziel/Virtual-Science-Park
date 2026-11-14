"""Build a chat answer from the logged-in company's own data. Owner: Backend 1.

The context is read server-side for the session's company only. Scraped text
is passed to the model as data inside <company_context>; any item that looks
like an instruction is dropped before it gets there. Without a model (or if it
fails, or its reply breaks a rule) a deterministic answer is built instead.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from api.chat.guardrail import looks_like_injection, normalize
from contracts.models import Opportunity, Profile, Recommendation

log = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "system_v1.md"
PROMPT_MARKER = "VSP-GUARDRAIL-v1"
TOP_N = 3
CAVEAT = "These are potential matches; eligibility is not confirmed."


@dataclass
class Context:
    profile: Profile
    recommendations: list[tuple[Recommendation, Opportunity]]
    dropped_injections: int = 0
    sources: list[str] = field(default_factory=list)


def _label(opp: Opportunity) -> str:
    tags = [t for t, on in (("simulated", opp.is_simulated), ("cached snapshot", opp.cached_snapshot)) if on]
    return f" [{', '.join(tags)}]" if tags else ""


def _when(opp: Opportunity) -> str:
    if opp.deadline:
        return f"deadline {opp.deadline.isoformat()}"
    if opp.event_date:
        return f"event {opp.event_date.isoformat()}"
    return f"published {opp.published.isoformat()}" if opp.published else "no date"


def build_context(profile: Profile, recs: list[Recommendation], opps: dict[str, Opportunity]) -> Context:
    """Keep only clean items: scraped text that tries to give instructions is dropped."""
    dropped = 0
    claims = []
    for c in profile.claims:
        if looks_like_injection(c.value) or looks_like_injection(c.snippet):
            dropped += 1
            continue
        claims.append(c)
    pairs = []
    for r in recs:
        o = opps.get(r.opportunity_id)
        if o is None:
            continue
        if any(looks_like_injection(t) for t in (o.title, o.eligibility_text, o.audience, r.why, *o.topics)):
            dropped += 1
            continue
        pairs.append((r, o))
    if dropped:
        log.warning("dropped %d context items that looked like injected instructions", dropped)
    clean = profile.model_copy(update={"claims": claims})
    return Context(clean, pairs, dropped)


def _context_json(ctx: Context) -> str:
    p = ctx.profile
    data = {
        "company": p.name,
        "profile_is_simulated": p.is_simulated,
        "claims": [{"field": c.field.value, "value": c.value, "kind": c.kind.value,
                    "source": c.evidence_url, "cached_snapshot": c.cached_snapshot} for c in p.claims],
        "missing_fields": [f.value for f in p.missing_fields],
        "ranked_opportunities": [
            {"title": o.title, "type": o.type.value, "when": _when(o), "url": o.url, "score": r.score,
             "why": r.why, "caveats": r.caveats, "simulated": o.is_simulated, "cached_snapshot": o.cached_snapshot}
            for r, o in ctx.recommendations[:5]
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=1)


# ------------------------------------------------------- deterministic

_OPP_WORDS = re.compile(r"opportunit|funding|fund|grant|call|vinnova|event|testbed|deadline|match|recommend|apply|ranking|eligib")


def deterministic_answer(message: str, ctx: Context) -> tuple[str, list[str]]:
    text = normalize(message)
    if _OPP_WORDS.search(text):
        if not ctx.recommendations:
            return ("There are no ranked opportunities for your company yet. Check back after the next "
                    "opportunity refresh."), []
        lines, sources = [f"Top matches for {ctx.profile.name}:"], []
        for i, (r, o) in enumerate(ctx.recommendations[:TOP_N], 1):
            lines.append(f"{i}. {o.title} ({o.type.value}, {_when(o)}){_label(o)}: {r.why} {o.url}")
            sources.append(o.url)
        lines.append(CAVEAT)
        return "\n".join(lines), sources

    claims = ctx.profile.claims
    wanted = [c for c in claims if c.field.value.replace("_", " ") in text or c.field.value.split("_")[0] in text]
    shown = (wanted or claims)[:5]
    if not shown:
        return "Your profile has no claims yet.", []
    lines = [f"From {ctx.profile.name}'s profile:"]
    sources = []
    for c in shown:
        src = f" ({c.evidence_url})" if c.evidence_url else ""
        tag = " [cached snapshot]" if c.cached_snapshot else ""
        lines.append(f"- {c.field.value.replace('_', ' ')}: {c.value} [{c.kind.value}]{tag}{src}")
        if c.evidence_url:
            sources.append(c.evidence_url)
    if ctx.profile.is_simulated:
        lines.append("Note: this profile is simulated demo data.")
    return "\n".join(lines), sources


# ----------------------------------------------------------------- model


def _settings() -> tuple[str, str, str, float]:
    return (
        (os.environ.get("CHAT_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/"),
        os.environ.get("CHAT_MODEL") or "",
        os.environ.get("CHAT_API_KEY") or "",
        float(os.environ.get("CHAT_TIMEOUT") or 15),
    )


def llm_answer(message: str, ctx: Context, post=httpx.post) -> str | None:
    """Ask the model; None if not configured or anything goes wrong."""
    base_url, model, key, timeout = _settings()
    if not key or not model:
        return None
    user = f"<company_context>\n{_context_json(ctx)}\n</company_context>\n\nQuestion: {message}"
    try:
        resp = post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "temperature": 0.2, "max_tokens": 400,
                  "messages": [{"role": "system", "content": PROMPT_FILE.read_text(encoding="utf-8")},
                               {"role": "user", "content": user}]},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip() or None
    except Exception:  # noqa: BLE001 - fall back to the deterministic answer
        log.exception("chat model call failed; using the deterministic answer")
        return None


def reply_is_safe(reply: str, other_company_names: list[str]) -> bool:
    """Discard model output that leaks the prompt or talks about another company."""
    text = normalize(reply)
    if PROMPT_MARKER.lower() in text or "company_context" in text:
        return False
    return not any(n and re.search(rf"(?<![a-z0-9]){re.escape(normalize(n))}(?![a-z0-9])", text)
                   for n in other_company_names)


def answer(message: str, ctx: Context, other_company_names: list[str], post=httpx.post) -> tuple[str, list[str]]:
    fallback, sources = deterministic_answer(message, ctx)
    reply = llm_answer(message, ctx, post=post)
    if reply and reply_is_safe(reply, other_company_names):
        context_urls = [o.url for _, o in ctx.recommendations] + [c.evidence_url for c in ctx.profile.claims if c.evidence_url]
        return reply, [u for u in dict.fromkeys(context_urls) if u in reply]
    if reply:
        log.warning("discarded a model reply that broke a guardrail rule")
    return fallback, sources
