# Kubernetes deployment

FuelGrid, the organizer simulator and the monitoring stack run on any Kubernetes cluster with plain `kubectl`
(Kustomize is built in). Docker Compose remains the simplest way to run it on one machine; Kubernetes adds
self-healing, declarative rollouts and one-command rollback.

## What gets deployed

| Object | Purpose |
|---|---|
| Namespace `fuelgrid` | Everything below lives here |
| Deployment + Service `simulator` | Organizer image, unmodified |
| Deployment + Service `fuelgrid` | Backend + operator console, port 8080 |
| ConfigMaps (generated, hash-suffixed) | Settings; a change rolls the pods automatically |
| Secret `fuelgrid-secrets` (optional) | `DATABASE_URL`, `API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY` |
| Deployments `prometheus`, `grafana` | Same config, alert rules and dashboard as Compose (`deploy/`) |

Manifests: `deploy/k8s/base` (app) and `deploy/kustomization.yaml` (app + monitoring).

## Design choices

* **One FuelGrid replica, `Recreate` strategy, no autoscaler.** The decision engine and the lock-step clock run
  inside the process. Two pods would each plan and each send shipments to the same simulator. `Recreate` stops the
  old pod before the new one starts, so there is never a moment with two planners. One process handled about
  160 requests/s with zero errors in the load test, far above an operations room's needs. Scaling out would first
  need the engine separated from the API behind leader election; we did not add that complexity.
* **Probes.** A startup probe allows time for the trained model to load. Readiness stays green in degraded mode on
  purpose: when the simulator is down the console must keep serving the last good state. Liveness restarts a hung
  process.
* **Hardened pod.** Non-root (UID 10001), no privilege escalation, all Linux capabilities dropped, default seccomp
  profile, CPU and memory requests and limits sized from the load test.
* **Versioned images.** Images are tagged with the git SHA, and `/api/health` reports the running build.

## Run it locally

Any local cluster works. With Docker Desktop: *Settings → Kubernetes → Enable Kubernetes*. The cluster shares
Docker's image store, so a locally built image needs no registry.

```bash
docker build --build-arg GIT_SHA=dev -t fuelgrid:dev .
kubectl apply -k deploy                      # app + Prometheus + Grafana   (app only: kubectl apply -k deploy/k8s/base)
kubectl -n fuelgrid rollout status deployment/fuelgrid
```

With [kind](https://kind.sigs.k8s.io), load the image first: `kind load docker-image fuelgrid:dev`.

Optional secrets, from the same `.env` Compose uses:

```bash
kubectl -n fuelgrid create secret generic fuelgrid-secrets --from-env-file=.env
kubectl -n fuelgrid rollout restart deployment/fuelgrid
```

## Open it

```bash
kubectl -n fuelgrid port-forward svc/fuelgrid 8080:8080      # console  http://127.0.0.1:8080
kubectl -n fuelgrid port-forward svc/grafana 3000:3000       # Grafana  http://127.0.0.1:3000
kubectl -n fuelgrid port-forward svc/prometheus 9090:9090    # Prometheus
kubectl -n fuelgrid port-forward svc/simulator 8000:8000     # simulator admin http://127.0.0.1:8000/admin
```

## Deploy a new version, roll back

```bash
TAG=$(git rev-parse --short HEAD)
docker build --build-arg GIT_SHA=$TAG -t fuelgrid:$TAG .
kubectl -n fuelgrid set image deployment/fuelgrid fuelgrid=fuelgrid:$TAG
kubectl -n fuelgrid rollout status deployment/fuelgrid --timeout=180s   # fails if the new pod never becomes healthy
kubectl -n fuelgrid rollout undo deployment/fuelgrid                    # back to the previous version
kubectl -n fuelgrid rollout history deployment/fuelgrid                 # the last 5 versions are kept
```

To make a tag the declared default, set `images[0].newTag` in `deploy/k8s/base/kustomization.yaml` (or run
`kustomize edit set image fuelgrid=fuelgrid:$TAG` there), since `kubectl apply -k` re-applies that tag.

## Demo: self-healing

```bash
kubectl -n fuelgrid delete pod -l app.kubernetes.io/name=fuelgrid
kubectl -n fuelgrid get pods -w
```

A replacement pod starts, loads the model, re-reads the world from the simulator and resumes planning. Decisions
and audit history survive when a database is configured (`DATABASE_URL`); memory-only mode starts fresh.

## Continuous integration

The CI job `k8s` creates a kind cluster on every push, deploys these manifests with the freshly built image, checks
that FuelGrid reports the simulator healthy and the right build, then deletes the pod and checks that the
replacement becomes healthy.

## Tear down

```bash
kubectl delete namespace fuelgrid
```
