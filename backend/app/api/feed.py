"""Generic live-feed API and data-source switching.

Point any real system at /api/feed/* and FuelGrid runs on it; nothing here is simulator-specific."""
import asyncio
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.adapters.feed import Ack, TelemetryIn, TopologyIn

router = APIRouter(prefix="/api")


def rt(request: Request):
    return request.app.state.rt


def key_ok(expected: str | None, given: str | None) -> bool:
    """True when no key is configured or the given one matches (constant-time comparison)."""
    return not expected or hmac.compare_digest((given or "").encode(), expected.encode())


def guard(request: Request, x_api_key: str | None = Header(default=None)):
    if not key_ok(request.app.state.rt.cfg.api_key, x_api_key):
        raise HTTPException(401, "invalid api key")


# ------------------------------------------------------------------------------------------------ ingestion
@router.post("/feed/topology", dependencies=[Depends(guard)])
async def feed_topology(body: TopologyIn, r=Depends(rt)):
    out = r.feed.set_topology(body)
    r.repo.audit(r.run_id, "integration", f"Feed topology received: {out['depots']} depots, {out['stations']} stations, {out['routes']} routes", "info")
    return out


@router.post("/feed/telemetry", dependencies=[Depends(guard)])
async def feed_telemetry(body: TelemetryIn, r=Depends(rt)):
    return r.feed.ingest(body)


@router.get("/feed/orders")
async def feed_orders(status: str | None = None, r=Depends(rt)):
    """Dispatch orders approved by operators. Executing systems poll this (or receive the optional webhook)."""
    return [o.model_dump(mode="json") for o in r.feed.pending_orders(status)]


@router.post("/feed/orders/{order_id}/ack", dependencies=[Depends(guard)])
async def feed_ack(order_id: int, body: Ack, r=Depends(rt)):
    body.order_id = order_id
    if not r.feed.ack(body):
        raise HTTPException(404, "unknown order")
    r.sync.trigger.set()
    return {"ok": True}


@router.get("/feed/status")
async def feed_status(r=Depends(rt)):
    return r.feed.status()


# ------------------------------------------------------------------------------------------------ source switching
class SourceIn(BaseModel):
    kind: str


def describe(r) -> dict:
    active = r.client
    return {
        "active": active.kind,
        "sources": [
            {"kind": "simulator", "label": r.sim.label, "supports_admin": True, "active": active.kind == "simulator",
             "detail": r.cfg.sim_base_url},
            {"kind": "feed", "label": r.feed.label, "supports_admin": False, "active": active.kind == "feed",
             "detail": f"{len(r.feed.stations_)} stations, {len(r.feed.depots_)} depots received"},
        ],
        "demo": r.demo.status() if r.demo else {"running": False},
    }


@router.get("/source")
async def source(r=Depends(rt)):
    return describe(r)


@router.post("/source", dependencies=[Depends(guard)])
async def switch(body: SourceIn, r=Depends(rt)):
    if body.kind not in ("simulator", "feed"):
        raise HTTPException(422, "kind must be simulator|feed")
    from app.main import switch_source

    await switch_source(r, body.kind)
    return describe(r)


# ------------------------------------------------------------------------------------------------ built-in independent world
class DemoStart(BaseModel):
    seed: int = 7
    speed: float = Field(4.0, gt=0, le=100)  # ticks per second


class DemoChange(BaseModel):
    kind: str  # demand_shift | demand_shock | sensor_dropout | road_closure | new_station | capacity_change
    magnitude: float = Field(1.4, gt=0, le=10)  # multiplier: 0 or below would zero or negate demand
    duration_ticks: int = Field(24, ge=1, le=10_000)


@router.post("/feed/demo/start", dependencies=[Depends(guard)])
async def demo_start(body: DemoStart, r=Depends(rt)):
    from app.main import start_demo

    await start_demo(r, body.seed, body.speed)
    return describe(r)["demo"]


@router.post("/feed/demo/stop", dependencies=[Depends(guard)])
async def demo_stop(r=Depends(rt)):
    if r.demo:
        await r.demo.stop()
    return describe(r)["demo"]


@router.post("/feed/demo/change", dependencies=[Depends(guard)])
async def demo_change(body: DemoChange, r=Depends(rt)):
    if not r.demo or not r.demo.running:
        raise HTTPException(409, "the demo world is not running")
    msg = r.demo.world.inject(body.kind, body.magnitude, body.duration_ticks)
    r.repo.audit(r.run_id, "scenario", f"Demo world change: {msg}", "warn", r.demo.world.tick)
    await asyncio.sleep(0)
    return {"ok": True, "change": msg}


@router.get("/feed/demo/status")
async def demo_status(r=Depends(rt)):
    return describe(r)["demo"]
