"""Profiler configuration.

Every tunable number and every environment variable the profiler reads lives
here, so a reviewer can audit the agent's behaviour in one file. Model names and
keys are never hard-coded: they come from the environment (see `.env.example`).

Owner: Backend 2.
"""
from __future__ import annotations

import os
from pathlib import Path

PROFILER_DIR = Path(__file__).parent
CACHE_DIR = Path(os.getenv("PROFILER_CACHE_DIR") or PROFILER_DIR / "cache")
PAGE_CACHE_DIR = Path(os.getenv("PROFILER_PAGE_CACHE_DIR") or CACHE_DIR / "pages")
PROMPTS_DIR = PROFILER_DIR / "prompts"
PROMPT_FILE = PROMPTS_DIR / "extract_claims.md"

# --- scraping etiquette (AGENTS.md §5) -------------------------------------
# An identifying User-Agent, a per-host delay and robots.txt are not optional.
USER_AGENT = os.getenv(
    "PROFILER_USER_AGENT",
    "BlueScienceParkProfiler/1.0 (demo; +https://bluesciencepark.se)",
)
MIN_REQUEST_INTERVAL_SECONDS = float(os.getenv("PROFILER_MIN_INTERVAL", "2.0"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("PROFILER_TIMEOUT", "20"))
MAX_PAGE_BYTES = 2_000_000
MAX_PAGE_CHARS = 60_000  # how much page text goes into the LLM prompt

# --- extraction ------------------------------------------------------------
MAX_EXTRACTION_ATTEMPTS = 2  # validate, retry once, then raise (never patch)
MAX_CLAIMS_PER_FIELD = 3
MAX_VALUE_CHARS = 240
MIN_SNIPPET_CHARS = 20  # shorter "quotes" prove nothing
STATEMENT_CONFIDENCE = 0.9
INTERPRETATION_CONFIDENCE = 0.6
FALLBACK_STATED_CONFIDENCE = 0.8
FALLBACK_INFERRED_CONFIDENCE = 0.5

# --- model runtime (read at runtime, never hard-coded) ---------------------
MODEL_RUNTIME = (os.getenv("MODEL_RUNTIME") or "").strip().lower()  # api | ollama
MODEL_NAME = os.getenv("MODEL_NAME") or ""
MODEL_API_KEY = os.getenv("MODEL_API_KEY") or ""
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL") or "https://api.openai.com/v1"
OLLAMA_HOST = os.getenv("OLLAMA_HOST") or "http://localhost:11434"
LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 2500
LLM_TIMEOUT_SECONDS = 120.0
