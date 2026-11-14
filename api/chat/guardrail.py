"""Chat guardrail: decide what to do with a message before any model sees it. Owner: Backend 1.

Deterministic on purpose: the boundary tests (relevant, unrelated, unclear,
override, role-play, other-company data, injected web page) run in CI without
a model or network. Order matters: refusals are checked first, so an on-topic
word cannot smuggle an override past the guardrail.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from contracts.models import ChatAction

# --- refusals -------------------------------------------------------------

_OVERRIDE = [
    r"\b(ignore|disregard|forget|bypass|skip)\b.{0,40}\b(instructions?|rules?|prompts?|guidelines?|guardrails?|restrictions?|policy|policies)\b",
    r"\b(system|developer|hidden|initial|original)\s+(prompt|message|instructions?)\b",
    r"\b(reveal|show|print|repeat|leak|tell me)\b.{0,40}\b(prompt|instructions|rules|configuration|config)\b",
    r"\bdeveloper\s+mode\b",
    r"\bjail\s*break",
    r"\bnew\s+instructions?\b",
    r"\boverride\b",
    r"\bno\s+(longer\s+)?(bound|restricted|limited)\b",
    r"\b(api[\s_-]?keys?|passwords?|secrets?|access\s+tokens?|bearer\s+tokens?|credentials?)\b",
]

_ROLE_PLAY = [
    r"\bpretend\b",
    r"\bact\s+(as|like)\b",
    r"\brole[\s-]?play",
    r"\byou\s+are\s+now\b",
    r"\bfrom\s+now\s+on,?\s+you\b",
    r"\bimagine\s+(that\s+)?you\s+are\b",
    r"\bplay\s+the\s+(role|part)\b",
    r"\bstay\s+in\s+character\b",
    r"\blet'?s\s+play\s+a\s+game\b",
]

_OTHER_COMPANY_GENERIC = [
    r"\b(other|another|competitor'?s?|rival)\s+(member\s+)?compan(y|ies)'?s?\b",
    r"\b(all|every)\s+(the\s+)?(member\s+)?compan(y|ies)\b",
    r"\b(their|someone\s+else'?s)\s+(private\s+)?(profile|data|claims)\b",
]

# --- on-topic -------------------------------------------------------------

_RELEVANT = [
    r"\bprofiles?\b", r"\bclaims?\b", r"\btechnolog", r"\bproducts?\b", r"\bservices?\b", r"\bexpertise\b",
    r"\bmarkets?\b", r"\bcustomers?\b", r"\bindustr", r"\bprioriti", r"\bprojects?\b", r"\bcollaborat",
    r"\btopics?\b", r"\bopportunit", r"\bfunding\b", r"\bfund(s|ed)?\b", r"\bgrants?\b", r"\bcalls?\b",
    r"\bvinnova\b", r"\bevents?\b", r"\btestbeds?\b", r"\bdeadlines?\b", r"\bmatch", r"\brecommend",
    r"\bapply\b", r"\bapplication", r"\beligib", r"\branking\b", r"\bevidence\b", r"\bsources?\b",
    r"\bpublish", r"\bprivate\b", r"\bblue\s+science\s+park\b", r"\bour\s+compan", r"\bmy\s+compan",
    r"\bwhat\s+(do|does)\s+we\b", r"\bfor\s+us\b", r"\butlysning", r"\bfinansiering", r"\bevenemang",
]

# Words that carry no topic on their own: a short message of only these is unclear.
_UNCLEAR_MAX_WORDS = 3

COMPILED = {
    "override": [re.compile(p) for p in _OVERRIDE],
    "role_play": [re.compile(p) for p in _ROLE_PLAY],
    "other_company": [re.compile(p) for p in _OTHER_COMPANY_GENERIC],
    "relevant": [re.compile(p) for p in _RELEVANT],
}


@dataclass(frozen=True)
class Decision:
    action: ChatAction
    reason: str  # override | role_play | other_company | unclear | relevant | unrelated


def normalize(text: str) -> str:
    """Lowercase, fold Unicode look-alikes, drop zero-width characters, collapse spaces."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return re.sub(r"\s+", " ", text).strip().lower()


def _any(kind: str, text: str) -> bool:
    return any(p.search(text) for p in COMPILED[kind])


def _names_other_company(text: str, own_id: str, others: dict[str, str]) -> bool:
    for cid, name in others.items():
        if cid == own_id:
            continue
        for term in {cid, cid.replace("-", " "), normalize(name)}:
            if term and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text):
                return True
    return False


def classify(message: str, own_company_id: str, other_companies: dict[str, str]) -> Decision:
    """`other_companies`: company_id -> name for every known company (own included is fine)."""
    text = normalize(message)
    if _any("override", text):
        return Decision(ChatAction.refuse, "override")
    if _any("role_play", text):
        return Decision(ChatAction.refuse, "role_play")
    if _names_other_company(text, own_company_id, other_companies) or _any("other_company", text):
        return Decision(ChatAction.refuse, "other_company")
    relevant = _any("relevant", text)
    if not relevant and len(re.findall(r"[a-z0-9åäöé']+", text)) <= _UNCLEAR_MAX_WORDS:
        return Decision(ChatAction.clarify, "unclear")
    if relevant:
        return Decision(ChatAction.answer, "relevant")
    return Decision(ChatAction.redirect, "unrelated")


def looks_like_injection(text: str | None) -> bool:
    """For scraped or stored text going INTO the context: does it try to give instructions?"""
    if not text:
        return False
    t = normalize(text)
    return _any("override", t) or _any("role_play", t)


FIXED_REPLIES = {
    "override": "I can't change how I work or share my instructions. I can help with your company's "
                "profile, matching opportunities and why they match.",
    "role_play": "I can't take on other roles. I can help with your company's profile, matching "
                 "opportunities and why they match.",
    "other_company": "I can only discuss your own company's profile and matches. Other companies' "
                     "private information isn't available here.",
    "unclear": "Could you say a bit more? For example: \"Which funding calls match our priorities?\" "
               "or \"What does our profile say about our technologies?\"",
    "unrelated": "That's outside what I can help with here. I answer questions about your company's "
                 "profile, funding and event opportunities, and why they match.",
}
