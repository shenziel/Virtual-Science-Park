# API contract

Owner: Backend 1. FastAPI on `http://localhost:8000` (`API_URL` inside Docker: `http://api:8000`).
Request and response bodies are the models in `contracts/models.py`. The JSON Schemas in this folder are generated from them (`python -m contracts.export_schemas`).

## Auth

Login sets an HTTP-only session cookie. Send it on every request. A request without a session counts as a **visitor**.

| Method | Path | Body → Response | Who |
|---|---|---|---|
| POST | `/auth/login` | `LoginRequest` → `User` | anyone |
| POST | `/auth/logout` | – → `204` | logged in |
| GET | `/auth/me` | – → `User` | logged in (`401` otherwise) |

## Companies and profiles

| Method | Path | Body → Response | Visitor | Company user | Admin |
|---|---|---|---|---|---|
| GET | `/companies` | – → `[{company_id, name, visibility}]` | published only | published + own | all |
| GET | `/companies/{id}/profile` | – → `Profile` | published only | own or published | all |
| PATCH | `/companies/{id}/claims/{claim_id}` | `ClaimPatch` → `Claim` | 401 | own only, else 403 | all |
| POST | `/companies/{id}/claims` | `ClaimCreate` → `Claim` (201) | 401 | own only, else 403 | all |
| PATCH | `/companies/{id}/visibility` | `VisibilityPatch` → `Profile` | 401 | own only, else 403 | all |
| GET | `/companies/{id}/recommendations` | – → `[Recommendation]`, best first | published only | own or published | all |
| GET | `/opportunities` | – → `[Opportunity]` | all | all | all |
| POST | `/feedback` | `FeedbackIn` → `204` | 401 | own company (from session) | 403 (no company) |
| POST | `/chat` | `ChatRequest` → `ChatResponse` | 401 | own company (from session) | 403 (no company) |

A private profile returns `404` to anyone who can't see it, not `403`, so the response doesn't reveal that the company exists.

## Rules the server enforces

- `company_id` for `/chat` and `/feedback` comes from the **session only**. It never comes from the request body or from model output.
- Every claim written through `PATCH` or `POST` gets `kind = user_confirmed` and `confidence = 1.0`, with `retrieved_at` set to today. On a user-written claim, `evidence_url` and `snippet` are null.
- When the profiler runs again, it never overwrites or deletes a `user_confirmed` claim.
- Agent output is saved with `visibility = private`.
- Errors return FastAPI's default `{"detail": ...}` with codes `401`, `403`, `404` or `422`.
