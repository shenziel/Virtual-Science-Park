"""
Matcher configuration — all weights and thresholds live here.
Adjust without touching matcher.py.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------
WEIGHT_TOPIC_OVERLAP: float = 0.50   # Subject / topic relevance
WEIGHT_TIMELINE: float = 0.30        # Deadline / event date proximity
WEIGHT_LOCATION_FORMAT: float = 0.20 # Geographic fit or online availability

assert abs(WEIGHT_TOPIC_OVERLAP + WEIGHT_TIMELINE + WEIGHT_LOCATION_FORMAT - 1.0) < 1e-9, (
    "Scoring weights must sum to 1.0"
)

# ---------------------------------------------------------------------------
# Timeline scoring parameters
# ---------------------------------------------------------------------------
# Full score if the deadline/event is within this many days
TIMELINE_FULL_SCORE_DAYS: int = 30
# Zero score if deadline/event is farther away than this many days
TIMELINE_ZERO_SCORE_DAYS: int = 365
# Score awarded when no date is available (treat as moderate)
TIMELINE_NO_DATE_SCORE: float = 0.5

# ---------------------------------------------------------------------------
# Topic overlap
# ---------------------------------------------------------------------------
# user_confirmed claims receive this multiplier on their topic weight
USER_CONFIRMED_BOOST: float = 1.5

# Minimum score to include a recommendation in results
MIN_SCORE_THRESHOLD: float = 0.05

# ---------------------------------------------------------------------------
# Matcher LLM settings (names match the root .env.example).
# ---------------------------------------------------------------------------
import os

MATCHER_MODEL: str = os.getenv("MATCHER_MODEL", "openai/gpt-4o-mini")
MATCHER_API_KEY: str | None = os.getenv("MATCHER_API_KEY")
MATCHER_BASE_URL: str = os.getenv(
    "MATCHER_BASE_URL", "https://openrouter.ai/api/v1"
).rstrip("/")

# Re-matching can happen after every claim edit, so fail over to the local
# deterministic explanation quickly when the provider is slow.
MATCHER_TIMEOUT_SECONDS: float = 5.0
