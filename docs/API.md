# API reference

70 operations, generated from the application's OpenAPI schema by `scripts/make_api_doc.py`. Interactive documentation is served at `/docs`.

Write operations (POST/PUT/DELETE) require the `X-API-Key` header when `API_KEY` is set. Errors use a JSON `detail` (a message, or `{code, message}`). The v1 resource endpoints mirror the organizer brief's resources (stations, depots, routes, supply arrivals, events, demand history, allocations, metrics, instance) and answer from whichever data source is active, so they work the same for the simulator and for a live feed.

## Core resources (stations, depots, routes, supply arrivals, demand history, allocations)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/allocations` | Allocations (shipments), newest first; filter by status. |
| POST | `/api/v1/allocations` | Manual dispatch. Validated against the source's rules before sending; the same key with the same body returns the same result. |
| POST | `/api/v1/allocations/{alloc_id}/cancel` | Cancel an allocation FuelGrid created, if it has not departed yet. |
| GET | `/api/v1/demand-history` | Most recent demand observations (newest first), optionally for one station and/or fuel. limit is clamped to 1..2000. |
| GET | `/api/v1/depots` | All depots with dispatch capacity and current stock per fuel. |
| GET | `/api/v1/depots/{did}` | One depot. |
| GET | `/api/v1/events` | Crisis and disruption events of the world (not FuelGrid's own activity feed, which is /api/events). |
| GET | `/api/v1/instance` | The world instance: scenario, current tick, tick length, the active data source and how old the snapshot is. |
| GET | `/api/v1/metrics` | Network service metrics: served and unmet demand, service level, allocated liters, failures. |
| GET | `/api/v1/regions` | Regions and their demand factors. |
| GET | `/api/v1/routes` | All roads between depots and stations: transit time, maximum shipment, status. |
| GET | `/api/v1/stations` | All stations with capacity and current inventory per fuel; filter by region_id. |
| GET | `/api/v1/stations/{sid}` | One station. |
| GET | `/api/v1/supply-arrivals` | Supply deliveries into depots (planned and actual tick, status); filter by status. |

## Live-feed ingestion and the independent demo world

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/feed/demo/change` | Demo Change |
| POST | `/api/feed/demo/start` | Demo Start |
| GET | `/api/feed/demo/status` | Demo Status |
| POST | `/api/feed/demo/stop` | Demo Stop |
| GET | `/api/feed/orders` | Dispatch orders approved by operators. Executing systems poll this (or receive the optional webhook). |
| POST | `/api/feed/orders/{order_id}/ack` | Feed Ack |
| GET | `/api/feed/status` | Feed Status |
| POST | `/api/feed/telemetry` | Feed Telemetry |
| POST | `/api/feed/topology` | Feed Topology |

## Recommendations and operator decisions

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/decisions` | Decisions |
| POST | `/api/decisions/approve-all` | Approve All |
| POST | `/api/decisions/reject-all` | Reject All |
| POST | `/api/decisions/{did}/approve` | Approve |
| POST | `/api/decisions/{did}/cancel` | Cancel |
| POST | `/api/decisions/{did}/reject` | Reject |

## Operational controls (auto-approve, pause, emergency stop, limits)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/controls` | Get Controls |
| POST | `/api/controls` | Set Controls |
| POST | `/api/controls/emergency-stop` | One button: stop planning, stop auto-dispatch, withdraw pending recommendations. |
| POST | `/api/controls/reset` | Reset Controls |
| POST | `/api/controls/resume` | Resume |

## Simulator control and the lock-step clock

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sim/clock` | Clock Status |
| POST | `/api/sim/clock/start` | Lock-step clock: FuelGrid advances the simulator itself, planning every tick before taking the next. |
| POST | `/api/sim/clock/stop` | Clock Stop |
| POST | `/api/sim/faults/clear` | Clear Faults |
| POST | `/api/sim/inject/event` | Inject Event |
| POST | `/api/sim/inject/fault` | Inject Fault |
| POST | `/api/sim/{action}` | Sim Control |

## Model registry and lifecycle

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/models` | Models |
| POST | `/api/models/activate` | Activate Model |
| GET | `/api/models/learned` | The trained model's card: what it is, how it was trained, how it scored, what it relies on, and its version history. |
| POST | `/api/models/retrain` | Retrain |

## Replay of recorded runs

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/replay/runs` | Replay Runs |
| GET | `/api/replay/{run_id}` | Replay |

## Platform state, analytics, assistant, scenarios and health

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/adaptation` | Adaptation |
| POST | `/api/assistant` | Ask |
| GET | `/api/assistant/status` | Assistant Status |
| GET | `/api/audit` | Audit |
| GET | `/api/auth/status` | Lets the console know whether write actions need an API key and whether the key it holds works. |
| GET | `/api/benchmarks` | Benchmarks |
| GET | `/api/briefing` | Briefing |
| POST | `/api/cycle` | Cycle Now |
| GET | `/api/events` | Recent Events |
| GET | `/api/experiments` | Experiments |
| GET | `/api/forecast` | Observed demand, forecast with uncertainty band, and projected inventory (with/without in-flight supply). |
| GET | `/api/health` | Health |
| GET | `/api/scenarios` | Scenarios |
| POST | `/api/scenarios/{name}/apply` | Apply Scenario |
| POST | `/api/settings` | Settings |
| GET | `/api/source` | Source |
| POST | `/api/source` | Switch |
| GET | `/api/state` | State |
| GET | `/api/stream` | Live push: every domain event (snapshot, decision change, audit entry, sim degraded/recovered/reset) as SSE. |
| GET | `/api/telemetry` | Telemetry |
| GET | `/api/timeline` | Timeline |
| GET | `/api/tuning` | Tuning |

## Operations (health probes, metrics, documentation)

| Method | Path | Purpose |
|---|---|---|
| GET | `/readyz` | Readiness: the platform has a snapshot from its data source and can serve decisions. 503 until then. |
