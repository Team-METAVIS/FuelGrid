"""Replay, assistant, model registry and experiment history."""
import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.intelligence import assistant
from app.intelligence.forecast import V1, V2

router = APIRouter(prefix="/api")
DOCS = Path(__file__).resolve().parents[3] / "docs"
MAX_REPLAY_POINTS = 300
_CACHE: dict[str, tuple[float, object]] = {}  # tiny TTL cache: the remote database is the slow part


async def _cached(key: str, ttl: float, make):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        value = await make()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"database is busy, try again ({type(e).__name__})") from None
    _CACHE[key] = (time.time(), value)
    return value


def rt(request: Request):
    return request.app.state.rt


# --------------------------------------------------------------------------------------------- assistant
class Ask(BaseModel):
    question: str = Field(min_length=2, max_length=400)


@router.get("/assistant/status")
async def assistant_status(r=Depends(rt)):
    for p in (r.llm.gemini, r.llm.groq):
        await r.llm.refresh_models(p)  # cached; shows which models were discovered
    return r.llm.status()


@router.post("/assistant")
async def ask(body: Ask, r=Depends(rt)):
    return await assistant.ask(r, body.question)


# --------------------------------------------------------------------------------------------- replay
@router.get("/replay/runs")
async def replay_runs(r=Depends(rt)):
    if not r.repo.up:
        return {"runs": [], "current": r.run_id, "note": "database unavailable"}

    async def make():
        rows = await r.repo.fetch(
            "select run_id, min(tick) as first_tick, max(tick) as last_tick, count(*) as points, max(created_at) as last_at "
            "from fg_ticks group by run_id order by max(created_at) desc limit 20")
        return [{**x, "last_at": str(x["last_at"])} for x in rows]
    return {"runs": await _cached("runs", 15, make), "current": r.run_id}


@router.get("/replay/{run_id}")
async def replay(run_id: str, r=Depends(rt)):
    if not r.repo.up:
        raise HTTPException(503, "database unavailable")

    async def make():
        ticks, decisions, audit = await asyncio.gather(
            r.repo.fetch("select tick, service_level, unmet_liters, payload->'stations' as stations from fg_ticks where run_id=:r order by tick", {"r": run_id}),
            r.repo.fetch(
                "select distinct on (payload->>'id') payload->>'id' as id, tick, station_id, fuel, route_id, quantity, severity, status, actor "
                "from fg_decisions where run_id=:r order by payload->>'id', id desc", {"r": run_id}),
            r.repo.fetch("select tick, kind, severity, message from fg_audit where run_id=:r and tick is not null order by id", {"r": run_id}),
        )
        if not ticks:
            raise HTTPException(404, "unknown run")
        if len(ticks) > MAX_REPLAY_POINTS:  # keep the payload small for very long runs
            step = len(ticks) / MAX_REPLAY_POINTS
            ticks = [ticks[int(i * step)] for i in range(MAX_REPLAY_POINTS)] + [ticks[-1]]
        ticks = [{"tick": t["tick"], "service_level": t["service_level"], "unmet_liters": t["unmet_liters"], "payload": {"stations": t["stations"]}} for t in ticks]
        return {"run_id": run_id, "ticks": ticks, "decisions": decisions, "audit": audit}
    # a finished run never changes; the run being recorded right now is cached only briefly
    return await _cached(f"run:{run_id}", 5 if run_id == r.run_id else 300, make)


# --------------------------------------------------------------------------------------------- registry / experiments
FORECASTERS = {
    "seasonal": {"version": V2, "title": "Seasonal + events (v2)", "description": "Daily profile x region factor x announced events x learned residual"},
    "seasonal_v1": {"version": V1, "title": "Seasonal moving level (v1)", "description": "Daily profile x moving average of observed/expected"},
    "moving_avg": {"version": "moving-average-v1", "title": "Moving average (fallback)", "description": "Last-resort trailing mean"},
}
POLICIES = {
    "optimizer": {"title": "OR-Tools optimizer", "description": "Integer program: fair, urgency-weighted, all limits enforced"},
    "rules": {"title": "Rule-based baseline", "description": "Greedy by urgency; used as automatic fallback"},
}


@router.get("/models")
async def models(r=Depends(rt)):
    c = r.cfg
    return {
        "forecasters": [{"key": k, **v, "active": k == c.forecaster} for k, v in FORECASTERS.items()],
        "policies": [{"key": k, **v, "active": k == c.active_policy} for k, v in POLICIES.items()],
        "live_mape": r.engine.mape(), "rolled_back": c.policy_rolled_back,
        "parameters": {"target_cover_ticks": c.target_cover_ticks, "safety_z": c.safety_z, "depot_reserve_frac": c.depot_reserve_frac,
                       "horizon_ticks": c.horizon_ticks, "decision_every_ticks": c.decision_every_ticks},
    }


@router.get("/experiments")
async def experiments(limit: int = 60, r=Depends(rt)):
    if not r.repo.up:
        return []
    rows = await r.repo.fetch("select created_at, name, policy, forecaster, model_version, scenario, metrics from fg_experiments order by id desc limit :n", {"n": limit})
    return [{**x, "created_at": str(x["created_at"])} for x in rows]


@router.get("/tuning")
def tuning():
    f = DOCS / "tuning_results.json"
    return json.loads(f.read_text()) if f.exists() else {"rows": []}
