# Deployment guide

FuelGrid is one container (API + operator console) plus a PostgreSQL container. Nothing else is required.

## 1. How FuelGrid and the simulator connect

The organizer's simulator is **passive**: it exposes an HTTP API and never calls anybody. FuelGrid is the client, so there is
nothing to configure *inside* the simulator. You point **FuelGrid at the simulator** with one setting:

| Where FuelGrid runs | Where the simulator runs | `SIM_BASE_URL` |
|---|---|---|
| On your machine (`uvicorn`) | Docker on the same machine, port 8000 published | `http://127.0.0.1:8000` |
| Docker Compose from this repository | The `simulator` service in the same compose file | `http://simulator:8000` (set for you) |
| A single `docker run` container | Simulator container on the host | `http://host.docker.internal:8000` (Windows/macOS) or the host's IP (Linux) |
| Cloud (Vercel/Render/…) | Your laptop or a server | A public URL for the simulator (a tunnel such as `cloudflared tunnel --url http://127.0.0.1:8000`) |

On Windows use `127.0.0.1`, not `localhost` (`localhost` tries IPv6 first and adds ~200 ms per connection).
The console can also switch the source at run time (*Data sources* page), including to the built-in independent demo world or a live feed.

## 2. Everything in Docker (recommended for judges)

```bash
docker compose up --build            # simulator + FuelGrid + PostgreSQL/pgvector
docker compose --profile monitoring up --build   # plus Prometheus and Grafana
```

Console: http://127.0.0.1:8080. The database volume `fuelgrid-pgdata` keeps decisions, the audit log, model registry and settings
across restarts. Compose waits for the database to be healthy before FuelGrid starts.

### Using the published image

```bash
docker network create fuelgrid
docker run -d --name fuelgrid-db --network fuelgrid -e POSTGRES_USER=fuelgrid -e POSTGRES_PASSWORD=fuelgrid \
  -e POSTGRES_DB=fuelgrid -v fuelgrid-pgdata:/var/lib/postgresql/data pgvector/pgvector:pg16
docker run -d --name fuelgrid --network fuelgrid -p 8080:8080 \
  -e DATABASE_URL=postgresql://fuelgrid:fuelgrid@fuelgrid-db:5432/fuelgrid \
  -e SIM_BASE_URL=http://host.docker.internal:8000 \
  zaberdev/fuelgrid:latest
```

`scripts/deploy.sh [tag]` deploys a tag with a health gate and automatic rollback to the previous image.

## 3. Database

Plain PostgreSQL 16 with the `pgvector` extension (used only for incident memory). Migrations in `backend/app/db/migrations` are
applied automatically at start-up and tracked in `fg_migrations`. Leave `DATABASE_URL` empty to run memory-only (nothing is persisted).
Any other Postgres with pgvector works by changing `DATABASE_URL`; migration `005` enables row-level security so a database that
also exposes a public REST API (as Supabase does) does not expose these tables.

## 4. Console on Vercel, API elsewhere

The React console can be hosted on Vercel while the API runs in Docker on a machine that can reach the simulator.

1. Vercel project → root directory `frontend` (`frontend/vercel.json` sets the Vite build and single-page-app rewrites).
2. Environment variable `VITE_API_BASE=https://<your-api-host>` (no trailing slash), then deploy.
3. On the API host set `CORS_ORIGINS=https://<your-project>.vercel.app` (comma separate several origins) and, because the API is now on the
   internet, `API_KEY=<secret>`: the console asks for the key on the first write action.
4. The API must be served over HTTPS (or the browser will block mixed content).

### The API on Vercel?

`backend/vercel.json` is provided for completeness, but Vercel runs short-lived serverless functions. FuelGrid keeps a background
control loop, a live event stream (SSE), a model in memory and a database pool, and the dependency set (scikit-learn, OR-Tools, NumPy)
is close to Vercel's size limits. **Treat it as experimental**; the supported production path is the Docker image on any container host.

## 5. Configuration reference

All settings are environment variables; `.env.example` lists them with defaults. The ones most deployments touch:

| Variable | Purpose |
|---|---|
| `SIM_BASE_URL` | Where the simulator is |
| `DATABASE_URL` | PostgreSQL connection string |
| `API_KEY` | Require `X-API-Key` for every write action |
| `CORS_ORIGINS` | Browser origins allowed when the console is hosted elsewhere |
| `DATA_SOURCE` | `simulator` or `feed` at start-up |
| `GEMINI_API_KEY`, `GROQ_API_KEY` | Optional wording for the assistant (answers are grounded in live data either way) |
| `AUTO_EXECUTE` | Start with automatic approval on (default off) |

## 6. Health and monitoring

| Probe | Path | Meaning |
|---|---|---|
| Liveness | `/healthz` | The process is up |
| Readiness | `/readyz` | 503 until the data source has delivered a snapshot |
| Components | `/api/health` | Database, data source, event stream, prediction, decision engine |
| Metrics | `/metrics` | Prometheus (`fg_*`); alert rules in `deploy/alerts.yml`, Grafana dashboard in `deploy/grafana` |
