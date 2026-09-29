# FuelGrid — Round One Preparation

Use this page to explain FuelGrid to anyone: what it does, how every part works inside, how decisions are made, how the model was trained and on what data, and how it copes with a changing world. Plain words first; the technical detail is there when a judge digs in. A glossary is at the end.

> Everything here is built and tested. Numbers come from our own runs; raw results are in `docs/BENCHMARK.md`, `docs/MODEL.md`, `docs/ADAPTATION.md`, `docs/TUNING.md` and `docs/LOAD_TEST.md`. Diagrams and graphs are in the `README.md`.

---

## 0. The four questions judges asked, answered up front

| Judges' question | Short, true answer |
|---|---|
| **"Did you train a model?"** | **Yes.** A gradient-boosted quantile model (scikit-learn), trained on 188 demand series / 226,560 observations from two very different environments, evaluated walk-forward against simple baselines, versioned in a registry, and retrained automatically. It does **not** read the simulator's published demand pattern. (Section 6) |
| **"Real situations are dynamic. How does mathematics cope?"** | Four layers. (1) The optimizer **re-solves from the live measured state every cycle**, so nothing stale is trusted. (2) The model **adapts online** within a few ticks of a level shift. (3) **Drift** is detected, a challenger model is trained and only replaces the champion if it is clearly better on recent data. (4) Every part of the network (stations, roads, fuels) is data, so the world can **change while running**. (Section 7) |
| **"Is it using the simulator? Is it tied to it?"** | The simulator is **one adapter of two**. The core works on a canonical data model. A second adapter, the **live feed**, lets any system push topology and telemetry over HTTP and pull dispatch orders back. We proved it on an independent generated network with different topology, four fuels (including LPG), a different clock, weekly seasonality and injected shocks. One click switches sources. (Section 8) |
| **"If it's maths, how does it handle dynamic things?"** | Same as row 2, plus: maths gives the *decision*, learning gives the *inputs*. The demand the optimizer plans against is learned from data and corrected online; the constraints it obeys (roads, stock, capacity) are re-read every cycle. (Sections 5 and 7) |

---

## 1. The problem in plain words

A country has fuel depots and fuel stations; trucks carry fuel along fixed roads. Things go wrong: a road closes, a delivery is late, a city suddenly needs more fuel, a station shuts. If nobody reacts in time, a station runs dry.

The operations team needs a screen that answers: *What is the situation? Where will fuel run out and how sure are we? What should we send, from where, how much? What happens if we do? Is the system itself healthy?*

The organizers provide a practice world (a simulator): 2 depots, 4 stations, 6 roads, 3 fuels, time in 15-minute steps, and exactly one write action — create a shipment.

---

## 2. What FuelGrid is

An operations console plus the decision "brain" behind it. Every time the clock ticks it runs:

| Step | Plain meaning | Which engine does it |
|---|---|---|
| Observe | Read fuel levels, roads, deliveries, events, demand | Data-source adapter + synchronizer |
| Detect | Spot closures, delays, surges, model drift | Incident detector |
| Predict | Estimate demand for the next 32 steps with an uncertainty band | Forecast engine (trained model) |
| Assess | Roll stock forward, work out when and how likely a station runs out | Risk engine |
| Decide | Choose the best shipments under every real limit | Planner + optimizer (OR-Tools) |
| Simulate | Show what the plan changes, and compare with doing nothing | Impact and shadow-comparison engine |
| Act | Check against the simulator's own rules, then send after approval | Decision engine + executor |
| Monitor | Score, health, alerts, audit | Metrics, health, audit log |
| Recover | Fall back, retry, roll back, relearn | Resilience layer + model manager |

Screens: Overview (briefing, risks, comparison, live feed), Network, Decisions, Controls, Forecast & Models, Scenarios & Chaos, Ops assistant, Replay, Data sources, System health, Audit log.

---

## 3. Inside the system: the engines and how they work together

```
 DATA SOURCES            CORE (source-independent)                                 OUTPUTS
 ─────────────      ─────────────────────────────────────────────────────    ────────────────
 Simulator adapter ┐                                                          Operator console
                   ├─► Canonical model ─► State store ─► Forecast ─► Risk ─►  (live via SSE)
 Live-feed adapter ┘   (fuels are text)     (snapshot,    engine      engine        │
   ▲ topology/telemetry                      demand                       │         ▼
   │ in; orders out                          history)          Planner + optimizer ─► Decision engine ─► Orders
   │                                                              (OR-Tools, fallback)    (approve, precheck,   to source
   │                                                                                       audit)
   └── Model manager: online adaptation · drift · retrain · champion/challenger · rollback
       Supabase: decisions, audit, ticks, experiments, incident memory (pgvector), models, settings
```

