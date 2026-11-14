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

To use it, set `SEED_DIR=fixtures/mock` in `.env` (the default in `.env.example`).

## Switching to real data

Do these in order. Steps marked **(not built yet)** are still on Backend 1's list.

**Before you start** (other owners):
- Backend 3: the monitor snapshots in `agents/monitors/snapshots/` contain only real, reachable URLs, or entries labelled `is_simulated: true`. At least one live source returns data.
- Backend 2: the profiler runs on a real company and passes its tests.
- The team has picked the 3 member companies.

**Backend 1:**
1. Make the database tests independent of the mock folder: move the sample data they need into `db/tests/` **(not built yet)**. Otherwise all `db/` tests skip once `fixtures/mock/` is gone.
2. Add `fixtures/companies.json` with `company_id`, `name` and `website` for each real company.
3. Run `python -m db.ingest` **(not built yet)**. It runs the profiler, monitors and matcher, validates the output against `contracts.models`, and writes `profiles/<company_id>.json`, `opportunities.json` and `recommendations.json` here.
4. Add one company account per profile to `users.json`, with a `demo-…` throwaway password, and add it to the table below.
5. Remove the mock data: `git rm -r fixtures/mock`.
6. Point everything at the real folder: `SEED_DIR=fixtures` in `.env`, and change the default in `.env.example`.
7. Reset the database. Seeding never deletes companies, so the mock companies stay until you do this:
   - Docker: `docker compose down && docker volume rm virtual-science-park_vsp-data`
   - Local: delete `vsp.db`

   Then run `python -m db.seed`.
8. Run `python -m pytest fixtures db contracts api`. The real-data checks that were skipped now run: every profile covers each field or lists it as missing, recommendations point to real claims and opportunities, and every company has an account.
9. Spot-check the labels: `is_simulated` is false only for real data, and hand-saved pages have `cached_snapshot: true`.

Load either folder in code with `from fixtures.loader import load_seed`. It validates everything against `contracts.models`.

`fixtures/tests/` validates both folders against `contracts.models` and checks that all cross-references resolve. Checks that need data are skipped while the files are empty.

Real data still follows the contract rules: every claim has an evidence link, a retrieval date and a stated/inferred label. Anything cached or simulated must be labelled as such.

## Demo accounts

These throwaway passwords exist only for the local demo. The API hashes them with argon2 when it seeds the database.

| Email | Password | Role |
|---|---|---|
| admin@bsp.example.com | demo-admin-2026 | BSP admin |
