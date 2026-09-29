# Requirements coverage

Traceability from the hackathon documents to FuelGrid: `bup_hackathon_challenge_md.md` (the challenge brief) and `BUP_Fuel_Supply_Simulator_Integration_Guide_Final.md` (the simulator guide). Section numbers refer to those files.

**Legend:** ✅ covered · 🟡 partly covered (what is missing is stated) · ⛔ deliberately not built (reason given) · ⚠️ built but not independently verified

At the end: a summary against the evaluation weights, and the gaps stated plainly.

---

## A. Challenge brief

### §2 The engineering loop: Observe → Detect → Predict → Decide → Simulate → Act → Monitor → Recover

| Step | Status | How |
|---|---|---|
| Observe | ✅ | Adapters read the world (simulator REST, or live feed); synchronizer keeps the latest snapshot and demand history (`app/state`, `app/adapters`) |
| Detect | ✅ | Incident detector (closed roads, outages, late deliveries, demand surges above the model's own 90th percentile, model drift) (`app/decision/engine.py`) |
| Predict | ✅ | Trained quantile demand model, shortage risk with stock-out probability (`app/ml`, `app/intelligence/projection.py`) |
| Decide | ✅ | OR-Tools optimizer with rule-based fallback (`app/intelligence/policies`) |
| Simulate | ✅ | Every recommendation is rolled forward with and without the shipment; three-way comparison "do nothing / rules / optimizer" (`planner.py`, Overview) |
| Act | ✅ | Precheck against the simulator's validation order, idempotent send, approval workflow (`app/decision/engine.py`) |
| Monitor | ✅ | Prometheus metrics, health page, audit log, live activity feed |
| Recover | ✅ | Retry, breaker, cached state, fallbacks, rollback, model retrain/rollback |

### §5 What the team must build
✅ Data collection and management (adapters, store, Supabase persistence), analysis (forecast and risk), decision support (optimizer, approvals), applications and operator tools (React console), monitoring (metrics, health, audit).

### §6 Application requirement (a usable operator-facing application)

| Item the brief lists | Status | Where |
|---|---|---|
| Current fuel inventory | ✅ | Overview chart, Network page (every station and depot, every fuel) |
| Depot and station status | ✅ | Network page (topology map, status badges) |
| Regional fuel demand | 🟡 | Demand history and forecast per station and fuel (Forecast & Models page). No separate region-level roll-up chart |
| Shortage alerts | ✅ | "Needs attention" list, severity badges, alerts in the live feed |
| Projected shortage risk | ✅ | Hours to stock-out and stock-out probability per station and fuel; projected inventory chart |
| Incoming supply | ✅ | Network page: scheduled supply arrivals and shipments in transit |
| Disruptions | ✅ | Active incidents panel, road/station/depot status, topology map |
| Recommended allocations | ✅ | Decisions page and Overview |
| Expected impact of decisions | ✅ | Risk before/after, unmet demand avoided, three-way comparison |
| System alerts | ✅ | Audit log, banners for degraded mode, fallback, rollback, cadence |
| Decision history | ✅ | Decisions page history table (persisted in Supabase); Replay page |
| Service health | ✅ | System health page |

The brief recommends a web application: ✅ React console, light theme, structured layout.

### §7 Intelligence requirement (at least one meaningful capability)

| Capability listed | Status | How |
|---|---|---|
| Demand forecasting | ✅ | **Trained** gradient-boosted quantile model (p10/p50/p90), walk-forward evaluated (`docs/MODEL.md`) |
| Shortage prediction, stock-out probability | ✅ | Roll-forward plus normal-error model from the model's own band |
| Estimated supply arrival | ⛔ | Supply arrivals are taken from the source as given; not predicted |
| Transport delay prediction | ⛔ | Not modelled |
| Anomalous demand | ✅ | Unexplained-surge flag (demand above own p90 three ticks running), data-quality flags |
| Abnormal inventory changes | 🟡 | Live-feed adapter flags large jumps and over-capacity; not applied to the simulator's inventory |
| Bottlenecks, emerging disruptions | 🟡 | Disruptions and delays detected from status/events; no separate bottleneck analytics |
| Constrained optimization, heuristic, hybrid | ✅ | CP-SAT integer program, greedy rule policy, forecast + optimizer hybrid |
| Reinforcement learning | ⛔ | See §8 |
| Generative AI | ✅ | Plain-language briefing and Ops assistant, built from live data; optional Gemini/Groq only reword, replies with unknown numbers are discarded. The brief says LLMs should support the operational system rather than be a chatbot: the assistant is read-only and grounded, decisions never depend on it |

### §8 Reinforcement learning (optional)
⛔ Not built, on purpose. Each planning step is small enough for the optimizer to solve exactly, and the brief asks RL to show a benefit over a reasonable heuristic, which we had no evidence it could. `docs/OPTIONAL_FEATURES.md`.

### §9 Decision support (inspectable recommendations)

| Example field / expectation | Status | Where |
|---|---|---|
| Projected stock-out (hours) | ✅ | Recommendation card |
| Current inventory, expected demand | ✅ | Recommendation card |
| Recommended allocation (liters, source depot) | ✅ | Recommendation card |
| Expected result (risk reduced) | ✅ | "Stockout risk 100% → 4%", unmet demand avoided |
| Why the area is at risk, influencing signals | ✅ | "Why this recommendation" list (signals, forecast level, probability) |
| Relevant constraints | ✅ | Road maximum, depot and station limits stated in the reasons |
| Confidence or uncertainty | ✅ | Confidence score from the model's band; below 0.35 forces human review |
| Alternative actions | ✅ | Other routes with transit time, depot stock, and why-not |
| Humans can inspect important decisions | ✅ | Approval workflow, audit log |

### §10 Crisis and event handling

| Scenario | Status | Evidence |
|---|---|---|
| Shipment delay | ✅ | Scenario `shipment_delay`; incident raised; replanning; benchmark |
| Demand spike | ✅ | Scenario `demand_spike`; forecast uses announced events; benchmark |
| Depot constraint | ✅ | Reserve released for critical stations; `combined_crisis` |
| Regional disruption (route/region unavailable) | ✅ | `route_disruption`: re-routes via the other depot; announced closures avoided at planning time |
| Combined crisis | ✅ | `combined_crisis`, `severe_crisis`, `scarcity` |
| Detect, evaluate, respond, explain, monitor recovery | ✅ | Incidents with recovery entries, recommendations with reasons, replay |

Surprise events during judging: the platform re-reads live state every cycle and handles unknown event types generically; the Scenarios page and Data sources page can create new ones live.

### §11 Application resilience

| Brief's example | Status | Behaviour |
|---|---|---|
| ML model unavailable → fallback allocation policy | ✅ | Forecaster falls back to moving average; optimizer falls back to rules; three failed cycles → automatic rollback to rules |
| Invalid simulator response → reject input, raise alert | ✅ | Schema validation rejects, alert raised, last good snapshot kept |
| Prediction confidence too low → human review requested | ✅ | Flagged in the card, never auto-approved |
| Backend dependency unavailable → retry / cached state / degraded mode | ✅ | Retry with backoff, circuit breaker, cached state, "degraded" banner, database writes buffered |

Also: health checks, timeouts, validation, circuit breaker, rollback: all ✅ (`docs/ARCHITECTURE.md` resilience matrix).

### §12 DevOps requirement

| Item | Status | How |
|---|---|---|
| Reproducible launch (`docker compose up`) | ✅ | `docker-compose.yml`: simulator + FuelGrid; profiles for monitoring and a local database. Image built and smoke-tested |
| Source → Build → Test → Package → Deploy → Health check → Running | ✅ | CI workflow (lint, tests, front-end build, image build, container smoke test); compose health checks |
| CI/CD strongly encouraged | ⚠️ | `.github/workflows/ci.yml` written; the same steps (lint, tests, build, image, smoke) were run locally, but a run on GitHub itself has not been confirmed |

### §13 Advanced DevOps (optional)
⛔ Kubernetes, Helm, Terraform, GitOps, blue/green, canary, autoscaling, queue-based processing: not built. One process handled ~160 requests/s with zero errors; the scaling path is in `docs/LOAD_TEST.md`. Automated rollback exists at application level (optimizer policy rollback, model rollback).

### §14 Observability

| Layer | Status | Where |
|---|---|---|
| Application: request rate, latency, error rate, availability, CPU, memory | ✅ | `/metrics` (Prometheus), System health page (avg/p95, error rate, CPU, memory), Grafana dashboard |
| Intelligence: prediction error, model confidence, alert rate, decision frequency, fallback activation | ✅ | `fg_forecast_mape`, `fg_forecast_confidence`, `fg_open_alerts`, `fg_decision_cycles_total`, `fg_fallback_total`, `fg_model_retrains_total` |
| Logs: warnings, integration failures, decisions, recoveries | ✅ | Structured JSON logs; persisted audit log |
| Distributed tracing (optional) | ⛔ | Not built |

### §15 Health and status
✅ Database, data source, event stream, prediction service, decision engine, API latency and error rate on the System health page and `/api/health`.

### §16 Data
✅ Primary data from the simulator. Additional data is **documented**: five simulator scenarios collected by our collector, plus four independent generated worlds from our generator (both in the repo, cached in `backend/ml_data`). Provenance and assumptions are in `round_one_prep.md` §6 and `docs/MODEL.md`.

### §17 Load testing

| Measurement | Status | Result (`docs/LOAD_TEST.md`) |
|---|---|---|
| Workload definition | ✅ | Locust scenario over dashboard, forecast, history, health, metrics and the full decision path |
| Average, p50, p95, p99 | ✅ | 50 users: avg 13 ms, p50 8, p95 37, p99 68 ms |
| Throughput | ✅ | 40 req/s at 50 users; ~160 req/s at 250 users |
| Error rate | ✅ | 0 failures of 2,407 and of 7,258 requests |
| Concurrency | ✅ | 50 and 250 users |
| Resource usage | ✅ | CPU and memory recorded (one core is the limit; ~160–210 MB) |
| Understanding limits | ✅ | Limit identified, and four real defects found and fixed |

### §18 Security and engineering hygiene
✅ No hard-coded secrets (`.env`, untracked; `.env.example` provided). ✅ External input validated (schemas on simulator and feed data, server-side validation of every control). ✅ Failed requests handled. Extra: optional API key on all write actions.

### §19 Required deliverables

| # | Deliverable | Status | Where |
|---|---|---|---|
| 1 | Working application | ✅ | `docker compose up --build` or the run steps in `README.md` |
| 2 | Source repository (code, setup, docs) | ✅ | GitHub `Team-METAVIS/bup-cse-fest-26-final` |
| 3 | Simulator integration | ✅ | `app/simulator`, `app/state` |
| 4 | Intelligence component | ✅ | Trained model + optimizer |
| 5 | Operator interface | ✅ | `frontend` |
| 6 | Architecture diagram | ✅ | `README.md` (four Mermaid diagrams), `docs/ARCHITECTURE.md` |
| 7 | Deployment | ✅ | `Dockerfile`, `docker-compose.yml` |
| 8 | Observability evidence | ✅ | Metrics, Grafana dashboard, alert rules, audit log, health page |
| 9 | Resilience demonstration | ✅ | Scenarios page (fault injection), tests, degraded-mode behaviour, live recovery in the audit log |
| 10 | Load-test evidence | ✅ | `docs/LOAD_TEST.md`, `loadtest/` |
| 11 | Final demo | ✅ | Script in `round_one_prep.md` §15 |

### §20 Recommended deliverables

| Item | Status | How |
|---|---|---|
| CI/CD | ⚠️ | Workflow written; see §12 note |
| Automated tests | ✅ | 90 tests |
| Experiment tracking | ✅ | `fg_experiments` (Supabase), benchmark, tuning sweep, model backtests |
| Model versioning | ✅ | Registry with champion/challenger and one-click rollback |
| Decision audit history | ✅ | `fg_decisions`, `fg_audit` |
| Deployment versioning | ✅ | Git SHA baked into the image, shown by `/api/health` |
| Simulation replay | ✅ | Replay page over recorded runs; deterministic scenario replays in the benchmark |
| Scenario configuration | ✅ | Scenario library, applicable live |
| Automated fallback | ✅ | Forecaster, optimizer, automatic policy rollback |
| Rollback | ✅ | Policy rollback, model rollback |

### §21 Optional advanced work

| Item | Status |
|---|---|
| Reinforcement learning | ⛔ |
| Multi-agent decision systems | ⛔ |
| Optimization-ML hybrids | ✅ |
| Uncertainty-aware allocation | ✅ safety buffer from the model's own band |
| Counterfactual simulation | ✅ |
| Automated incident detection | ✅ (plus incident memory in Supabase pgvector) |
| Policy rollback | ✅ |
| Drift detection | ✅ |
| Event-driven architecture, streaming | ✅ in-process event bus and SSE |
| Kubernetes, autoscaling | ⛔ |
| Generative-AI operations assistant | ✅ |

Reasons for each ⛔: `docs/OPTIONAL_FEATURES.md`.

### §22 Suggested demonstration story
✅ `round_one_prep.md` §15: normal operation → crisis injected → detection → fallback/recovery → operations continue, plus the independent-world and adaptation parts.

### §24 Constraints and guardrails

| Guardrail | Status | How |
|---|---|---|
| Operate only against the simulation | ✅ | Only the simulator and the generated feed world |
| No real infrastructure, purchases or dispatches | ✅ | Nothing real is reachable |
| No real credentials or private systems | ✅ | Only our own Supabase project and optional free AI keys |
| Distinguish simulated from real | ✅ | "Simulated environment" notice in the console |
| Document assumptions | ✅ | `round_one_prep.md`, `docs/MODEL.md`, `docs/ARCHITECTURE.md` |
| Preserve human review for consequential decisions | ✅ | Auto-approve off by default, bounded, emergency stop |

---

## B. Simulator guide

### §2 Hard rules

| Rule | Status | How |
|---|---|---|
| The simulator is the world, not the brain | ✅ | All intelligence is ours |
| REST is the source of truth; SSE is a hint | ✅ | SSE only wakes a full REST re-read |
| Deterministic world | ✅ | Used for replayable benchmarks |
| Do not modify the simulator | ✅ | Organizer image, unmodified |
| Only allocations may be written from `/v1/*` | ✅ | Only `POST /v1/allocations` |
| `/admin/*` is for self-test | ✅ | Used only by the Scenarios console, lock-step clock, data collection and benchmarks |

### §10 Defensive client checklist

| Item | Status | How |
|---|---|---|
| Endpoints instance, depots, stations, routes, supply-arrivals, events, allocations, metrics, regions | ✅ | `app/simulator/client.py` |
| Demand history with limit (clamped 1-2000) | ✅ | Batched single call, sized to the gap since the last tick |
| POST allocations with idempotency key; 200/201/404/409/422/503 | ✅ | Deterministic key; replay-safe retries; error codes mapped to clear reasons |
| Cancel a pending allocation | 🟡 | Client method exists; not exposed in the console |
| SSE: treat as advisory, re-GET after events | ✅ | |
| Watch `X-Simulator-Stale: true` | ✅ | Marks data stale, suspends auto-dispatch |
| `stream_disconnect` fault (503) | ✅ | Backoff and reconnect; polling fills the gap |
| Queue overflow → reconnect and re-fetch | ✅ | Full REST re-read after every reconnect |
| No Last-Event-ID replay | ✅ | Handled by re-reading state |
| 15 s silence is normal | ✅ | Not treated as a disconnect |
| Injected faults (latency, unavailable, error_rate, stale_data) | ✅ | Retry, breaker, cached state, degraded mode; all injectable from the Scenarios page |
| Validation order (§5.2) | ✅ | Mirrored locally so doomed shipments are never sent |
| Protect the simulator | ✅ | Concurrency cap and single-flight refresh (added after load testing hung the simulator) |

---

## C. Against the evaluation weights (§23)

| Criterion | Weight | Where the evidence is |
|---|---:|---|
| Working product & user experience | 20% | Console (11 pages), controls, live updates, replay, demo world |
| Intelligence & decision quality | 20% | Trained model (`docs/MODEL.md`), optimizer benchmark (`docs/BENCHMARK.md`), adaptation experiment (`docs/ADAPTATION.md`), tuning (`docs/TUNING_COMBOS.md`) |
| Architecture & integration | 15% | Canonical model, two adapters, engines, diagrams (`README.md`, `docs/ARCHITECTURE.md`) |
| DevOps & engineering quality | 15% | Docker, compose, monitoring profile, CI workflow, 90 tests, migrations, versioned models |
| Resilience & incident response | 10% | Resilience matrix, fault injection, breaker, fallbacks, rollback, recovery evidence |
| Observability & performance | 10% | Prometheus, Grafana, health, audit, load test (`docs/LOAD_TEST.md`) |
| Demo & problem understanding | 10% | `round_one_prep.md` (internals, Q&A, glossary, demo script) |

## D. Gaps, stated plainly

- Training data is simulated; there was no real network data.
- No region-level demand roll-up view; no supply-arrival or transport-delay prediction.
- The CI workflow has not been confirmed on GitHub itself.
- The Gemini/Groq layer is tested against mocked endpoints only (no keys were available).
- Planning only every several hours is throughput-limited by design (one shipment per road and fuel per plan); the lock-step clock keeps planning per tick.
- One process is the ceiling at about 160 requests/s.
- Reinforcement learning, multi-agent control, Kubernetes and distributed tracing were deliberately not built.
