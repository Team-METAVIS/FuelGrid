import asyncio
import json
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api import views

router = APIRouter(prefix="/api")


def rt(request: Request):
    return request.app.state.rt


def guard(request: Request, x_api_key: str | None = Header(default=None)):
    key = request.app.state.rt.cfg.api_key
    if key and x_api_key != key:
        raise HTTPException(401, "invalid api key")


@router.get("/state")
async def state(r=Depends(rt)):
    return views.build_state(r)


@router.get("/health")
async def health(r=Depends(rt)):
    return views.build_health(r)


@router.get("/decisions")
async def decisions(limit: int = 100, r=Depends(rt)):
    ids = list(r.engine.history)[-limit:][::-1]
    return [r.engine.decisions[i].to_dict() for i in ids if i in r.engine.decisions]


@router.post("/decisions/{did}/approve", dependencies=[Depends(guard)])
async def approve(did: int, r=Depends(rt)):
    try:
        return (await r.engine.approve(did)).to_dict()
    except KeyError:
        raise HTTPException(404, "This recommendation no longer exists (the simulator may have been reset).") from None
    except ValueError as e:
        raise HTTPException(409, f"Already handled: {e}") from None


@router.post("/decisions/{did}/reject", dependencies=[Depends(guard)])
async def reject(did: int, r=Depends(rt)):
    try:
        return r.engine.reject(did).to_dict()
    except KeyError:
        raise HTTPException(404, "unknown decision") from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None


@router.post("/decisions/approve-all", dependencies=[Depends(guard)])
async def approve_all(r=Depends(rt)):
    out = []
    for d in list(r.engine.decisions.values()):
        if d.status == "PROPOSED":
            out.append((await r.engine.approve(d.id)).to_dict())
    return out


@router.get("/audit")
async def audit(limit: int = 100, r=Depends(rt)):
    if r.repo.up:
        try:
            return await r.repo.fetch("select created_at,tick,kind,severity,message from fg_audit order by id desc limit :n", {"n": limit})
        except Exception:
            pass
    return list(r.repo.mem_audit)[:limit]


class SettingsIn(BaseModel):
    auto_execute: bool | None = None
    policy: str | None = None
    forecaster: str | None = None
    paused: bool | None = None
    max_auto_liters: float | None = None


@router.post("/settings", dependencies=[Depends(guard)])
async def settings(body: SettingsIn, r=Depends(rt)):
    c = r.cfg
    if body.auto_execute is not None:
        c.auto_execute = body.auto_execute
    if body.policy is not None:
        if body.policy not in ("optimizer", "rules"):
            raise HTTPException(422, "policy must be optimizer|rules")
        c.active_policy = body.policy
        if body.policy == "optimizer":
            c.policy_rolled_back = False
            r.engine.fallbacks_in_row = 0
    if body.forecaster is not None:
        if body.forecaster not in ("seasonal", "moving_avg"):
            raise HTTPException(422, "forecaster must be seasonal|moving_avg")
        c.forecaster = body.forecaster
    if body.paused is not None:
        r.engine.paused = body.paused
    if body.max_auto_liters is not None:
        c.max_auto_liters = body.max_auto_liters
    r.repo.audit(r.run_id, "operator", f"Settings changed: {body.model_dump(exclude_none=True)}")
    return views.settings_view(r)


@router.post("/cycle", dependencies=[Depends(guard)])
async def cycle_now(r=Depends(rt)):
    snap = r.store.snapshot
    if snap is None or snap.age_s() > 1.0:  # reuse a fresh snapshot instead of hammering the simulator
        await r.sync.refresh()
    plan = await r.engine.cycle_coalesced()
    return {"ok": plan is not None, "recommendations": len(plan.recommendations) if plan else 0}


# ---- scenario / chaos console (proxy to simulator admin; self-test only) ----
class EventIn(BaseModel):
    type: str
    start_tick: int | None = None
    duration_ticks: int = 12
    parameters: dict = {}


class FaultIn(BaseModel):
    type: str
    duration_seconds: int = 30
    parameters: dict = {}


async def _admin(r, method, path, body=None):
    try:
        return await r.client.admin(method, path, body)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text) from None
    except httpx.HTTPError as e:
        raise HTTPException(503, f"simulator admin unreachable: {e}") from None


@router.post("/sim/{action}", dependencies=[Depends(guard)])
async def sim_control(action: str, r=Depends(rt)):
    if action not in ("run", "pause", "step", "reset"):
        raise HTTPException(404)
    out = await _admin(r, "POST", f"/admin/{action}")
    r.repo.audit(r.run_id, "scenario", f"Simulator {action}")
    if action == "reset":
        r.store.clear()
        r.sync.warm = False
        r.engine.reset()
    r.sync.trigger.set()
    return out


@router.post("/sim/inject/event", dependencies=[Depends(guard)])
async def inject_event(body: EventIn, r=Depends(rt)):
    tick = body.start_tick if body.start_tick is not None else (r.store.snapshot.tick + 1 if r.store.snapshot else 0)
    payload = {"type": body.type, "start_tick": tick, "duration_ticks": body.duration_ticks, "parameters": body.parameters}
    out = await _admin(r, "POST", "/admin/events", payload)
    r.repo.audit(r.run_id, "scenario", f"Injected event {body.type}", "warn", tick, payload)
    r.sync.trigger.set()
    return out


@router.post("/sim/inject/fault", dependencies=[Depends(guard)])
async def inject_fault(body: FaultIn, r=Depends(rt)):
    payload = {"type": body.type, "duration_seconds": body.duration_seconds, "parameters": body.parameters}
    out = await _admin(r, "POST", "/admin/faults", payload)
    r.repo.audit(r.run_id, "scenario", f"Injected fault {body.type} for {body.duration_seconds}s", "warn", None, payload)
    return out


