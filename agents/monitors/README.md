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
- **Offline Reliability:** If public network endpoints are unreachable or in test/sandbox environments, monitors fall back to dated, labelled cached snapshots in `snapshots/`.
- **Badging / Labelling:** All cached snapshot items explicitly set `cached_snapshot=True`.
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

# Fetch opportunities from all monitors (automatically uses snapshots if offline)
opportunities = fetch_all_opportunities()

for opp in opportunities:
    print(opp.type, opp.title, opp.url, opp.deadline or opp.event_date)
```
