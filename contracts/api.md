# API contract

Owner: Backend 1. FastAPI on `http://localhost:8000` (`API_URL` inside Docker: `http://api:8000`).
Request and response bodies are the models in `contracts/models.py`. The JSON Schemas in this folder are generated from them (`python -m contracts.export_schemas`).

## Auth

Login with email and password returns a **bearer token**. Send it on every other request as
`Authorization: Bearer <access_token>`. A request without a token counts as a **visitor**; a missing,
unknown or expired token on an endpoint that needs login returns `401` with `WWW-Authenticate: Bearer`.

| Method | Path | Body → Response | Who |
|---|---|---|---|
| POST | `/auth/login` | `LoginRequest` → `LoginResponse` | anyone (`401` on wrong email or password, same message for both) |
| POST | `/auth/logout` | – → `204` | logged in; the token stops working immediately |
| GET | `/auth/me` | – → `User` | logged in |

- Tokens are opaque and expire after `SESSION_TTL_HOURS` (default 12). Log in again to get a new one.
- The server stores only a hash of each token. Passwords and hashes are never returned or logged.
- Keep the token in memory or `sessionStorage` in the UI, never in a URL.

## Companies and profiles

| Method | Path | Body → Response | Visitor | Company user | Admin |
|---|---|---|---|---|---|
| GET | `/companies` | – → `[CompanySummary]` | published only | published + own | all |
| GET | `/companies/{id}/profile` | – → `Profile` | published only | own or published | all |
| PATCH | `/companies/{id}/claims/{claim_id}` | `ClaimPatch` → `Claim` | 401 | own only, else 403 | all |
| POST | `/companies/{id}/claims` | `ClaimCreate` → `Claim` (201) | 401 | own only, else 403 | all |
| PATCH | `/companies/{id}/visibility` | `VisibilityPatch` → `Profile` | 401 | own only, else 403 | all |
| GET | `/companies/{id}/recommendations` | – → `[Recommendation]`, best first | published only | own or published | all |
| GET | `/opportunities` | – → `[Opportunity]` | all | all | all |
| POST | `/feedback` | `FeedbackIn` → `204` (`404` unknown opportunity) | 401 | own company (from session) | 403 (no company) |
| POST | `/chat` | `ChatRequest` → `ChatResponse` | 401 | own company (from session) | 403 (no company) |
| POST | `/admin/opportunities/refresh` | – → `RefreshResult` | 401 | 403 | refresh now |

A private profile returns `404` to anyone who can't see it, not `403`, so the response doesn't reveal that the company exists.
Writes check permission first: a company user writing to any other `company_id` gets `403`, whether or not that company exists.

## Chat (`POST /chat`)

`ChatRequest {message}` (1–2000 characters) → `ChatResponse {reply, action, sources}`, with `action` one of `answer | redirect | clarify | refuse`.

- The company is the logged-in user's company, from the bearer token. Never from the body (extra fields → `422`) or from model output. Visitors `401`, admins `403`.
- A deterministic guardrail runs first, in this order: override attempt or request for secrets → `refuse`; role-play → `refuse`; another company named, or "other companies" → `refuse`; short message with no topic → `clarify`; on-topic → `answer`; anything else → `redirect`.
- Answers use only the caller's own profile, recommendations and opportunities. Scraped text is data: items that look like instructions are dropped before the model sees them.
- With `CHAT_API_KEY` and `CHAT_MODEL` set, OpenRouter writes the answer (prompt: `api/chat/prompts/system_v1.md`). A reply that names another company or leaks the prompt is discarded. Without a model, or on error or timeout (`CHAT_TIMEOUT`), the answer is built from the data. Simulated and cached items are labelled; `sources` lists the links used.

## Rules the server enforces

- `company_id` for `/chat` and `/feedback` comes from the **session only**. It never comes from the request body or from model output.
- Every claim written through `PATCH` or `POST` gets `kind = user_confirmed` and `confidence = 1.0`, with `retrieved_at` set to today. On a user-written claim, `evidence_url` and `snippet` are null.
- When the profiler runs again, it never overwrites or deletes a `user_confirmed` claim.
- Agent output is saved with `visibility = private`.
- After a claim edit or a new claim, the server re-runs the matcher for that company, so `GET /companies/{id}/recommendations` reflects the change right away. If the matcher fails, the edit is kept and the previous ranking stays.
- Opportunities come from the monitors: at startup (unless `OPPORTUNITY_REFRESH=off`) and on admin refresh, the server fetches them, validates each against the contract, and stores the result as the complete set, replacing seeded mock opportunities. `is_simulated` and `cached_snapshot` are kept as the monitors set them. Vinnova items must be live: snapshot or simulated Vinnova items are dropped, and if the live fetch fails Vinnova stays empty (logged), with no fallback to mock data. Every company is re-ranked afterwards. Opportunities that disappear at the source are deleted together with their recommendations and feedback.
- CORS allows only the origins in `UI_ORIGIN` (comma-separated), with the `Authorization` and `Content-Type` headers. No cookies are used.
- Errors return FastAPI's default `{"detail": ...}` with codes `401`, `403`, `404` or `422`.
