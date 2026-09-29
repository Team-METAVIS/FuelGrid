# Planner tuning sweep

Generated 2026-09-29 12:08. Optimizer policy, 192 ticks per run on the same deterministic world; one setting changed at a time. Higher service level is better; at equal service level, less fuel shipped is better (less waste and less trucking).

| Setting | scarcity service | scarcity unmet L | scarcity shipped L | severe_crisis service | severe_crisis unmet L | severe_crisis shipped L |
|---|---:|---:|---:|---:|---:|---:|
| baseline (cover 24, z 1.28, reserve 10%) | 100.00% | 0 | 218,700 | 96.82% | 7,239 | 154,000 |
| shorter cover (16 ticks) | 100.00% | 0 | 208,600 | 94.68% | 12,122 | 140,800 |
| longer cover (32 ticks) | 100.00% | 0 | 227,000 | 98.03% | 4,486 | 164,400 |
| small safety buffer (z 0.5) | 100.00% | 0 | 219,000 | 96.21% | 8,639 | 149,800 |
| large safety buffer (z 2.0) | 100.00% | 0 | 221,700 | 97.31% | 6,139 | 154,100 |
| no depot reserve | 100.00% | 0 | 218,300 | 96.82% | 7,239 | 154,000 |
| large depot reserve (20%) | 100.00% | 0 | 213,700 | 96.82% | 7,239 | 154,000 |