| Engine | What it is | Inputs | Output | Technique |
|---|---|---|---|---|
| **Data-source adapters** | Translators from any source into one canonical model | Simulator REST + SSE, or the live feed API | Snapshot: stations, depots, routes, arrivals, events, shipments, demand history | HTTP client with retry, breaker, validation; feed adapter with quality scoring |
| **Synchronizer + store** | Keeps the freshest known world in memory | Adapter reads (about twice a second) | Latest snapshot + accumulated demand history | REST is truth, push events are only hints; single-flight refresh; reset detection |
| **Forecast engine** | Predicts demand per station and fuel | Demand history, clock, announced events | Median forecast, 10th and 90th percentile per step, confidence | **Trained gradient-boosted quantile model**, online correction, fallbacks |
| **Risk engine** | Turns forecast into shortage risk | Stock, in-flight shipments, forecast | Hours to stock-out, probability, severity per station and fuel | Deterministic roll-forward + normal-error model |
| **Incident detector** | Notices trouble | Events, statuses, delays, model error | Incidents with start and recovery | Rules on live state; model surge and drift signals |
| **Planner + optimizer** | Chooses the shipments | Needs, routes, depot stock, limits | A set of (route, fuel, liters) | **Integer optimization (OR-Tools CP-SAT)**, rule-based fallback |
| **Impact engine** | Explains what a plan does | Plan, forecast | Risk and unmet demand before/after, alternatives, "do nothing / rules / optimizer" comparison | Counterfactual roll-forward |
| **Decision engine** | Runs the workflow | Plan | Stable proposals, approvals, executed shipments, audit | Reconciliation, review gate, auto-approve rules, precheck, idempotent execution |
| **Model manager** | Owns the model's life | Live history, errors | Champion model, retrain results, versions | Online bias, drift trigger, champion/challenger gate, registry |
| **Event bus + stream** | Pushes changes to the screen | Every decision, alert, link change | Live UI updates | In-process publish/subscribe, server-sent events, replay after reconnect |
| **Incident memory** | "Seen this before?" | Incident signature | Closest past cases and outcomes | Supabase pgvector similarity (12 numbers) |
| **Assistant + briefing** | Plain-language answers | Live facts | Sentences | Templates from data; optional Gemini/Groq rewording with number check |

**How they collaborate on one cycle** (about 30 milliseconds end to end): the adapter delivers a fresh snapshot; the store updates history; the forecast engine produces distributions; the risk engine scores every station-fuel pair; the planner turns risky pairs into needs; the optimizer solves; the impact engine attaches before/after numbers and alternatives; the decision engine reconciles proposals with the ones already on screen, applies the approval rules, prechecks and sends approved shipments; the event bus pushes everything to the console; the model manager compares the last forecast with what actually happened.

---

## 4. How a decision is made, step by step

