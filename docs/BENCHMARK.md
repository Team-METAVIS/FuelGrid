# Benchmark results

Generated 2026-09-29 12:34. Each run resets the deterministic simulator (fixed seed), injects the scenario, then plays it under one policy. 1 tick = 15 simulated minutes.

Policies: `none` = do nothing, `rules` = greedy rule-based baseline, `optimizer` = OR-Tools planner.

| Scenario | Policy | Ticks | Service level | Unmet (L) | Served (L) | Shipped (L) | Rejected | Cycle avg/p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | none | 192 | 46.10% | 100,452 | 85,900 | 0 | 0 | 0.0/0.0 |
| baseline | rules | 192 | 100.00% | 0 | 186,352 | 129,000 | 0 | 7.6/11.8 |
| baseline | optimizer | 192 | 100.00% | 0 | 186,352 | 129,000 | 0 | 7.7/14.0 |
| demand_spike | none | 192 | 43.06% | 113,591 | 85,900 | 0 | 0 | 0.0/0.0 |
| demand_spike | rules | 192 | 100.00% | 0 | 199,491 | 143,300 | 0 | 10.9/20.8 |
| demand_spike | optimizer | 192 | 100.00% | 0 | 199,491 | 143,300 | 0 | 9.3/17.4 |
| route_disruption | none | 192 | 46.10% | 100,452 | 85,900 | 0 | 0 | 0.0/0.0 |
| route_disruption | rules | 192 | 100.00% | 0 | 186,352 | 129,000 | 0 | 7.2/10.8 |
| route_disruption | optimizer | 192 | 100.00% | 0 | 186,352 | 129,000 | 0 | 7.7/12.5 |
| shipment_delay | none | 192 | 46.10% | 100,452 | 85,900 | 0 | 0 | 0.0/0.0 |
| shipment_delay | rules | 192 | 100.00% | 0 | 186,352 | 129,000 | 0 | 7.2/11.1 |
| shipment_delay | optimizer | 192 | 100.00% | 0 | 186,352 | 129,000 | 0 | 7.4/14.0 |
| combined_crisis | none | 192 | 43.09% | 113,449 | 85,900 | 0 | 0 | 0.0/0.0 |
| combined_crisis | rules | 192 | 100.00% | 0 | 199,349 | 142,800 | 0 | 7.5/13.9 |
| combined_crisis | optimizer | 192 | 100.00% | 0 | 199,349 | 142,800 | 0 | 7.2/11.9 |
| scarcity | none | 288 | 20.76% | 327,861 | 85,900 | 0 | 0 | 0.0/0.0 |
| scarcity | rules | 288 | 93.10% | 28,538 | 385,223 | 305,900 | 0 | 9.4/17.3 |
| scarcity | optimizer | 288 | 94.55% | 22,542 | 391,219 | 305,900 | 0 | 8.4/13.8 |
| severe_crisis | none | 288 | 26.76% | 235,103 | 85,900 | 0 | 0 | 0.0/0.0 |
| severe_crisis | rules | 288 | 98.60% | 4,486 | 316,517 | 252,600 | 0 | 8.4/14.3 |
| severe_crisis | optimizer | 288 | 98.60% | 4,486 | 316,517 | 252,600 | 0 | 8.5/13.6 |
