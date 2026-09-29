# Deliverables checklist

Every deliverable in the challenge brief, mapped to where it lives and how to check it. Section numbers refer to
`bup_hackathon_challenge_md.md`.

## Required (§19)

| # | Deliverable | Where | How to check |
|---|---|---|---|
| 1 | Working application | `backend/`, `frontend/`, `Dockerfile`, `docker-compose.yml` | `docker compose up --build`, open http://127.0.0.1:8080 |
| 2 | Source repository | This repository: code, setup scripts, docs | `README.md` → *Run it*, *Reproduce every number* |
| 3 | Simulator integration | `backend/app/simulator/client.py` (REST + SSE, retry, breaker, stale flag, idempotent allocations) | *System health* page shows the data-source component; `GET /api/health` |
| 4 | Intelligence component | Trained quantile demand model (`backend/app/ml`), risk engine, OR-Tools optimizer with rule-based fallback (`backend/app/intelligence`) | `docs/MODEL.md`, `docs/BENCHMARK.md`; *Forecast & Models* and *Decisions* pages |
| 5 | Operator interface | `frontend/src/pages`: Overview, Network, Decisions, Controls, Forecast & Models, Scenarios & Chaos, Ops assistant, Replay, Data sources, System health, Audit log | Open the console |
| 6 | Architecture diagram | `README.md` §1 and `docs/ARCHITECTURE.md` (Mermaid, rendered by GitHub) | View on GitHub |
| 7 | Deployment | `docker compose up --build`; `scripts/deploy.sh` (versioned, health-gated, automatic rollback); Kubernetes: `kubectl apply -k deploy` (`docs/KUBERNETES.md`) | CI jobs `e2e` (Compose) and `k8s` (kind cluster) deploy on every push |
| 8 | Observability evidence | `/metrics` (Prometheus), `deploy/alerts.yml` (7 alert rules), `deploy/grafana/dashboards/fuelgrid.json`, structured JSON logs, audit trail | `docker compose --profile monitoring up --build` → Grafana http://127.0.0.1:3000 |
| 9 | Resilience demonstration | Resilience matrix in `docs/ARCHITECTURE.md`; fallback tests in `backend/tests`; CI job `e2e` injects a simulator outage and asserts degraded mode and recovery | `docs/DEMO_RUNBOOK.md` step 4 |
| 10 | Load-test evidence | `loadtest/locustfile.py` (workload), `loadtest/results/*_stats.csv` (raw), `docs/LOAD_TEST.md` (analysis) | `bash loadtest/run.sh` then `python loadtest/summarize.py` |
| 11 | Final demo | `docs/DEMO_RUNBOOK.md` (finals script following §22), `round_one_prep.md` §15 (three-minute version) | Rehearse once on the demo machine |

## Recommended (§20)

| Item | Status | Where |
|---|---|---|
| CI/CD | Built | `.github/workflows/ci.yml`: lint → tests → type-check and build → image → smoke test → full-stack deploy and resilience test → Kubernetes deploy and self-healing test |
| Automated tests | Built (94) | `backend/tests` |
| Experiment tracking | Built | `fg_experiments` table, `docs/TUNING.md`, `docs/TUNING_COMBOS.md` |
| Model versioning | Built | Model registry, champion/challenger gate, one-click activation (`docs/ADAPTATION.md`) |
| Decision audit history | Built | *Audit log* page, `fg_audit` and `fg_decisions` tables |
| Deployment versioning | Built | Images tagged with the git SHA; `/api/health` reports the running build |
| Simulation replay | Built | *Replay* page |
| Scenario configuration | Built | `backend/app/scenarios/library.py` (baseline, demand spike, route disruption, shipment delay, depot constraint, combined crisis, scarcity, severe crisis) |
| Automated fallback | Built | Optimizer → rules, trained model → moving average, simulator → cached state |
| Rollback | Built | Policy rollback after 3 failed optimizer cycles, model rollback, deployment rollback (`scripts/deploy.sh`) |

## Crisis scenarios (§10)

| Brief | Scenario name | What the system shows |
|---|---|---|
| Shipment delay | `shipment_delay` | Delivery incident, depot stock projection, re-planned shipments |
| Demand spike | `demand_spike` | Forecast and risk rise, demand-anomaly incident, allocations shift to Dhaka |
| Depot constraint | `depot_constraint` | Depot incident, reduced supply, stations covered from the other depot |
| Regional disruption | `route_disruption` | Road incident, re-routing, recovery when the road reopens |
| Combined crisis | `combined_crisis`, `severe_crisis` | All of the above at once; comparison against doing nothing |

## Resilience rules (§11)

| Brief | Behaviour | Evidence |
|---|---|---|
| ML model unavailable → fallback policy | Moving-average forecaster; optimizer failure → rule-based policy | `backend/tests/test_intelligence.py`, `test_ml.py`; `fg_fallback_total` metric |
| Invalid simulator response → reject, alert | Schema-rejected, alert raised, last good snapshot kept | `backend/tests/test_client.py` (`test_invalid_payload_rejected`) |
| Low prediction confidence → human review | `min_confidence` threshold forces review; auto-approve never applies | `backend/app/intelligence/planner.py`, *Controls* page |
| Dependency unavailable → retry, cached state | Retry with backoff, circuit breaker, cached-state degraded mode | CI job `e2e`; *System health* page |

## Guardrails (§24)

* Simulation only: the only domain write is `POST /v1/allocations`; the console carries a *Simulated environment* banner.
* Human review by default: auto-approve is off after every restart; emergency stop halts planning and execution.
* No secrets in the repository: `.env` is untracked; `.env.example` lists every setting.
* Assumptions and data sources: `docs/ARCHITECTURE.md` (*Assumptions & guardrails*), `docs/MODEL.md` (training data).
