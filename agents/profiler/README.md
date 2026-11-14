# Profiler agent

Owner: **Backend 2**. Folders: `agents/profiler/` only.

Turns a member company's public website into a contract-valid
`contracts.models.Profile`: every claim carries a source, a retrieval date and a
`stated` / `inferred` label, and every profile area is either covered or listed
in `missing_fields`.

## Run it

```bash
# model runtime comes from the environment (see .env.example)
export MODEL_RUNTIME=ollama MODEL_NAME=llama3.1 OLLAMA_HOST=http://localhost:11434

python -m agents.profiler \
  --company-id nordsense --name "NordSense AB" --website https://nordsense.example
```

It prints the profile, validates it as `Profile`, and caches it (plus the fetched
pages) so a later run works offline.

* `--html page.html` — use a page saved by hand. Every claim is then labelled
  `cached_snapshot: true`.
* `--existing profile.json` — keep `user_confirmed` claims from a previous run.
* `--out path.json` — write the profile somewhere else (for Backend 1 to drop
  into `fixtures/profiles/`).

From code:

```python
from agents.profiler import ProfilerAgent

agent = ProfilerAgent()
profile = agent.profile_company("nordsense", "NordSense AB", "https://nordsense.example")
agent.save(profile)          # <cache>/nordsense.json
```

`profile_company` raises `FetchError` when the site cannot be reached and no
cache exists, and `ExtractionError` when the model's answer cannot be validated
and `fallback_on_llm_error=False`.

## What the code enforces

| Rule | Where |
|---|---|
| An identifying `User-Agent` on every request | `fetch.py` |
| `robots.txt` obeyed — a disallowed URL raises, never fetches | `fetch.py` |
| One request at a time per host (`PROFILER_MIN_INTERVAL`, default 2 s) | `fetch.py` |
| Pages and profiles cached; a cached page keeps its **original** retrieval date | `fetch.py` |
| A `stated` claim must quote the page **verbatim**, or it is dropped | `extract.py` |
| `geographic_focus` only as a `stated` claim (AGENTS.md §1) | `extract.py` |
| The agent never emits `user_confirmed` | `extract.py` |
| One evidence URL per claim: the page it was read from | `extract.py` |
| Unsupported areas go to `missing_fields`, never invented as claims | `extract.py` |
| `user_confirmed` claims survive a re-run and are never overwritten | `profiler.py` |
| Output validated as `contracts.models.Profile` before saving | `profiler.py` |
| A re-run never un-publishes a profile | `profiler.py` |
| Only `http(s)` URLs are fetched: `file://`, `data:`, `ftp:` are refused before any request | `paths.py`, `fetch.py` |
| Cache file names are hashes, and the resolved path must stay inside the cache directory | `paths.py`, `fetch.py` |
| `load(company_id)` validates the slug and the path, so `../` cannot name a file | `profiler.py` |
| `--html` / `--existing` must be existing regular files; `--out` needs a real directory | `paths.py` |
| The page cache records only the retrieval date; the URL is never written to disk | `fetch.py` |

Dropped claims are logged with the reason. Nothing is repaired into a different
fact: a model answer that fails validation is retried once and then raised.

## Untrusted input

A URL, a `company_id` or a file path can come from a model answer, a request
body or a command line, so none of them is trusted:

* [`paths.py`](paths.py) is the only place that turns one into a filesystem
  path. `contained()` resolves the result and refuses anything outside its
  directory, which is what stops `../../etc/passwd` from naming a cache file.
* `urllib` understands `file://` and `data:`, so `check_url()` allows only
  `http(s)` with a host — a "website" of `file:///etc/passwd` fails before the
  transport runs and never reaches the page cache.
* The cache name is the SHA-256 of the URL, never the URL itself, and the
  sidecar next to a cached page holds only the retrieval date, so an untrusted
  URL is never repeated into a file.

## Two extractors

1. **Model** — any OpenAI-compatible endpoint (`MODEL_RUNTIME=api`) or Ollama
   (`MODEL_RUNTIME=ollama`). The prompt is a versioned file:
   [`prompts/extract_claims.md`](prompts/extract_claims.md).
2. **Deterministic fallback** — used when no model runtime is configured, or
   when a model answer fails after the retry. It only quotes sentences from the
   page and marks a claim `stated` only when the sentence itself makes the
   statement (`"We develop …"`, `"Based in …"`). It is the floor, not the goal:
   field attribution is a keyword heuristic.

Page text is always treated as data. The prompt says so explicitly, and
`<script>`/`<style>` content is stripped before the model sees it.

## Labelling

* `Claim.cached_snapshot` is `true` for any claim read from the cache or from a
  page saved by hand — the UI can badge it.
* `Profile.is_simulated` stays `false`: these are real pages, read now.
* A profile built from `fixtures/mock/` data is Backend 1's simulated seed and
  is already labelled there.

## Configuration

All of it lives in [`config.py`](config.py). Environment variables, all read at
runtime and never hard-coded:

| Variable | Default | Purpose |
|---|---|---|
| `MODEL_RUNTIME` | *(empty)* | `api`, `ollama`, or empty for the fallback |
| `MODEL_NAME` | *(empty)* | model id |
| `MODEL_API_KEY` | *(empty)* | only for `api` |
| `MODEL_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `OLLAMA_HOST` | `http://localhost:11434` | local model server |
| `PROFILER_CACHE_DIR` | `agents/profiler/cache` | profile + page cache |
| `PROFILER_MIN_INTERVAL` | `2.0` | seconds between requests to one host |
| `PROFILER_USER_AGENT` | Blue Science Park demo UA | identifying header |

Backend 1: the profiler imports `httpx` (already pinned) and nothing else new.

## Tests

```bash
python -m pytest agents/profiler -q
```

They run offline — the HTTP transport and the model are fakes:

* contract validity: ids, evidence URLs, `stated` ⇒ verbatim snippet;
* every profile area covered **or** in `missing_fields`, never both;
* a paraphrased quote is dropped, a fake inferred quote loses its snippet;
* `geographic_focus` is rejected unless stated;
* `user_confirmed` is never produced by the agent and never overwritten by a
  re-run (including claim-id collisions);
* cached pages, cached dates, `robots.txt` denial, throttling, fetch failure;
* model answers are retried then raised, never silently patched.

## Known limits / next step

* Only the company's own site is read. External sources (news, registries) would
  add `inferred` claims — that is the next step, and it must never override a
  `stated` claim.
* One page, not a crawler: `/about` and `/products` pages fetch better profiles
  than a JavaScript home page. Use `--html` for those.
* Swedish pages work; values are not translated, because a translation would no
  longer be a verbatim quote.
