# Adaptation experiment: how the platform copes when the world changes

The same unseen network and the same five surprises (demand +40% at t=150, daily peaks +3 h at t=300, three sensors silent at t=450, a new station at t=520, an unannounced surge at t=600) were replayed under five forecasting approaches, each driving the same optimizer in a closed loop with hourly re-planning. Higher service level and lower error are better.

| Approach | Service level | Unmet demand (L) | Fuel shipped (L) | Mean 1-step forecast error | Model retrains |
|---|---:|---:|---:|---:|---:|
| Expert profile (hand-set) | 99.97% | 1,216 | 4,249,800 | 20.7% | 0 promoted / 0 run |
| Moving average | 99.98% | 814 | 4,179,000 | 25.8% | 0 promoted / 0 run |
| Trained model, frozen | 99.98% | 1,018 | 4,140,200 | 14.1% | 0 promoted / 0 run |
| Trained + online adaptation | 99.98% | 878 | 4,175,400 | 14.0% | 0 promoted / 0 run |
| Trained + adaptation + retraining | 99.97% | 1,027 | 4,170,100 | 14.0% | 1 promoted / 3 run |

## Forecast error around each surprise

Mean 1-step error: 48 ticks before -> in the 24 ticks after -> 48-72 ticks after.

| Approach | demand shift (t=150) | seasonality shift (t=300) | sensor dropout (t=450) | new station (t=520) | demand shock (t=600) |
|---|---:|---:|---:|---:|---:|
| Expert profile (hand-set) | 21% -> 22% -> 19% | 20% -> 17% -> 23% | 21% -> 20% -> 20% | 20% -> 22% -> 20% | 20% -> 22% -> 21% |
| Moving average | 26% -> 28% -> 23% | 25% -> 19% -> 27% | 26% -> 23% -> 24% | 25% -> 29% -> 27% | 25% -> 28% -> 27% |
| Trained model, frozen | 15% -> 17% -> 12% | 13% -> 20% -> 17% | 13% -> 14% -> 12% | 13% -> 13% -> 13% | 12% -> 14% -> 13% |
| Trained + online adaptation | 13% -> 13% -> 14% | 13% -> 20% -> 19% | 14% -> 13% -> 14% | 13% -> 14% -> 12% | 12% -> 14% -> 13% |
| Trained + adaptation + retraining | 13% -> 13% -> 14% | 12% -> 20% -> 19% | 14% -> 12% -> 14% | 13% -> 14% -> 13% | 13% -> 14% -> 13% |

## Model retraining log (last approach)

- t=2: **rejected** - challenger error 17.9% vs champion 16.0%: not a clear win, champion kept
- t=242: **promoted** - gbm-20260929-074738 promoted: challenger error 16.6% vs champion 17.4%
- t=482: **rejected** - challenger error 18.0% vs champion 17.7%: not a clear win, champion kept
