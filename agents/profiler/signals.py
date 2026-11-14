"""Deterministic claim signals — the profiler's no-model path.

When no model runtime is configured the profiler still has to produce a profile
the demo can show. It may only use what is on the page, so this module does one
thing: find page sentences that talk about a profile area, and turn those
sentences into claims.

Nothing is paraphrased and nothing is invented:

* ``snippet`` is the sentence from the page, so it is verbatim by construction;
* ``value`` is that same sentence (trimmed), so it is traceable to the page;
* the field is our interpretation, so the claim is ``inferred`` unless the
  sentence itself makes the statement (``"We develop …"``, ``"Based in …"``);
* a field with no supporting sentence stays empty and ends up in
  ``missing_fields`` — which is the honest answer.

The LLM extractor in ``extract.py`` produces richer claims; this module is the
floor the profiler never drops below.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import config
from .text import Document, is_verbatim, sentences, truncate

FIELD_ORDER = (
    "products_services",
    "what_it_does",
    "technologies",
    "expertise",
    "application_areas",
    "industries",
    "customer_groups",
    "markets",
    "collaborations",
    "projects",
    "development_priorities",
    "geographic_focus",
    "topics",
)


@dataclass(frozen=True)
class Candidate:
    """A possible claim, before it is checked against the page and given an id."""

    field: str
    value: str
    kind: str = "inferred"
    snippet: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class Signal:
    keywords: tuple[str, ...]
    stated_markers: tuple[str, ...] = ()


SIGNALS: dict[str, Signal] = {
    "products_services": Signal(
        keywords=(
            "our product", "our products", "our service", "our services", "our solution",
            "our platform", "our system", "we offer", "we provide", "we supply", "we deliver",
            "product portfolio", "we sell",
        ),
        stated_markers=(
            "our product", "our service", "our solution", "our platform", "we offer",
            "we provide", "we supply", "we deliver",
        ),
    ),
    "what_it_does": Signal(
        keywords=(
            "we develop", "we build", "we make", "we produce", "we design", "we help",
            "we enable", "we create", "our mission", "we are a", "we are an",
            "specialises in", "specializes in", "the company develops", "the company is",
        ),
        stated_markers=(
            "we develop", "we build", "we make", "we produce", "we design", "we help",
            "we enable", "our mission", "we are a", "we are an", "specialises in",
            "specializes in",
        ),
    ),
    "technologies": Signal(
        keywords=(
            "sensor", "sensors", "iot", "artificial intelligence", "machine learning", "ai",
            "software", "platform", "cloud", "automation", "robotics", "battery", "hydrogen",
            "biotech", "photonics", "5g", "data", "electronics", "mechatronics", "laser",
            "composite", "materials", "chemistry", "energy", "recycling", "circular",
            "simulation", "digital twin", "embedded", "hardware", "algorithm",
        ),
        stated_markers=("our technology", "our technologies", "we use", "built on", "based on"),
    ),
    "expertise": Signal(
        keywords=(
            "expertise", "r&d", "prototype", "testing", "laboratory", "lab",
            "certification", "engineering", "consultancy", "know-how", "competence",
        ),
        stated_markers=("our expertise", "we specialise", "we specialize", "our team"),
    ),
    "application_areas": Signal(
        keywords=(
            "used in", "for use in", "applications include", "application areas",
            "is used for", "can be used", "designed for",
        ),
        stated_markers=("used in", "for use in", "applications include", "designed for"),
    ),
    "industries": Signal(
        keywords=(
            "automotive", "aerospace", "manufacturing", "healthcare", "medical", "energy",
            "food", "agriculture", "construction", "logistics", "packaging", "maritime",
            "shipping", "marine", "telecom", "defence", "defense", "pharma", "mining",
            "steel", "forestry", "process industry", "real estate", "retail",
        ),
        stated_markers=("industries we serve", "customers in", "we serve"),
    ),
    "customer_groups": Signal(
        keywords=(
            "our customers", "our clients", "customers", "clients", "b2b", "oem",
            "suppliers", "public sector", "smes", "enterprises", "startups",
            "municipalities",
        ),
        stated_markers=("our customers", "our clients"),
    ),
    "markets": Signal(
        keywords=(
            "market", "markets", "export", "global", "international", "nordic", "european",
            "scandinavia", "sales offices",
        ),
        stated_markers=("we sell", "our market", "we serve"),
    ),
    "collaborations": Signal(
        keywords=(
            "partner", "partners", "partnership", "collaboration", "together with",
            "consortium", "university", "institute", "alliance", "joint venture",
        ),
        stated_markers=(
            "in collaboration with", "we partner", "together with", "our partners",
            "we work with",
        ),
    ),
    "projects": Signal(
        keywords=(
            "project", "projects", "pilot", "demonstrator", "programme", "program",
            "case study", "proof of concept",
        ),
        stated_markers=("our project", "pilot project", "we run", "we are part of"),
    ),
    "development_priorities": Signal(
        keywords=(
            "priority", "priorities", "roadmap", "next step", "strategy", "strategic",
            "we are investing", "investment", "expansion", "scaling", "focus area",
            "next we",
        ),
        stated_markers=(
            "our priority", "our priorities", "our focus", "we focus", "we are investing",
            "our strategy", "next we", "our roadmap",
        ),
    ),
    # AGENTS.md §1: geographic focus only if the company states it.
    "geographic_focus": Signal(
        keywords=(
            "based in", "located in", "headquartered", "head office", "our headquarters",
            "we operate in", "established in", "founded in", "offices in", "plant in",
            "site in", "operations in",
        ),
        stated_markers=(
            "based in", "located in", "headquartered", "head office", "our headquarters",
            "we operate in", "established in", "founded in", "offices in", "plant in",
            "site in", "operations in",
        ),
    ),
    # Topics are thematic interpretation, never a direct statement.
    "topics": Signal(
        keywords=(
            "sustainability", "sustainable", "circular economy", "green transition",
            "digitalisation", "digitalization", "climate", "electrification", "innovation",
            "green", "renewable", "decarbonisation", "decarbonization", "energy efficiency",
        ),
    ),
}

_KEYWORD_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    field: tuple(
        re.compile(rf"\b{re.escape(word.strip())}\b", re.IGNORECASE) for word in signal.keywords
    )
    for field, signal in SIGNALS.items()
}


def _first_match_position(sentence: str, patterns: tuple[re.Pattern[str], ...]) -> int | None:
    positions = [m.start() for m in (pattern.search(sentence) for pattern in patterns) if m]
    return min(positions) if positions else None


def _has_marker(sentence: str, markers: tuple[str, ...]) -> bool:
    lowered = sentence.casefold()
    return any(marker in lowered for marker in markers)


def _pick_field(sentence: str, counts: dict[str, int]) -> tuple[str, bool] | None:
    """Choose one field per sentence, using the most salient signal it contains.

    Ranking is by where the signal appears in the sentence: the phrase nearest
    the start names what the sentence is about ("**Our next priority** is to
    scale the new sensor family" is a priority, not a technology). When two
    fields match at the same position, the one the sentence states explicitly
    wins, which keeps ``"based in …"`` as ``geographic_focus``.

    One sentence supports one claim, so the profile reads like a summary rather
    than a keyword dump.
    """
    best: tuple[tuple[int, int], str, bool] | None = None
    for field in FIELD_ORDER:
        if counts.get(field, 0) >= config.MAX_CLAIMS_PER_FIELD:
            continue
        position = _first_match_position(sentence, _KEYWORD_PATTERNS[field])
        if position is None:
            continue
        stated = _has_marker(sentence, SIGNALS[field].stated_markers)
        if field == "geographic_focus" and not stated:
            continue  # AGENTS.md §1: geographic focus only if stated
        rank = (position, 0 if stated else 1)
        if best is None or rank < best[0]:
            best = (rank, field, stated)
    if best is None:
        return None
    return best[1], best[2]


def candidate_claims(document: Document) -> list[Candidate]:
    """Build candidates from page text. Empty when the page says nothing useful."""
    out: list[Candidate] = []
    counts: dict[str, int] = {}

    def add(field: str, value: str, snippet: str | None, kind: str) -> None:
        if counts.get(field, 0) >= config.MAX_CLAIMS_PER_FIELD:
            return
        value = truncate(value, config.MAX_VALUE_CHARS)
        if not value:
            return
        counts[field] = counts.get(field, 0) + 1
        out.append(
            Candidate(
                field=field,
                value=value,
                kind=kind,
                snippet=snippet,
                confidence=(
                    config.FALLBACK_STATED_CONFIDENCE
                    if kind == "stated"
                    else config.FALLBACK_INFERRED_CONFIDENCE
                ),
            )
        )

    # The page's own self-description is the best answer to "what does it do?".
    for hint in (document.description, document.title):
        if not hint:
            continue
        verbatim = is_verbatim(hint, document.text)
        add(
            "what_it_does",
            hint,
            hint if verbatim else None,
            "stated" if verbatim else "inferred",
        )
        break

    for sentence in sentences(document.text):
        choice = _pick_field(sentence, counts)
        if choice is None:
            continue
        field, stated = choice
        add(field, sentence, sentence, "stated" if stated else "inferred")

    return out
