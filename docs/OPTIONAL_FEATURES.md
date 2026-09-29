# Optional advanced work — what we built, and what we deliberately did not

The brief lists optional items and warns that complexity alone earns nothing. Each item below was judged on one
question: *does it make the operators' decisions better or the system more trustworthy, and can we prove it?*

| Optional item | Status | Where / why |
|---|---|---|
| Optimization + ML hybrid | **Built** | A trained quantile demand model (gradient boosting, uncertainty band) feeds an exact optimizer (OR-Tools); the band sets the safety buffer. Forecast v2 cut error on the combined crisis from 7.5% to 6.0% and reached the same service level while shipping about 30% less fuel on the demand-spike scenario. |
| Uncertainty-aware allocation | **Built** | Every need includes a safety buffer of `safety_z` standard deviations of forecast error; low confidence forces human review. `docs/TUNING.md` shows the effect of the buffer. |
| Counterfactual simulation | **Built** | Each cycle rolls forward "do nothing", the active policy and the other policy on the same state (Overview, live). The Forecast page also shows inventory with and without pending shipments. |
| Automated incident detection | **Built** | Road, station, depot, delivery, demand-anomaly and model-drift incidents are detected and logged, with recovery tracking. |
| Incident memory (pgvector) | **Built** | Resolved incidents are stored in Supabase with a numeric signature and outcome; new incidents show the closest past cases. Falls back to in-memory search if the database is down. |
| Drift detection | **Built** | Rolling forecast error above 25% raises an incident and a Prometheus alert. |
| Policy rollback | **Built** | Three failed optimizer cycles in a row switch the system to the rule-based policy, with a banner and a one-click restore. |
| Event-driven architecture | **Built** | In-process event bus (`app/core/events.py`); the engine, sync layer and audit trail publish, the live UI stream subscribes with replay after reconnect. |
| Streaming | **Built** | Server-sent events push decisions, alerts, and link changes to the console as they happen. |
| Generative-AI operations assistant | **Built, safely** | `/api/assistant` answers from live data. Free-tier language models (Gemini with automatic model discovery and rotation, Groq as backup) may only reword the answer; any reply containing a number not in the data is discarded and the next model is tried. It cannot act. Works fully with no key. |
| Continuous learning (champion / challenger) | **Built** | Drift or schedule triggers a challenger; it replaces the trained champion only if it beats it by 3% on the most recent window; versions kept for one-click rollback (`docs/ADAPTATION.md`). |
| Data-source independence | **Built** | Canonical model, simulator and live-feed adapters, independent generated world, live source switching (`docs/ARCHITECTURE.md`). |
| Simulation replay | **Built** | Replay page scrubs through any recorded run (fuel levels, decisions, incidents). |
| Experiment tracking, model versioning | **Built** | `fg_experiments` table, model registry with one-click activation, tuning sweep (`docs/TUNING.md`). |
| Automated rollback, deployment versioning | **Built** | Every image is tagged with its git SHA; `scripts/deploy.sh` starts a version, waits for it to report itself healthy and restarts the previous version if it does not. CI runs this against the organizer's simulator image, then injects a simulator outage and asserts degraded mode and recovery (`.github/workflows/ci.yml`, job `e2e`). |
| Reinforcement learning | **Not built, on purpose** | Each planning step is a small, exactly solvable problem, so an exact optimizer is already optimal for it. RL would need a training loop against a slow simulator and would have to beat a strong baseline to justify itself; we have no evidence it could. The organizers ask for that comparison if RL is used. |
| Multi-agent decision systems | **Not built, on purpose** | With 2 depots and 4 stations one solver sees the whole problem. Splitting it into negotiating agents would add failure modes and lose optimality. |
| Kubernetes | **Built** | Kustomize manifests for the app, simulator, Prometheus and Grafana (`deploy/`); probes, resource limits, hardened non-root pods, one-command rollback. CI deploys them to a kind cluster and checks self-healing after the pod is killed (`docs/KUBERNETES.md`). |
| Autoscaling | **Not built, on purpose** | The decision engine runs in-process, so a second replica would be a second planner sending its own shipments. One process handles about 160 requests/s with zero errors, far above any operations room; the scaling path is described in `docs/LOAD_TEST.md`. |

Everything built is covered by automated tests (94) and listed in the round-one notes.
