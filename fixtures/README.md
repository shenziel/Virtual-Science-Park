# Fixtures

Owner: Backend 1. Seed data loaded by the API. **The real companies are not chosen yet**, so the data files are empty until then.

| File | Shape | Status |
|---|---|---|
| `profiles/<company_id>.json` | `Profile` | empty until the companies are chosen; file name must equal `company_id` |
| `opportunities.json` | `[Opportunity]` | empty, filled from the monitors' output |
| `recommendations.json` | `[Recommendation]` | empty, filled from the matcher's output |
| `users.json` | `User` + `password` | admin only; add one company account per profile |

## Mock data (`fixtures/mock/`)

Until the real data is in, use the simulated data in `fixtures/mock/`. It has the same layout: 3 companies, 6 opportunities, recommendations and demo accounts. Everything in it is labelled `is_simulated: true`, names end in "(simulated)", and URLs use `example.com`.

- Use it: set `SEED_DIR=fixtures/mock` in `.env` (the default in `.env.example`).
- Remove it: `git rm -r fixtures/mock` and set `SEED_DIR=fixtures`. Its tests are inside the folder and go with it; nothing else changes.

Load either folder in code with `from fixtures.loader import load_seed`. It validates everything against `contracts.models`.

`fixtures/tests/` validates both folders against `contracts.models` and checks that all cross-references resolve. Checks that need data are skipped while the files are empty.

Real data still follows the contract rules: every claim has an evidence link, a retrieval date and a stated/inferred label. Anything cached or simulated must be labelled as such.

## Demo accounts

These throwaway passwords exist only for the local demo. The API hashes them with argon2 when it seeds the database.

| Email | Password | Role |
|---|---|---|
| admin@bsp.example.com | demo-admin-2026 | BSP admin |
