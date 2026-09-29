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
Locust, Supabase over the internet). Dedicated hardware would give better numbers.

## Results

### Normal load — 50 concurrent users, 60 s

| Endpoint | Requests | Failures | Avg ms | p50 | p95 | p99 | Max ms | Req/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| /api/briefing | 212 | 0 | 9 | 5 | 31 | 47 | 60 | 3.6 |
| /api/decisions | 295 | 0 | 13 | 7 | 47 | 78 | 167 | 5.0 |
| /api/forecast | 276 | 0 | 13 | 8 | 36 | 69 | 200 | 4.6 |
| /api/health | 190 | 0 | 11 | 6 | 31 | 70 | 91 | 3.2 |
| /api/state | 992 | 0 | 13 | 9 | 33 | 64 | 151 | 16.7 |
| /api/timeline | 174 | 0 | 12 | 6 | 39 | 110 | 119 | 2.9 |
| /healthz | 89 | 0 | 6 | 3 | 20 | 67 | 67 | 1.5 |
| /metrics | 89 | 0 | 12 | 9 | 29 | 37 | 37 | 1.5 |
| /api/cycle (full decision path) | 90 | 0 | 30 | 23 | 79 | 100 | 104 | 1.5 |
| **All endpoints** | **2407** | **0** | **13** | **8** | **37** | **68** | **200** | **40.4** |

Memory 163 MB. Error rate 0%.

### Stress — 250 concurrent users, 45 s (find the limit)

| Endpoint | Requests | Failures | Avg ms | p50 | p95 | p99 | Max ms | Req/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| /api/state | 2908 | 0 | 306 | 270 | 650 | 870 | 1074 | 64.1 |
| /api/forecast | 884 | 0 | 297 | 270 | 610 | 850 | 899 | 19.5 |
| /api/cycle (full decision path) | 302 | 0 | 561 | 470 | 1400 | 1700 | 1818 | 6.7 |
| /healthz | 306 | 0 | 186 | 170 | 410 | 610 | 636 | 6.8 |
| **All endpoints** | **7258** | **0** | **306** | **270** | **660** | **900** | **1818** | **160.1** |

CPU about 77–100% of one core, memory 191 MB. Still **0 errors**, and the simulator stayed healthy throughout.

## What we learned

1. **The limit is one CPU core: roughly 160 requests/s.** Beyond that, requests queue and latency grows (typical
   answer 270 ms at 250 users, worst 1.8 s), but nothing fails and the control loop keeps running. The service
   slows down gracefully instead of falling over.
2. **Normal operation is very comfortable:** 95 of 100 requests finish in under 40 ms and 99 of 100 in under 70 ms;
   the whole decision path averages 30 ms.
3. **Scaling path:** read endpoints depend only on the latest cached snapshot, so several copies could sit behind a
   load balancer with one copy owning the decision loop. Not needed at this scale.

## Problems this load test found (all fixed and covered by tests)

| Finding | Cause | Fix | Effect |
|---|---|---|---|
| Median 120 ms even for `/healthz` | The test tool used `localhost` (IPv6 attempted first, then fallback) | Use `127.0.0.1`; documented | Measurement artifact removed |
| 95th percentile 610 ms, worst 3.3 s at 50 users | Every request rebuilt the dashboard payload; shipments and demand history were re-scanned per station and fuel; forecasts recomputed per request; sync ran 4 times a second | Payload cached per data version; shipments indexed once per snapshot; ordered history index; plan's forecasts reused; sync limited to twice a second | 610 → 37 ms; worst 3.3 s → 0.2 s; decision path 894 → 30 ms |
| One rare HTTP 500 on `/api/state` | Statistics window read from a worker thread while the main thread wrote to it | Lock around the window; read endpoints run on the main event loop | 0 errors afterwards |
| Decision requests waited up to 38 s at 250 users | Every concurrent "decide now" ran its own full cycle | Concurrent requests share one in-flight cycle | Worst case 38 s → 1.8 s |
| **The organizer's simulator stopped responding after heavy load** | Its own database connection pool is tiny (5 plus 10 spare). Concurrent decision requests each triggered their own 8-way parallel refresh, flooding it with more simultaneous requests than it can serve | FuelGrid now caps simultaneous simulator calls at 4, and concurrent refreshes share one round of calls. Unit tests cover both. | Same stress test now leaves the simulator healthy |

The last finding matters for the live event: **a client that can hang the shared simulator is a liability**, so
FuelGrid deliberately protects it.

## Recommendation for demos

Run the simulator at a lower speed (`SIMULATION_SPEED=1`) when demonstrating; decisions then track the world at human
pace and the simulator is not stressed. Use `127.0.0.1` rather than `localhost` on Windows.
