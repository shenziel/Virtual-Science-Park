# Opportunity Monitors (`agents/monitors/`)

**Owner:** Backend 3  
**Responsibility:** Monitor public sources (funding calls and science park events) and produce clean, validated `Opportunity` objects conforming to `contracts/opportunity.json`.

---

## Sources

Per AGENTS.md §5:
1. **Funding Source:** Vinnova open calls (`VinnovaFundingMonitor`)
2. **Events Source:** Blue Science Park events and webinars (`BSPEventsMonitor`)

---

## Contract Compliance & Guarantees

- **No Inventions:** Every opportunity requires a live `url` (`http://` or `https://`) and at least one real date (`published`, `deadline`, or `event_date`). Items missing either are dropped immediately.
- **Offline Behavior:** Blue Science Park events can use a dated, labelled cached snapshot. Vinnova funding returns no items if the live API is unavailable; there is no fabricated funding snapshot.
- **Badging / Labelling:** Cached event items explicitly set `cached_snapshot=True`. Vinnova results always come from live API responses and set `cached_snapshot=False`.
- **Vinnova API:** Reads calls and application rounds from the documented `data.vinnova.se` endpoints, joins them by case number, and emits only public rounds with a future closing date. `VINNOVA_UPDATED_SINCE` can override the default two-year lookback date.
- **Environment names:** Source settings use `MONITOR_REQUEST_TIMEOUT`, `VINNOVA_API_URL`, `VINNOVA_UPDATED_SINCE`, and `BSP_EVENTS_FEED_URL`, matching `.env.example`. `MONITOR_BASE_URL`, `MONITOR_MODEL`, and `MONITOR_API_KEY` are also read there for consistency, but this deterministic monitor currently makes no LLM calls.
- **Identifying User-Agent:** All HTTP requests send:
  `VirtualScienceParkBot/1.0 (+https://www.bluesciencepark.se; contact@bluesciencepark.se)`
- **Validation:** Every item returned by `fetch_all_opportunities()` validates against `contracts.models.Opportunity`.

---

## Directory Structure

```
agents/monitors/
├── __init__.py           # fetch_all_opportunities() aggregator
├── base.py               # BaseMonitor, sanitization, date parsing, slugify
├── config.py             # URLs, timeout, user agent, snapshot paths
├── vinnova.py            # VinnovaFundingMonitor
├── bsp_events.py         # BSPEventsMonitor
├── snapshots/            # Dated, labelled cached snapshots for offline demo
│   ├── vinnova_calls.json
│   └── bsp_events.json
├── tests/
│   ├── __init__.py
│   └── test_monitors.py  # Comprehensive test suite
└── README.md
```

---

## Usage

```python
from agents.monitors import fetch_all_opportunities

# Fetch live funding opportunities and events (events may use a labelled snapshot offline)
opportunities = fetch_all_opportunities()

for opp in opportunities:
    print(opp.type, opp.title, opp.url, opp.deadline or opp.event_date)
```