1. **Snapshot.** Current stock at every depot and station, road and site status, shipments in flight, announced events.
2. **Forecast.** For each station and fuel: expected demand for each of the next 32 ticks, plus a 10th and 90th percentile band. The band width becomes the uncertainty.
3. **Roll forward.** Start from current stock, add in-flight deliveries when they will land, subtract forecast demand tick by tick. The first tick stock reaches zero gives *hours to stock-out*. The chance that total demand exceeds stock plus incoming gives *stock-out probability*.
4. **Severity.** CRITICAL if stock-out within 8 ticks (2 hours); WARNING if a stock-out is projected or probability is above 50%; WATCH above 15%; otherwise OK.
5. **Need.** For a station at risk (or below 35% of tank), the fuel to add is: forecast demand over the cover target (default 32 ticks) **plus a safety buffer** (2.0 standard deviations of forecast error, from the model's own uncertainty) **minus** stock expected on arrival **minus** deliveries already coming, capped by free tank space.
6. **Optimize** (next section) to split the needs across roads and depots.
7. **Impact.** For each recommended shipment, roll the world forward again *with* it: stock-out probability before/after, unmet demand avoided. Also compute what the alternative policy and doing nothing would have left unmet.
8. **Review gate.** If forecast confidence is below 0.35 the recommendation is flagged for a person and can never be auto-approved.
9. **Reconcile.** A recommendation for the same (station, fuel, road) keeps its ID from the previous cycle, so the operator's list never shuffles.
10. **Approve.** A person clicks Approve — or auto-approve sends it, if allowed by the rules (master switch on, within per-cycle budget, within the per-shipment cap, confidence and severity thresholds met, data not stale).
11. **Precheck.** The shipment is checked against the simulator's exact validation order (status, road maximum, depot stock, sending limit, tank headroom) and against announced closures. A doomed shipment is never sent.
12. **Send and record.** Idempotent send (unique ticket), shipment applied to local state at once, audit entry, event pushed to the screen.

---

## 5. How the optimization works

The problem: several stations need fuel, several roads could carry it, each road has a maximum load, each depot has limited stock and can only send so much per tick, each tank has limited room. Find the best set of shipments.

**Formulation (OR-Tools CP-SAT, integer programming):**
- Decision: an integer number of 100-litre units on each (road, fuel), between 0 and `min(road maximum, tank headroom)`.
- Hard limits: depot stock minus a reserve (the reserve is released if the road serves a critical station); depot sending capacity per tick minus what is already pending; only roads that are open, between open sites, and not about to close.
- For each station and fuel with a need: shortfall = need − delivered. Delivery may not exceed need + 5 units.
- **Objective (minimize):** for each shortfall, `weight × 10 × (shortfall + deep_shortfall)` where `deep_shortfall` is the part beyond half the need (a convex, **fairness** penalty, so scarce fuel is spread instead of fully serving one station and starving another); `weight` = severity (30 critical, 10 warning, 3 watch, 1 ok) × urgency `(1 + 4/(1 + ticks to stock-out))`. Plus a small cost for transit time and volume as a tie-breaker (prefer short roads, ship less).
- Deterministic: one worker thread, fixed seed, 2-second limit. Same input, same answer.
- Anything under 500 L is dropped unless critical.

**Fallbacks:** if the optimizer errors, times out or is infeasible, a greedy rule-based policy (most urgent first, nearest depot first) takes over immediately; three failed cycles in a row roll the platform over to the rule policy until an operator restores the optimizer.

**Tuned by experiment, not by feel:** cover target 32 and safety buffer 2.0 were chosen from a parameter sweep on the hardest scenarios (`docs/TUNING_COMBOS.md`): severe multi-failure service rose from 97.75% to 98.60%.

---

## 6. The trained model: what it is, what it was trained on, how good it is

**What it is.** Three gradient-boosted regression models (scikit-learn `HistGradientBoostingRegressor`, quantile loss) predicting the 10th, 50th and 90th percentile of demand, so we get a forecast and an honest uncertainty band. One **pooled** model serves every station and fuel: demand is divided by a recent-average scale, so it learns *shapes and dynamics*, not the size of any one station. That is why it can forecast a station it has never seen.

**Features (18), all source-neutral:** hours ahead; time of day and day of week (as circular values); weekend flag; the last observation; averages over the last 4, 16 and one day; demand at the same time yesterday, the day before and last week (missing values allowed); the announced event multiplier at the target time and now; tick length; recent volatility; short-vs-daily level ratio. **No station identity, no fuel identity, no simulator demand profile.**

**Where the data came from (all simulated; no real-world data was available or used):**

| Dataset | How it was produced | Size |
|---|---|---|
| **Simulator, 5 scenarios** (baseline, demand spike, combined crisis, scarcity, severe multi-failure) | Our collector (`python -m app.ml.collect --sim`) resets the organizer's simulator, injects each scenario through its admin API, steps 576 ticks (6 days), and reads `/v1/demand-history` and `/v1/events` | 60 series |
| **Four independent generated worlds** (seeds 1–4) | Our world generator (`app/worldgen/world.py`): 3 depots, 8 stations, 4 fuels, 30-minute ticks, smooth two-peak daily curves, weekday/weekend seasonality, trend, autocorrelated noise, with demand shifts, shifted peaks and surges injected mid-run | 128 series, 1,500 ticks each |
| **Total** | | **188 series, 226,560 observations**, sampled to 250,000 training rows |

Training takes about 22 seconds. Model file: 600 KB, stored in the repository and in Supabase (`fg_models`).

**How well it works** (walk-forward on data the model did not train on; error = WAPE, total absolute error divided by total demand, lower is better; horizon = ticks ahead):

| Experiment | Trained model | Same as now | Same as yesterday | Moving average | Hand-set expert | 80% band holds |
|---|---:|---:|---:|---:|---:|---:|
| **E1** held-out simulator scenario (h=8) | **6.3%** | 24.6% | 6.9% | 34.0% | 5.1% | 78% |
| **E2** unseen generated network (h=8) | **13.9%** | 38.0% | 17.5% | 38.2% | n/a | 83% |
| **E4** future window, all data (h=8) | **13.5%** | 37.7% | 16.9% | 38.7% | n/a | 82% |
| **E3a** zero-shot: trained on simulator only, tested on new world (h=8) | 17.6% | 38.0% | 17.5% | 38.2% | n/a | **42%** |
| **E3b** zero-shot: trained on worlds only, tested on simulator (h=8) | 10.5% | 24.6% | 6.9% | 34.0% | 5.1% | 84% |

**Honest reading.**
- The trained model beats the simple baselines at every horizon on unseen data, and its uncertainty band is well calibrated (about 80% of outcomes fall inside the 80% band) when it has seen varied worlds.
- On the simulator the *hand-set expert* is slightly better (5.1% vs 6.3%) because that formula **is** how the simulator generates demand, so 5% is essentially the noise floor. The trained model gets within about one point without being told the formula, and works where no such formula exists.
- A model trained on the simulator **alone** looks fine on error but is dangerously over-confident on a new network (band holds only 42%). That is exactly why FuelGrid retrains on the new network's own data, and why the champion was trained on both worlds.
- What it relies on most (permutation importance): the value at the same time yesterday, then the day before, last week, and the latest observation.

**How it keeps learning:** see Section 7.

---

## 7. How FuelGrid copes when the world keeps changing

| Layer | Timescale | What happens |
|---|---|---|
| **1. Re-plan from live state** | every cycle (about 30 ms) | Nothing from the past is trusted. Stock, roads, capacities and in-flight shipments are re-read and the optimizer is re-solved. Forecast errors cannot pile up. |
| **2. Online adaptation** | a few ticks | Each tick, the model's own next-step forecast is compared with reality. A smoothed correction per station and fuel follows level shifts immediately. Demand above the model's own 90th percentile for three ticks in a row is flagged as an **unexplained surge**. |
| **3. Drift → retrain → gate → promote** | scheduled (every 480 ticks) or on drift | If rolling forecast error exceeds 25%, an incident is raised and a **challenger** model is trained on the history collected so far (plus a base corpus while history is short). Challenger and current **champion** are both scored on the most recent window the challenger did not train on. Only a win of at least 3% replaces the champion; the old model stays in the registry for **one-click rollback**. |
| **4. Data that changes shape** | any time | Stations, depots, roads and fuels are data, not code. A new station appears (or disappears) when the topology is updated; it uses a moving average until it has 24 observations, then the model takes over. |
| **5. Messy data** | every reading | Negative, impossible or unknown-entity values are rejected with a reason; values above capacity are clamped and flagged; silent sensors keep their last value and are listed; a feed that goes quiet is reported stale and auto-dispatch pauses. A data-quality score is on screen. |

**Measured** (`docs/ADAPTATION.md`, graph in README): the same unseen network and the same five surprises — demand +40% (t=150), daily peaks shifted 3 hours (t=300), three sensors silent (t=450), a new station (t=520), an unannounced surge (t=600) — replayed under five forecasting approaches feeding the same optimizer in a closed loop.

| Approach | Mean 1-step forecast error | Service level | Model retrains |
|---|---:|---:|---:|
| Hand-set expert profile | 20.7% | 99.97% | none |
| Moving average | 25.8% | 99.98% | none |
| **Trained model, frozen** | **14.1%** | 99.98% | none |
| Trained + online adaptation | 14.0% | 99.98% | none |
| Trained + adaptation + retraining | 14.0% | 99.97% | 3 run, 1 promoted, 2 rejected |

**Honest reading of this experiment:**
- On a network it has never seen, the trained model forecasts about **32% better than the hand-set profile and 45% better than a moving average**, and stays in the 12-17% range around every surprise while the baselines sit at 19-29%.
- **Service level is about 99.98% for every approach.** That is not a flaw in the test, it is the design working: because the optimizer re-plans hourly from measured stock, forecast errors are corrected before they turn into stock-outs. Forecast accuracy shows up in early warnings, safety stock and risk numbers rather than in final service.
- **Online correction adds little on top of the trained model**, because the model already forecasts from recent history (its inputs include the latest observation and the day's average), so it follows level shifts by construction. After the demand jump it kept error at 13% where the frozen model briefly rose to 17%.
- **A shifted daily pattern (peaks moving 3 hours) is the hardest surprise for every approach.** The trained model's error rose from 13% to 20% and settled near 17-19%, still better than the baselines (23-27%). A challenger trained at t=482, 180 ticks after the shift, was **rejected** because it did not clearly beat the champion. It shows the gate protecting us from a churn of marginal models, and shows that pattern changes need more post-change history before retraining pays off.
- Planning only every 6 hours is not viable with this planner (one shipment per road and fuel per plan), which we document as a limitation.

---

## 8. Independence from the simulator

**One contract, two adapters.** The core only knows the canonical model (`app/domain`) and the `DataSource` contract (`app/adapters/base.py`). Fuels are plain text; nothing in the forecast or optimizer names a station, product or region.

| Adapter | How it connects | Notes |
|---|---|---|
| **Simulator** | REST for state, server-sent events as change hints, one write endpoint | Has an admin console for crises and faults |
| **Live feed** | `POST /api/feed/topology`, `POST /api/feed/telemetry`; orders pulled from `GET /api/feed/orders` (optional webhook); progress via `POST /api/feed/orders/{id}/ack` | Validates and scores quality; handles changing topology; goes stale when silent |

**Proof it is not simulator-bound:**
- An **independent world** (3 depots, 8 stations, 4 fuels incl. LPG, 30-minute ticks, weekly seasonality, injected shocks) runs in-process (one click) or **from outside over plain HTTP** (`python -m app.worldgen.run`), which imports nothing from FuelGrid.
- A test runs the full loop (feed → forecast → optimize → approve → world executes) on it and keeps service healthy.
- The console can **switch source live** without a restart.

**Connecting a real company** would mean writing a small gateway that translates their systems into the topology/telemetry calls above and executes the orders it pulls. No change to the core.

---

## 9. Controls and safety for real use

| Control | What it does |
|---|---|
| Start / pause engine | Stops or resumes planning and dispatch |
| **Emergency stop** | One button: pause, switch auto-approve off, withdraw pending recommendations |
| Auto-approve (master switch) | Off by default; every shipment waits for a person |
| Auto-approve rules | Budget per cycle, largest single shipment, minimum confidence, minimum severity |
| Approve all / reject all / replan now | Bulk actions on the pending list |
| Planning parameters | Policy, cover target, safety buffer, depot reserve, horizon, re-plan cadence |
| Model controls | Demand model choice, online adaptation, auto-retrain, schedule, retrain now, activate any version |
| Resilience thresholds | Stale-data limit, rollback threshold |
| Data source | Switch source, run the demo world, change it while running |
| Operator API key | Optional; protects every write action (reading stays open) |

Every control is validated on the server (bad values are refused), written to the audit log with old and new value, and **saved in Supabase** so it survives a restart. After a restart, **auto-approve is deliberately left off** and the log says so.

---

## 10. What happens when something breaks

| What breaks | What FuelGrid does |
|---|---|
| Source slow or down | Retries with growing waits; after 5 failures stops calling for 3 s, then probes; meanwhile shows last good data, labeled degraded; auto-dispatch pauses |
| Source sends nonsense | Rejected, alert raised, last good data kept |
| Data older than the limit | Warning; auto-dispatch pauses |
| Live-update connection drops | Reconnects with backoff; polling fills the gap; state re-read after reconnect |
| Optimizer fails | Rule-based policy immediately; after 3 in a row it becomes the active policy with a restore button |
| Trained model missing or failing | Moving average until it works |
| Model drifts | Incident and alert; challenger trained; promoted only if clearly better |
| A new model is worse | Not promoted; if a promoted one later disappoints, roll back in one click |
| A shipment would be refused | Not sent; reason shown; replanned |
| Sending fails midway | Unique ticket makes retry safe (never a double shipment) |
| Database down | Writes buffered and retried; console served from memory |
| Simulator or world reset | Clock going backwards is detected; caches cleared |
| Too many callers | Simulator calls capped; simultaneous refreshes and decide-now requests share one run |
| AI service busy or wrong | Rotate to another free model, then the backup provider, then the built-in answer; replies with unknown numbers are discarded |

---

## 11. Observability, deployment, testing

- **Observability:** Prometheus metrics (request rate/latency/errors, source health, breaker, fallbacks, open alerts, forecast error and confidence, model retrains, allocations, service level, database), structured logs, a health page, ready-made Grafana dashboard and alert rules.
- **Deployment:** `docker compose up --build` (simulator + FuelGrid); optional profiles for Prometheus/Grafana and a local database; multi-stage image with health check and non-root user; CI runs lint, tests, front-end build, image build and a start-up smoke test.
- **Testing:** 87 automated tests: optimizer constraints, fallbacks and rollback, decision workflow and stable IDs, precheck, feed validation and quality, dynamic topology, closed loop on an unseen network, model features/calibration/serialization/adaptation/gate, controls and safety, assistant grounding, API contract, load-test-derived hardening.

---

## 12. Measured results

**Decision quality** (`docs/BENCHMARK.md`): the same crisis replayed under "do nothing", "simple rules" and our optimizer:

| Situation | Do nothing | Simple rules | FuelGrid |
|---|---:|---:|---:|
| Normal (2 days), demand jump, road closed, late deliveries, combined crisis | 43–46% | 100% | 100% |
| Severe multi-failure (3 days) | 27% | 98.6% | 98.6% |
| Fuel scarcity, supply cut to a quarter (3 days) | 21% | 93.1% | **94.6%** |

Honest reading: doing nothing fails; both smart policies handle normal and medium crises; the optimizer's edge appears under real shortage (about a fifth less unmet demand than simple rules in the scarcity test).

**Load** (`docs/LOAD_TEST.md`): 50 users, 2,407 requests, 0 failures, 95% under 37 ms, 99% under 68 ms; 250 users, 7,258 requests, 0 failures, about 160 requests/s (one processor core is the limit). The test found and we fixed: slow repeated work, a thread-safety error, and a risk of overloading the simulator.

---

## 13. Technology choices in plain words

| Choice | Why |
|---|---|
| Python + FastAPI | Fast to build, readable, strong data and ML libraries |
| scikit-learn gradient boosting | Accurate on tabular time-series features, trains in seconds, tiny model file, gives quantiles for uncertainty |
| Google OR-Tools (CP-SAT) | Exact optimization under many rules, deterministic |
| Supabase Postgres + pgvector | Managed storage for audit, models, settings; vector search for incident memory |
| React + Tailwind + Recharts | Clean, modern operator console |
| Prometheus + Grafana | Standard monitoring |
| Gemini / Groq (free, optional) | Only to reword explanations; decisions never depend on them |
| No reinforcement learning, multi-agent or clusters | Each planning step is solved exactly; one process handled 160 requests/s. See `docs/OPTIONAL_FEATURES.md` |

---

## 14. Questions judges may ask, with answers

**Did you train any model?** Yes: gradient-boosted quantile regression, trained on 226,560 observations from the simulator and generated worlds, with walk-forward evaluation, a model registry and automatic retraining (Section 6).

**Where did the training data come from?** Two places, both simulated: the organizer's simulator (we drove it through five crisis scenarios via its admin API and read the demand history) and independent worlds our own generator produced. There was no real-world data available; we say so openly. The collection and generation code is in the repository (`app/ml/collect.py`, `app/worldgen/world.py`) so anyone can reproduce it.

**Isn't training on simulated data a weakness?** It is a limitation, and the design accounts for it: the model is pooled and scale-free so it transfers; it is retrained on each network's own data; a challenger only replaces the champion on a measured win. On a real network the first step would be to let it collect history and retrain.

**How do you know it isn't just memorizing the simulator?** We tested on data it never saw: a held-out crisis scenario and a completely different generated network. It beats the baselines on both, and the zero-shot tests show where it does not (over-confident when trained on one world alone), which is why we train on two.

**Why not just use a formula?** We have one (the hand-set expert); it is a bit better *on the simulator* because it is the simulator's own formula, but it needs that knowledge and fails when the network differs. The trained model needs no such knowledge.

**Why gradient boosting and not deep learning?** The signal is tabular (time of day, lags, level), the data is modest, and we need fast retraining (22 seconds), a tiny model, quantiles and interpretability. Deep learning would add cost and risk without evidence of a benefit here.

**What does "confidence" mean?** A number from 0 to 1 built from the width of the model's 10–90% band relative to its forecast and from how much history the station has. Below 0.35, a person must decide.

**How does it handle a station it has never seen?** It uses a moving average for the first 24 observations, then the pooled model, because the model is scale-free.

**What if demand suddenly changes for good?** Within a few ticks the online correction follows it; if error stays high a retrain is triggered and the new model replaces the old only if it scores better on recent data (Section 7).

**What if retraining makes things worse?** The gate rejects it (in our adaptation run, two of three challengers were rejected, including one trained shortly after a pattern shift). If a promoted model disappoints later, roll back in one click.

**Is it using the simulator?** It can. It also runs on a live feed of any system, proven on an independent network; the simulator is one of two adapters (Section 8).

**How would you connect it to a real company?** Write a small gateway that pushes topology and telemetry to `/api/feed/*` and executes the orders it pulls. The core does not change.

**How does the optimizer decide?** It minimizes weighted, fairness-adjusted shortfall subject to every road, depot, sending and tank limit (Section 5).

**Why is the optimizer trustworthy?** It is exact, deterministic, respects the simulator's rules, is checked by a precheck before sending, shows before/after impact and alternatives, and is compared live with doing nothing and with simple rules.

**How do you handle bad sensor data?** Reject impossible values, clamp and flag suspicious ones, carry forward silent sensors, mark a silent feed stale, show a quality score (Section 7, layer 5).

**Who is in control?** The person. Auto-approve is off by default, bounded by budget, shipment size, confidence and severity, suspended on stale data, off again after a restart, with one-button emergency stop and full audit.

**How do you prevent AI hallucination?** Answers are built from live data; an optional language model may only reword them, and any reply with a number not in the data is discarded.

**What are the weaknesses?** Training data is simulated; the world is small and regular so real results would be messier; planning once every several hours is throughput-limited (one shipment per road and fuel per plan); a single process is the ceiling at about 160 requests/s; the sim-only model is over-confident on other networks until retrained.

---

## 15. Three-minute demo

1. **Overview:** calm network, briefing says stable, 100% service.
2. **Scenarios:** apply the combined crisis; watch alerts, recommendations with reasons, and the live comparison against doing nothing. Approve one; it disappears instantly.
3. **Controls:** show Emergency stop, auto-approve rules, and the audit trail of the change.
4. **Data sources:** click *Start demo world*: a different network with LPG appears; the same platform runs on it. Click *Demand jumps +40%* and *Daily peaks move +3 h*; open **Forecast & Models** and watch error rise then recover.
5. **Ops assistant:** "Why is this station low?" and "Is the optimizer better than doing nothing?".
6. **Fault:** make the simulator unavailable for 30 s, show degraded mode, then recovery in the audit log.
7. **Replay** the crisis; close with the benchmark, model and load-test graphs.

---

## 16. Glossary

| Term | Plain meaning |
|---|---|
| **Tick** | One step of the clock (15 minutes in the simulator) |
| **Service level** | Share of fuel demand actually served |
| **Forecast horizon** | How many ticks ahead we predict |
| **Quantile / 80% band** | A range where the true value should land about 80% of the time |
| **Calibration / coverage** | Whether that range really holds 80% of outcomes |
| **WAPE** | Total forecast error divided by total demand; lower is better |
| **Pooled model** | One model shared by all stations and fuels |
| **Walk-forward test** | Forecast points in the future of the training data, like real use |
| **Online adaptation** | Small automatic correction every tick that follows sudden shifts |
| **Drift** | The world changed so old patterns no longer fit |
| **Champion / challenger** | Current model vs. a newly trained candidate; the candidate must win a fair test |
| **Optimizer (CP-SAT)** | A solver that finds the best whole-numbers plan within all limits |
| **Fallback** | A simpler backup that takes over when something fails |
| **Idempotent** | Sending the same order twice has the same effect as once |
| **Circuit breaker** | Stop calling a failing service for a short time so it can recover |
| **Adapter** | A translator between an outside system and our internal data model |
| **pgvector** | Database feature for finding similar records by numbers |
| **SSE** | The server pushing live updates to the screen |
