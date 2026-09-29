# System audit

An audit of the whole platform before the finals: security, data protection, correctness of the API surface, performance, and
documentation accuracy. Every finding below was fixed and, where it is code, covered by a test. Nothing is listed as fixed
unless it was re-checked afterwards.

## Summary

| # | Area | Finding | Severity | Status |
|---|---|---|---|---|
| 1 | Data exposure | Database tables were readable through the hosting provider's public REST API (row-level security off on all 8 tables) | High | Fixed: migration `005`, and the database is now a private local container |
| 2 | Reliability | The migration runner split SQL on every `;`, so any function or `DO $$ … $$` block failed to apply | Medium | Fixed: dollar-quote-aware splitter, tested on every shipped migration |
| 3 | Performance | Throughput dropped from ~160 to ~87 requests/s once the trained model was active: its OpenMP threads starved the web server | Medium | Fixed: single-threaded inference + dashboard body serialized once per data version → 146 req/s |
| 4 | Dependencies | Two moderate advisories in `react-router` (open redirect, SSR hydration) | Low (not reachable: static links, no SSR) | Fixed: upgraded to 7.18; `npm audit` reports 0 |
| 5 | API completeness | No FuelGrid endpoints for stations, depots, routes, supply, demand history, allocations, instance; no readiness probe | Medium | Added `/api/v1/*` and `/readyz` |
| 6 | Deployment | No CORS, so a separately hosted console (for example on Vercel) could not call the API | Medium | Added an explicit allow-list (`CORS_ORIGINS`, empty by default) and `VITE_API_BASE` |
| 7 | Abuse / cost | `POST /api/assistant` had no limit and spends free language-model quota | Low | Rate limited (30 per minute, `ASSISTANT_PER_MINUTE`), returns 429 |
| 8 | Memory | Demand history per station and fuel grew without bound on a long-running deployment | Low | Capped at 20,000 ticks per series (about a year) |
| 9 | Configuration | `.env.example` listed a fraction of the settings the application reads | Low | All settings documented |
| 10 | Documentation | Architecture diagram, module list, load-test numbers, test count and database wording were out of date | Low | All rewritten; figures regenerated |

## What was checked and found sound

| Check | Method | Result |
|---|---|---|
| Secrets in the repository | Scanned every commit for API keys, database URLs with passwords, JWTs; confirmed `.env` is untracked and ignored | None found |
| Python dependency vulnerabilities | `pip-audit` on the locked environment | None known |
| Front-end dependency vulnerabilities | `npm audit --omit=dev` | 0 (after finding 4) |
| SQL injection | Searched for SQL built from strings; every statement is parameterized | None |
| Write protection | Every POST/PUT/DELETE route depends on one constant-time API-key check (the only unguarded POST is the assistant, which reads only) | Consistent |
| Input validation | Pydantic bounds on quantities, keys, limits (`limit` clamped 1–2000); unknown ids give 404, bad bodies 422 | Verified by tests |
| Manual and automatic dispatch safety | Same precheck against the source's rules, idempotency key (same key + different body is refused), audit entry | Verified by tests |
| Endpoint smoke test | Called every parameterless GET of the running platform against the real simulator | 34 of 35 return 200; the 35th (`/api/forecast`) correctly returns 422 without its required parameters |
| Load | 50 and 250 concurrent users, trained model active, real simulator ticking | 0 errors in 8,877 requests (see [LOAD_TEST.md](LOAD_TEST.md)) |
| Tests and lint | `pytest` (110 tests), `ruff`, `tsc`, production build | Pass |
| Database migrations | Applied from scratch to an empty PostgreSQL 16 + pgvector container | 5 of 5 applied; row-level security on all 8 tables; bundled model registered |

## Known limits (unchanged, stated plainly)

* One process is the ceiling (about 145 requests/s); scaling out would put one instance in charge of the decision loop.
* Training data is simulated. The independent demo world and the adaptation experiment show behaviour on unseen networks, but no real network data was available.
* `backend/vercel.json` is experimental: serverless functions are a poor fit for a long-running control loop. The supported production path is the Docker image ([DEPLOYMENT.md](DEPLOYMENT.md)).
* The vector extension is installed in the `public` schema (a provider lint warning, not exploitable once row-level security is on and the database is private).

## How to repeat the audit

```bash
cd backend && uv run pytest -q && uv run ruff check app tests
cd ../frontend && npm audit --omit=dev && npm run build
uvx pip-audit                      # from backend/
bash loadtest/run.sh               # with the platform running
backend/.venv/Scripts/python scripts/make_api_doc.py   # regenerates docs/API.md from the code
```
