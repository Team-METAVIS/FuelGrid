# FuelGrid — Load test

Tool: [Locust](https://locust.io). Script: `loadtest/locustfile.py`. Re-run everything with `bash loadtest/run.sh`
(summary tables: `python loadtest/summarize.py`). Raw CSV output: `loadtest/results/`.

> Load figures were measured with the simulator ticking live. Later additions (trained model, live feed, controls) do not sit on the hot read path; the model forecast runs once per planning cycle (a few milliseconds for the whole network).

## What was tested

The simulator was **running live (8 ticks per second)** during both runs, so background sync, forecasting and decision
cycles competed with the test traffic. This is the realistic worst case, not an idle server.

Workload per simulated user (weights in brackets), mimicking an operations room plus monitoring:

| Path | Weight | What it exercises |
|---|---:|---|
| `GET /api/state` | 10 | Main dashboard payload |
| `GET /api/forecast` | 3 | Forecast, uncertainty band and inventory projection |
| `GET /api/decisions` | 3 | Decision history |
| `GET /api/timeline`, `/api/briefing`, `/api/health` | 2 each | Trend data, plain-language briefing, health |
| `GET /healthz`, `/metrics` | 1 | Liveness and metrics scraping |
| `POST /api/cycle` | 1 | **Full decision path**: read the world, forecast, optimize, reconcile recommendations |

Environment: one Windows 11 laptop, everything on the same machine (FuelGrid as one process, simulator in Docker,
Locust, PostgreSQL in a local Docker container). Dedicated hardware would give better numbers.

## Results

### Normal load — 50 concurrent users, 60 s

| Endpoint | Requests | Failures | Avg ms | p50 | p95 | p99 | Max ms | Req/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| /api/briefing | 195 | 0 | 16 | 6 | 69 | 190 | 273 | 3.3 |
| /api/decisions | 297 | 0 | 16 | 9 | 49 | 100 | 239 | 5.0 |
| /api/forecast | 288 | 0 | 24 | 9 | 91 | 220 | 248 | 4.8 |
| /api/health | 185 | 0 | 18 | 8 | 60 | 180 | 274 | 3.1 |
| /api/state | 926 | 0 | 17 | 10 | 54 | 130 | 262 | 15.6 |
| /api/timeline | 189 | 0 | 16 | 8 | 44 | 140 | 246 | 3.2 |
| /healthz | 98 | 0 | 9 | 3 | 30 | 120 | 120 | 1.7 |
| /metrics | 98 | 0 | 17 | 13 | 41 | 62 | 62 | 1.7 |
| /api/cycle (full decision path) | 114 | 0 | 74 | 56 | 150 | 260 | 416 | 1.9 |
| **All endpoints** | 2390 | 0 | 20 | 9 | 76 | 150 | 416 | 40.2 |

Process after the run: 267 MB memory. Error rate 0%.

### Stress — 250 concurrent users, 45 s (find the limit)

| Endpoint | Requests | Failures | Avg ms | p50 | p95 | p99 | Max ms | Req/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| /api/briefing | 476 | 0 | 412 | 370 | 820 | 1000 | 1524 | 10.7 |
| /api/decisions | 793 | 0 | 410 | 370 | 790 | 1000 | 1544 | 17.9 |
| /api/forecast | 772 | 0 | 421 | 380 | 810 | 1100 | 1751 | 17.4 |
| /api/health | 494 | 0 | 404 | 370 | 760 | 940 | 1301 | 11.1 |
| /api/state | 2664 | 0 | 414 | 370 | 830 | 1200 | 1725 | 60.1 |
| /api/timeline | 525 | 0 | 422 | 380 | 770 | 1200 | 1589 | 11.8 |
| /healthz | 250 | 0 | 260 | 230 | 530 | 1100 | 1166 | 5.6 |
| /metrics | 246 | 0 | 382 | 370 | 730 | 870 | 937 | 5.6 |
| /api/cycle (full decision path) | 267 | 0 | 1314 | 1200 | 2400 | 2700 | 3299 | 6.0 |
| **All endpoints** | 6487 | 0 | 444 | 380 | 920 | 1800 | 3299 | 146.4 |

Process after the run: 283 MB memory. Still **0 errors**, and the simulator stayed healthy throughout.

Both runs use the current build: the trained forecasting model (it runs in every decision cycle), regional roll-up, arrival
estimates and bottleneck analysis in the dashboard payload, and PostgreSQL in a local container.

## What we learned

1. **The limit is one CPU core: roughly 145 requests/s.** Beyond that, requests queue and latency grows (typical
   answer 380 ms at 250 users, worst 3.3 s), but nothing fails and the control loop keeps running. The service
   slows down gracefully instead of falling over.
2. **Normal operation is very comfortable:** 95 of 100 requests finish in under 80 ms and 99 of 100 in under 150 ms;
   the whole decision path (including the trained model) averages 74 ms.
3. **Scaling path:** read endpoints depend only on the latest cached snapshot, so several copies could sit behind a
   load balancer with one copy owning the decision loop. Not needed at this scale.

## Problems this load test found (all fixed and covered by tests)

| Finding | Cause | Fix | Effect |
|---|---|---|---|
| Median 120 ms even for `/healthz` | The test tool used `localhost` (IPv6 attempted first, then fallback) | Use `127.0.0.1`; documented | Measurement artifact removed |
| 95th percentile 610 ms, worst 3.3 s at 50 users | Every request rebuilt the dashboard payload; shipments and demand history were re-scanned per station and fuel; forecasts recomputed per request; sync ran 4 times a second | Payload cached per data version; shipments indexed once per snapshot; ordered history index; plan's forecasts reused; sync limited to twice a second | 610 → 37 ms; worst 3.3 s → 0.2 s; decision path 894 → 30 ms |
| One rare HTTP 500 on `/api/state` | Statistics window read from a worker thread while the main thread wrote to it | Lock around the window; read endpoints run on the main event loop | 0 errors afterwards |
| Decision requests waited up to 38 s at 250 users | Every concurrent "decide now" ran its own full cycle | Concurrent requests share one in-flight cycle | Worst case 38 s → 1.8 s |
| Throughput fell to 87 req/s and even `/healthz` took 500 ms once the trained model was active | scikit-learn's OpenMP worker threads spin on every core; with the API and load generator sharing the machine they starved the event loop (process showed 425% CPU) | Inference is limited to one thread (a few hundred rows gain nothing from more); the large dashboard body is serialized once per data version instead of once per request | 87 → 146 req/s at 250 users, still 0 errors |
| **The organizer's simulator stopped responding after heavy load** | Its own database connection pool is tiny (5 plus 10 spare). Concurrent decision requests each triggered their own 8-way parallel refresh, flooding it with more simultaneous requests than it can serve | FuelGrid now caps simultaneous simulator calls at 4, and concurrent refreshes share one round of calls. Unit tests cover both. | Same stress test now leaves the simulator healthy |

The last finding matters for the live event: **a client that can hang the shared simulator is a liability**, so
FuelGrid deliberately protects it.

## Recommendation for demos

Run the simulator at a lower speed (`SIMULATION_SPEED=1`) when demonstrating; decisions then track the world at human
pace and the simulator is not stressed. Use `127.0.0.1` rather than `localhost` on Windows.
