# Opportunity Monitors (`agents/monitors/`)

**Owner:** Backend 3  
**Responsibility:** Monitor public sources (funding calls and science park events) and produce clean, validated `Opportunity` objects conforming to `contracts/opportunity.json`.

---

## Sources

Per AGENTS.md §5:
1. **Funding Source:** Vinnova open calls (`VinnovaFundingMonitor`)
2. **Events Sources:** Blue Science Park's public WordPress event collection (`BSPEventsMonitor`) and public event pages linked from member company websites (`MemberCompanyEventsMonitor`).

---

## Contract Compliance & Guarantees

- **No Inventions:** Every opportunity requires a live `url` (`http://` or `https://`) and at least one real date (`published`, `deadline`, or `event_date`). Items missing either are dropped immediately.
- **Offline Behavior:** Neither source falls back to the old unverified snapshots. If a live source is unavailable, it returns no opportunities.
- **Badging / Labelling:** Live Vinnova and Blue Science Park records set `is_simulated=False` and `cached_snapshot=False`.
- **Vinnova API:** Joins public calls and application rounds by case number, emits only public rounds with a future closing date, and uses a human-facing URL from Vinnova's `LankLista`. Records without a public call page are dropped instead of linking to the JSON API or an application form. `VINNOVA_UPDATED_SINCE` overrides the default two-year lookback date.
- **Blue Science Park API:** Reads the public `/wp-json/wp/v2/event` collection. It emits only events with an explicitly year-qualified future date in the event content, and uses the record's canonical event page URL. It does not infer a year from the publication date.
- **Member company events:** Reads `fixtures/companies.json` for official company websites, checks each site's `robots.txt`, then fetches only same-host links clearly identified as events, calendars, webinars, seminars, conferences, workshops or meetups. If `robots.txt` is unavailable or disallows a URL, that site/page is skipped. Only explicit full dates in the future are returned, with the company's event page as the source URL; no snapshot or guessed data is used. Requests are bounded by `COMPANY_EVENT_MAX_PAGES` (default 12 per company) and use the shared timeout and identifying User-Agent.
- **Environment names:** Source settings use `MONITOR_REQUEST_TIMEOUT` (default 35 seconds), `VINNOVA_API_URL`, `VINNOVA_UPDATED_SINCE`, `BSP_EVENTS_FEED_URL`, `MEMBER_COMPANIES_PATH` and `COMPANY_EVENT_MAX_PAGES`. `MONITOR_BASE_URL`, `MONITOR_MODEL`, and `MONITOR_API_KEY` are also read for consistency, but these deterministic monitors make no LLM calls.
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
├── company_events.py    # robots-aware member-company event discovery
├── snapshots/            # Empty until a source snapshot is verified and labelled
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
