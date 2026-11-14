"""
Configuration for the Opportunity Monitors.
Owner: Backend 3 (agents/monitors/)
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

# Base directory for cached snapshots
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
VINNOVA_SNAPSHOT_PATH = SNAPSHOTS_DIR / "vinnova_calls.json"
BSP_EVENTS_SNAPSHOT_PATH = SNAPSHOTS_DIR / "bsp_events.json"

# HTTP User-Agent identifying the science park bot respectfully (AGENTS.md §5)
USER_AGENT = "VirtualScienceParkBot/1.0 (+https://www.bluesciencepark.se; contact@bluesciencepark.se)"

# Network request timeout in seconds
REQUEST_TIMEOUT_SECONDS = int(os.getenv("MONITOR_REQUEST_TIMEOUT", "10"))

# Default public source endpoints
VINNOVA_API_BASE_URL = os.getenv("VINNOVA_API_BASE_URL", "https://data.vinnova.se/api")
# The legacy open-data API accepts an "updated since" date as the final path
# segment. A two-year window keeps the request bounded while including recently
# changed calls and application rounds.
VINNOVA_UPDATED_SINCE = os.getenv(
    "VINNOVA_UPDATED_SINCE",
    (date.today() - timedelta(days=730)).isoformat(),
)
BSP_EVENTS_FEED_URL = os.getenv(
    "BSP_EVENTS_FEED_URL",
    "https://www.bluesciencepark.se/evenemang/feed/",
)
