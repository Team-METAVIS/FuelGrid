# Finals demo runbook

A 10-minute live demo that follows the brief's suggested story (§22): the system runs and adapts, a failure is
injected, monitoring detects it, the fallback takes over, and operations continue. The three-minute version is in
`round_one_prep.md` §15.

## Before judges arrive (5 minutes)

```bash
docker compose --profile monitoring up --build -d
```

| Check | Where | Expected |
|---|---|---|
| Console | http://127.0.0.1:8080 | Overview loads, banner says *Simulated environment* |
| Health | *System health* page | All components healthy; mode `live` |
| Grafana | http://127.0.0.1:3000 | *FuelGrid - Operations & Intelligence* dashboard shows data |
| Prometheus alerts | http://127.0.0.1:9090/alerts | Rules loaded, none firing |
| Clean slate | *Scenarios & Chaos* → reset | Tick 0 |

Keep auto-approve **off** so the judges see the human-review step. On the *Data sources* page start the **lock-step
clock** at 2 ticks/s so every tick is planned before the next one.

## 1. Normal operations (1 min)

* **Overview:** stock levels, hours to stock-out, service level, briefing.
* **Decisions:** one recommendation opened: why the station is at risk, forecast band, constraints checked,
  expected impact, alternatives, confidence. Approve it; it leaves the list and appears in the *Audit log*.

## 2. Crisis: the network changes (2 min)

*Scenarios & Chaos* → scenario library → **Combined crisis** (or inject events one by one: demand spike, route
disruption, depot constraint, shipment delay).

* Incidents appear on the Overview, and risk rises on the affected stations.
* Recommendations re-route around the closed road and draw on the unconstrained depot.
* The live comparison shows the plan against doing nothing.
* *Forecast & Models:* the forecast follows the spike; the demand-anomaly incident is raised.

## 3. Software failure: inject and detect (2 min)

*Scenarios & Chaos* → **Inject software fault** → **API unavailable** (30 s).

| Where to look | What judges see |
|---|---|
| Console header, *System health* | Data source `degraded`, mode `cached-state (degraded)`, breaker open |
| Overview | Still served from the last good state, clearly labeled |
| Grafana | `fg_degraded` goes to 1, simulator error rate rises |
| Prometheus alerts | `SimulatorCircuitBreakerOpen` fires after 10 s; `DegradedMode` goes pending (it fires after 30 s, so it may clear as the 30 s fault ends: that is recovery working) |
| *Audit log* | Fault injection and degradation recorded |

Auto-dispatch is suspended while the data is not trustworthy.

## 4. Fallback and recovery (2 min)

* After 30 s the fault expires: after its cool-down the breaker lets one probe through, it succeeds and the breaker closes; mode returns to `live`; the audit log
  records the recovery.
* Repeat quickly with **Stale data** (auto-execute is suspended; the stale flag is shown) and **50% error rate**
  (retries absorb it; error-rate metric moves, the console does not break).
* Optimizer fallback: *Controls* → policy → rules, to show the rule-based policy producing a valid plan; switch back.
  An optimizer failure does this automatically, and after 3 failures in a row makes the rules policy active until an
  operator restores it.

## 5. Operations continue, and the evidence (2 min)

* The crisis is still being handled: recommendations keep coming, service level recovers.
* **Replay:** scrub back through the crisis.
* **Ops assistant:** "Why is this station at risk?" (answers only from live numbers).
* Evidence: `docs/BENCHMARK.md` (do nothing vs rules vs optimizer), `docs/MODEL.md`, `docs/LOAD_TEST.md`,
  and the CI run whose `e2e` job repeats step 3 and 4 automatically on every push.

## If something goes wrong on stage

| Symptom | Fix |
|---|---|
| Console blank | `docker compose ps`; `docker compose restart fuelgrid` (state is re-read from the simulator) |
| Simulator not ticking | Lock-step clock stopped: start it again on *Data sources* |
| Faults still active | *Scenarios & Chaos* → clear faults |
| Bad deploy | `bash scripts/deploy.sh <previous tag>` (health-gated) |
| Simulator unreachable | Demo the independent world: *Data sources* → *Start demo world* |
