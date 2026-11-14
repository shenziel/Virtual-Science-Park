"""Profiler configuration.

Every tunable number and every environment variable the profiler reads lives
here, so a reviewer can audit the agent's behaviour in one file. Model names and
keys are never hard-coded: they come from the environment (see `.env.example`).

Owner: Backend 2.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, MutableMapping

PROFILER_DIR = Path(__file__).parent
_PROFILER_ENV_KEYS = frozenset(
    {
        "MODEL_RUNTIME",
        "MODEL_NAME",
        "MODEL_API_KEY",
        "MODEL_BASE_URL",
        "OLLAMA_HOST",
        "CACHE_DIR",
        "PROFILER_CACHE_DIR",
        "PROFILER_PAGE_CACHE_DIR",
        "PROFILER_USER_AGENT",
        "PROFILER_MIN_INTERVAL",
        "PROFILER_TIMEOUT",
    }
)


def _load_env_file(
    path: Path, environ: MutableMapping[str, str] | None = None
) -> None:
    """Load profiler settings from a simple .env file without overriding the process."""
    env = os.environ if environ is None else environ
    if not path.exists():
        return

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key = key.strip()
        if key not in _PROFILER_ENV_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value

    for key, value in values.items():
        env.setdefault(key, value)


_load_env_file(PROFILER_DIR.parents[1] / ".env")


def _cache_root(environ: Mapping[str, str] | None = None) -> Path:
    """Where profiles and cached pages go.

    ``PROFILER_CACHE_DIR`` names it directly. Otherwise ``CACHE_DIR`` is used:
    that is the variable ``docker-compose.yml`` sets for every service, so a
    one-off ``docker compose run … python -m agents.profiler`` writes to the
    ``/data`` volume instead of into the read-only image. The folder default
    keeps a plain checkout working with no environment at all.
    """
    env = os.environ if environ is None else environ
    return Path(env.get("PROFILER_CACHE_DIR") or env.get("CACHE_DIR") or PROFILER_DIR / "cache")


CACHE_DIR = _cache_root()
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
