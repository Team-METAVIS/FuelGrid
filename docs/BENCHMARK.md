# Benchmark results

Generated 2026-09-29 11:04. Each run resets the deterministic simulator (fixed seed), injects the scenario, then plays it under one policy. 1 tick = 15 simulated minutes.

Policies: `none` = do nothing, `rules` = greedy rule-based baseline, `optimizer` = OR-Tools planner.

| Scenario | Policy | Ticks | Service level | Unmet (L) | Served (L) | Shipped (L) | Rejected | Cycle avg/p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | none | 192 | 46.10% | 100,452 | 85,900 | 0 | 0 | 0.0/0.0 |
| baseline | rules | 192 | 100.00% | 0 | 186,352 | 116,400 | 0 | 6.3/10.2 |
| baseline | optimizer | 192 | 100.00% | 0 | 186,352 | 116,400 | 0 | 7.7/12.7 |
| demand_spike | none | 192 | 43.06% | 113,591 | 85,900 | 0 | 0 | 0.0/0.0 |
| demand_spike | rules | 192 | 100.00% | 0 | 199,491 | 138,600 | 0 | 6.5/11.1 |
| demand_spike | optimizer | 192 | 100.00% | 0 | 199,491 | 138,600 | 0 | 8.3/13.7 |
| route_disruption | none | 192 | 46.10% | 100,452 | 85,900 | 0 | 0 | 0.0/0.0 |
| route_disruption | rules | 192 | 100.00% | 0 | 186,352 | 116,400 | 0 | 6.3/10.5 |
| route_disruption | optimizer | 192 | 100.00% | 0 | 186,352 | 116,400 | 0 | 8.4/16.9 |
| shipment_delay | none | 192 | 46.10% | 100,452 | 85,900 | 0 | 0 | 0.0/0.0 |
| shipment_delay | rules | 192 | 100.00% | 0 | 186,352 | 116,400 | 0 | 6.4/11.9 |
| shipment_delay | optimizer | 192 | 100.00% | 0 | 186,352 | 116,400 | 0 | 8.0/13.4 |
| combined_crisis | none | 192 | 43.09% | 113,449 | 85,900 | 0 | 0 | 0.0/0.0 |
| combined_crisis | rules | 192 | 100.00% | 0 | 199,349 | 131,400 | 0 | 6.9/13.3 |
| combined_crisis | optimizer | 192 | 100.00% | 0 | 199,349 | 131,400 | 0 | 8.1/15.5 |
| scarcity | none | 288 | 20.76% | 327,861 | 85,900 | 0 | 0 | 0.0/0.0 |
| scarcity | rules | 288 | 94.08% | 24,483 | 389,278 | 305,900 | 0 | 6.8/11.6 |
| scarcity | optimizer | 288 | 94.57% | 22,477 | 391,284 | 305,900 | 0 | 12.5/22.9 |
| severe_crisis | none | 288 | 26.76% | 235,103 | 85,900 | 0 | 0 | 0.0/0.0 |
| severe_crisis | rules | 288 | 98.06% | 6,213 | 314,790 | 246,700 | 0 | 7.4/12.6 |
| severe_crisis | optimizer | 288 | 98.59% | 4,513 | 316,490 | 249,400 | 0 | 13.1/26.0 |
