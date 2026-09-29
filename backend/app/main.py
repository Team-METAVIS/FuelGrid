import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.routes import router
from app.core.apistats import ApiStats, StatsMiddleware
from app.core.config import Settings, get_settings
from app.core.logging import get_logger, setup_logging
from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from app.simulator.client import SimulatorClient
from app.state.store import StateStore
from app.state.sync import Synchronizer

WEB = Path(__file__).resolve().parents[2] / "frontend" / "dist"
log = get_logger("main")


@dataclass
class Runtime:
    cfg: Settings
    client: SimulatorClient
    store: StateStore
    sync: Synchronizer
    repo: Repo
    engine: DecisionEngine
    api_stats: ApiStats
    run_id: str


def build_runtime(cfg: Settings, api_stats: ApiStats) -> Runtime:
    run_id = time.strftime("%m%d%H%M%S")
    client, store, repo = SimulatorClient(cfg), StateStore(), Repo(cfg.database_url)
    sync = Synchronizer(client, store)
    engine = DecisionEngine(cfg, store, client, repo, run_id)
    sync.on_snapshot.append(engine.on_snapshot)
    sync.on_reset.append(engine.reset)
    return Runtime(cfg, client, store, sync, repo, engine, api_stats, run_id)


def create_app(cfg: Settings | None = None, start_background: bool = True) -> FastAPI:
    cfg = cfg or get_settings()
    setup_logging(cfg.log_level)
    stats = ApiStats()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        rt = build_runtime(cfg, stats)
        app.state.rt = rt
        if start_background:
            await rt.repo.start()
            rt.repo.audit(rt.run_id, "integration", "FuelGrid started", "info", None, {"policy": cfg.active_policy})
            rt.sync.start()
        log.info("started", run_id=rt.run_id, sim=cfg.sim_base_url, db=bool(cfg.database_url))
        yield
        await rt.sync.stop()
        await rt.client.aclose()

    app = FastAPI(title="FuelGrid", version="0.1.0", lifespan=lifespan)
    app.add_middleware(StatsMiddleware, stats=stats)
    Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok"}

    if WEB.exists():
        app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            f = (WEB / path).resolve()
            if path and f.is_file() and WEB in f.parents:
                return FileResponse(f)
            return FileResponse(WEB / "index.html")  # client-side routing

    return app


app = create_app()