@router.post("/sim/faults/clear", dependencies=[Depends(guard)])
async def clear_faults(r=Depends(rt)):
    out = await _admin(r, "POST", "/admin/faults/clear")
    r.repo.audit(r.run_id, "scenario", "Faults cleared")
    return out


@router.get("/stream")
async def stream(request: Request, r=Depends(rt)):
    """UI push: emit a tiny 'update' hint on every cycle/snapshot; the UI then re-GETs /api/state."""
    async def gen():
        last = None
        while True:
            if await request.is_disconnected():
                break
            snap = r.store.snapshot
            marker = (snap.tick, snap.fetched_at, snap.stale, r.engine.version) if snap else None
            if marker != last:
                last = marker
                yield {"event": "update", "data": json.dumps({"tick": snap.tick if snap else None})}
            await asyncio.sleep(0.5)
    return EventSourceResponse(gen(), ping=15)


@router.get("/briefing")
async def briefing(r=Depends(rt)):
    from app.intelligence import briefing as b

    return b.build(r)


@router.get("/timeline")
async def timeline(r=Depends(rt)):
    return list(r.engine.timeline)


@router.get("/telemetry")
async def telemetry(r=Depends(rt)):
    return {"api": r.api_stats.series(), "summary": r.api_stats.summary()}


@router.get("/forecast")
async def forecast_detail(station_id: str, fuel: str, r=Depends(rt)):
    """Observed demand, forecast with uncertainty band, and projected inventory (with/without in-flight supply)."""
    from app.intelligence import planner
    from app.intelligence.projection import incoming_by_tick, simulate

    snap = r.store.snapshot
    if snap is None or station_id not in snap.stations:
        raise HTTPException(404, "no such station / no data yet")
    plan = r.engine.plan
    fcs = plan.forecasts if plan and plan.tick == snap.tick and plan.forecasts else planner.forecast_all(r.store, snap, r.cfg)[0]
    f = fcs.get((station_id, fuel))
    if f is None:
        raise HTTPException(404, "no such fuel")
    st = snap.stations[station_id]
    inv, cap = st.inventory.get(fuel, 0.0), st.capacity.get(fuel, 0.0)
    arr = incoming_by_tick(snap, station_id, fuel)
    traj, cur = [], inv
    for k, d in enumerate(f.per_tick, start=1):
        cur = min(cap, cur + arr.get(snap.tick + k, 0.0))
        cur = max(0.0, cur - d)
        traj.append(round(cur))
    first, unmet, _ = simulate(inv, cap, f.per_tick, arr, snap.tick)
    # what-if: same projection if every pending recommendation for this station/fuel were approved now
    extra = [(snap.tick + 1 + snap.routes[d.rec.route_id].transit_ticks, d.rec.quantity)
             for d in r.engine.decisions.values()
             if d.status == "PROPOSED" and d.rec.station_id == station_id and d.rec.fuel == fuel]
    arr2 = incoming_by_tick(snap, station_id, fuel, extra)
    cur2, traj2 = inv, []
    for k, d in enumerate(f.per_tick, start=1):
        cur2 = max(0.0, min(cap, cur2 + arr2.get(snap.tick + k, 0.0)) - d)
        traj2.append(round(cur2))
    hist = [{"tick": t, "demand": round(v, 1)} for t, v, _ in r.store.series(station_id, fuel, 48)]
    band = 1.28 * f.sigma_rel
    return {
        "station_id": station_id, "fuel": fuel, "tick": snap.tick, "model": f.model, "confidence": f.confidence,
        "level": f.level, "sigma_rel": f.sigma_rel, "capacity": cap, "inventory": inv,
        "history": hist,
        "forecast": [{"tick": snap.tick + k, "demand": round(d, 1), "lo": round(d * (1 - band), 1), "hi": round(d * (1 + band), 1),
                      "inventory": traj[k - 1], "with_plan": traj2[k - 1]} for k, d in enumerate(f.per_tick, start=1)],
        "pending_liters": sum(q for _, q in extra),
        "ticks_to_stockout": first, "unmet_horizon": round(unmet),
    }


BENCH_FILE = Path(__file__).resolve().parents[3] / "docs" / "benchmark_results.json"


@router.get("/benchmarks")
def benchmarks():
    if not BENCH_FILE.exists():
        return {"results": [], "generated": None}
    return json.loads(BENCH_FILE.read_text())


@router.get("/scenarios")
def scenarios():
    from app.scenarios.library import SCENARIOS

    return [{"name": k, "title": v["title"], "description": v["description"], "events": v["events"]} for k, v in SCENARIOS.items()]


@router.post("/scenarios/{name}/apply", dependencies=[Depends(guard)])
async def apply_scenario(name: str, r=Depends(rt)):
    from app.scenarios.library import SCENARIOS

    spec = SCENARIOS.get(name)
    if not spec:
        raise HTTPException(404, "unknown scenario")
    base = (r.store.snapshot.tick if r.store.snapshot else 0) + 1
    for ev in spec["events"]:
        first = min(e["start_tick"] for e in spec["events"])
        await _admin(r, "POST", "/admin/events", {**ev, "start_tick": base + ev["start_tick"] - first})
    r.repo.audit(r.run_id, "scenario", f"Applied scenario '{spec['title']}'", "warn", base)
    r.sync.trigger.set()
    return {"applied": name, "events": len(spec["events"])}
