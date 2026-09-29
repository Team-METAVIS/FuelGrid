import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.adapters.feed import FeedSource
from app.api.controls import restore
from app.api.controls import router as controls_router
from app.api.data import router as data_router
from app.api.extras import router as extras_router
from app.api.feed import router as feed_router
from app.api.routes import router
from app.core.apistats import ApiStats, StatsMiddleware
from app.core.config import Settings, get_settings
from app.core.events import EventBus
from app.core.logging import get_logger, setup_logging
from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from app.intelligence.llm import LlmRouter
from app.ml.manager import manager
from app.simulator.client import SimulatorClient
from app.state.clock import LockStepClock
from app.state.store import StateStore
from app.state.sync import Synchronizer
from app.worldgen.driver import DemoWorld

WEB = Path(__file__).resolve().parents[2] / "frontend" / "dist"
log = get_logger("main")


@dataclass
class Runtime:
    cfg: Settings
    client: object  # the ACTIVE data source (a DataSource: simulator or live feed)
    store: StateStore
    sync: Synchronizer
    repo: Repo
    engine: DecisionEngine
    api_stats: ApiStats
    run_id: str
    bus: EventBus
    llm: LlmRouter
    sim: SimulatorClient
    feed: FeedSource
    demo: DemoWorld | None = None
    clock: LockStepClock | None = None


def build_runtime(cfg: Settings, api_stats: ApiStats) -> Runtime:
    run_id = time.strftime("%m%d%H%M%S")
    sim, feed = SimulatorClient(cfg), FeedSource(cfg)
    client = feed if cfg.data_source == "feed" else sim
    store, repo = StateStore(), Repo(cfg.database_url)
    bus = EventBus()
    repo.bus = bus
    sync = Synchronizer(client, store)
    sync.bus = bus
    feed.on_change = sync.trigger.set  # new telemetry wakes the synchronizer immediately
    engine = DecisionEngine(cfg, store, client, repo, run_id)
    sync.on_snapshot.append(engine.on_snapshot)
    sync.on_reset.append(engine.reset)
    engine.refresh = sync.refresh
    manager.audit = lambda kind, msg, sev="info": repo.audit(run_id, kind, msg, sev)
    manager.bus = bus
    llm = LlmRouter(cfg.gemini_api_key, cfg.groq_api_key, cfg.llm_timeout_s)
    rt = Runtime(cfg, client, store, sync, repo, engine, api_stats, run_id, bus, llm, sim, feed)
    rt.clock = LockStepClock(sim, sync)
    return rt


async def switch_source(rt: Runtime, kind: str) -> None:
    """Point the whole platform at a different data source without restarting it."""
    if rt.client.kind == kind:
        return
    await rt.sync.stop()
    if rt.clock:
        await rt.clock.stop()
    new = rt.feed if kind == "feed" else rt.sim
    rt.client = rt.sync.client = rt.engine.client = new
    rt.cfg.data_source = kind
    rt.store.clear()
    rt.store.snapshot = None
    rt.store.regions = {}
    rt.sync.warm, rt.sync.last_tick = False, -1
    rt.sync.consecutive_failures, rt.sync.last_error = 0, None
    rt.engine.reset()
    rt.sync.start()
    rt.sync.trigger.set()
    rt.bus.publish("source.switched", kind=kind)
    rt.repo.audit(rt.run_id, "integration", f"Data source switched to: {new.label}", "warn")
    log.info("source_switched", kind=kind)


async def start_demo(rt: Runtime, seed: int, speed: float) -> None:
    """Start the built-in independent world (different network, products, clock and dynamics) on the live-feed adapter."""
    await switch_source(rt, "feed")
    if rt.demo is None:
        rt.demo = DemoWorld(rt.feed)
    rt.demo.after_tick = rt.sync.refresh
    await rt.demo.start(seed, speed)
    rt.repo.audit(rt.run_id, "scenario", f"Independent demo world started (seed {seed}, {rt.demo.speed:g} ticks/s)", "info")
    rt.sync.trigger.set()


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
            await rt.engine.memory.load()
            await manager.load(rt.repo)
            await restore(rt)  # operator settings persisted in the database (auto-dispatch is never re-enabled automatically)
            rt.repo.audit(rt.run_id, "integration", "FuelGrid started", "info", None, {"policy": cfg.active_policy, "source": cfg.data_source})
            rt.sync.start()
        log.info("started", run_id=rt.run_id, source=cfg.data_source, sim=cfg.sim_base_url, db=bool(cfg.database_url))
        yield
        if rt.demo:
            await rt.demo.stop()
        if rt.clock:
            await rt.clock.stop()
        await rt.sync.stop()
        await rt.sim.aclose()
        await rt.feed.aclose()

    app = FastAPI(title="FuelGrid", version="0.2.0", lifespan=lifespan)
    app.add_middleware(StatsMiddleware, stats=stats)
    origins = [o.strip() for o in cfg.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["Content-Type", "X-API-Key", "Last-Event-ID"], max_age=600)
    Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(app, include_in_schema=False)
    app.include_router(router)
    app.include_router(extras_router)
    app.include_router(feed_router)
    app.include_router(controls_router)
    app.include_router(data_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz(request: Request):
        """Readiness: the platform has a snapshot from its data source and can serve decisions. 503 until then."""
        rt = request.app.state.rt
        snap = rt.store.snapshot
        if snap is None:
            return JSONResponse({"ready": False, "reason": "no data from the data source yet", "source": rt.client.kind}, status_code=503)
        return {"ready": True, "source": rt.client.kind, "tick": snap.tick, "stale": snap.stale, "database": rt.repo.up}

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
