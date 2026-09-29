# Demand model: training and evaluation

FuelGrid's forecaster is a **trained model**, not a hand-written formula: gradient-boosted quantile regression (scikit-learn), pooled across every station and fuel, giving a forecast and an 80% prediction band. It never reads the simulator's published demand profile; it learns time-of-day, day-of-week, momentum, and the effect of announced events from data.

**Champion `gbm-20260929-base`**: 250,000 training rows from 188 series (226,560 observations) across sim:baseline, sim:combined_crisis, sim:demand_spike, sim:scarcity, sim:severe_crisis, world:1, world:2, world:3, world:4; model file 600 KB.

Error metric: **WAPE** = total absolute error / total actual demand (lower is better). Horizon *h* is ticks ahead. Coverage is the share of outcomes inside the 10-90% band (ideal: 80%).


## E1 held-out simulator scenario

Trained on 176 series (250,000 rows); tested on 12 series, walk-forward.

| Horizon | model | naive | yesterday | average | expert profile | Coverage (80%) |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 6.1% | 6.6% | 6.7% | 16.1% | 5.2% | 72% |
| 4 | 6.4% | 15.5% | 6.9% | 25.3% | 5.1% | 76% |
| 8 | 6.3% | 24.6% | 6.9% | 34.0% | 5.1% | 78% |
| 16 | 6.3% | 40.1% | 6.9% | 45.3% | 5.1% | 81% |
| 32 | 6.5% | 47.0% | 6.9% | 46.1% | 5.1% | 83% |

## E2 unseen generated network

Trained on 156 series (250,000 rows); tested on 32 series, walk-forward.

| Horizon | model | naive | yesterday | average | Coverage (80%) |
|---|---:|---:|---:|---:|---:|
| 1 | 11.2% | 12.8% | 16.9% | 24.1% | 86% |
| 4 | 13.7% | 26.4% | 17.4% | 32.6% | 82% |
| 8 | 13.9% | 38.0% | 17.5% | 38.2% | 83% |
| 16 | 14.0% | 40.0% | 17.5% | 33.5% | 83% |
| 32 | 14.1% | 40.0% | 17.5% | 39.1% | 84% |

## E3a zero-shot: simulator-only model on a new world

Trained on 60 series (105,300 rows); tested on 32 series, walk-forward.

| Horizon | model | naive | yesterday | average | Coverage (80%) |
|---|---:|---:|---:|---:|---:|
| 1 | 14.2% | 12.8% | 16.9% | 24.1% | 44% |
| 4 | 17.2% | 26.4% | 17.4% | 32.6% | 42% |
| 8 | 17.6% | 38.0% | 17.5% | 38.2% | 42% |
| 16 | 17.8% | 40.0% | 17.5% | 33.5% | 41% |
| 32 | 17.8% | 40.0% | 17.5% | 39.1% | 40% |

## E3b zero-shot: worlds-only model on the simulator

Trained on 128 series (250,000 rows); tested on 12 series, walk-forward.

| Horizon | model | naive | yesterday | average | expert profile | Coverage (80%) |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 8.6% | 6.6% | 6.7% | 16.1% | 5.2% | 85% |
| 4 | 10.3% | 15.5% | 6.9% | 25.3% | 5.1% | 82% |
| 8 | 10.5% | 24.6% | 6.9% | 34.0% | 5.1% | 84% |
| 16 | 10.5% | 40.1% | 6.9% | 45.3% | 5.1% | 85% |
| 32 | 11.1% | 47.0% | 6.9% | 46.1% | 5.1% | 85% |

## E4 future window (train first 75%, test last 25%)

Trained on 188 series (250,000 rows); tested on 188 series, walk-forward.

| Horizon | model | naive | yesterday | average | Coverage (80%) |
|---|---:|---:|---:|---:|---:|
| 1 | 10.9% | 11.9% | 16.9% | 23.6% | 83% |
| 4 | 13.2% | 25.4% | 16.9% | 33.0% | 81% |
| 8 | 13.5% | 37.7% | 16.9% | 38.7% | 82% |
| 16 | 13.7% | 41.5% | 17.0% | 35.8% | 82% |
| 32 | 14.0% | 42.4% | 17.2% | 40.9% | 82% |

## What the model relies on (permutation importance)

| Feature | Importance |
|---|---:|
| lag_day | 0.1028 |
| lag_2day | 0.0264 |
| lag_week | 0.0177 |
| last | 0.0166 |
| hours_ahead | 0.0111 |
| mean_day | 0.0077 |
| dow_cos | 0.0035 |
| hod_cos | 0.0034 |
| tick_minutes | 0.0025 |
| level_ratio | 0.0019 |
