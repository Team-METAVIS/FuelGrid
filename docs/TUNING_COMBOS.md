# Planner tuning sweep

Generated 2026-09-29 12:22. Optimizer policy, 288 ticks per run on the same deterministic world; one setting changed at a time. Higher service level is better; at equal service level, less fuel shipped is better (less waste and less trucking).

| Setting | scarcity service | scarcity unmet L | scarcity shipped L | severe_crisis service | severe_crisis unmet L | severe_crisis shipped L |
|---|---:|---:|---:|---:|---:|---:|
| current defaults (cover 24, z 1.28) | 94.09% | 24,433 | 305,900 | 97.75% | 7,239 | 244,500 |
| cover 32, z 1.28 | 94.36% | 23,348 | 305,900 | 98.60% | 4,486 | 255,000 |
| cover 32, z 2.0 | 94.55% | 22,542 | 305,900 | 98.60% | 4,486 | 252,600 |
| cover 40, z 1.28 | 94.36% | 23,348 | 305,900 | 98.60% | 4,486 | 255,000 |
| cover 40, z 2.0 | 94.55% | 22,542 | 305,900 | 98.60% | 4,486 | 252,600 |
