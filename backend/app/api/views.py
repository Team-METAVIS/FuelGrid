"""Read-models for the dashboard (pure functions over app state)."""
import dataclasses
import os
import time

import psutil

_PROC = psutil.Process()
_START = time.time()
VERSION = "0.1.0"
GIT_SHA = os.environ.get("GIT_SHA", "dev")


def build_health(rt) -> dict:
    snap = rt.store.snapshot
    sim_ok = rt.client.breaker_open is False and rt.client.last_error is None and snap is not None
    age = snap.age_s() if snap else None
    stale = bool(snap and (snap.stale or age > rt.cfg.stale_after_s))
    comps = {
        "database": {"status": "healthy" if rt.repo.up else ("disabled" if not rt.repo.url else "degraded"),
                     "detail": "Supabase Postgres" if rt.repo.up else "buffering writes in memory"},
        "data_source": {"status": "healthy" if sim_ok and not stale else "degraded",
                      "detail": rt.client.last_error or ("stale data flag" if stale else rt.client.label),
                      "breaker_open": rt.client.breaker_open, "label": rt.client.label},
        "event_stream": {"status": "healthy" if (rt.sync.sse_connected or not rt.client.supports_stream) else "degraded",
                         "detail": "SSE connected" if rt.sync.sse_connected else ("pushed by the feed" if not rt.client.supports_stream else "polling fallback")},
        "prediction": {"status": "degraded" if (rt.engine.plan and rt.engine.plan.notes) else "healthy",
                       "detail": rt.engine.plan.forecast_model if rt.engine.plan else "warming up",
                       "mape": rt.engine.mape()},
        "decision_engine": {"status": "degraded" if (rt.engine.plan and rt.engine.plan.fallback_used) else "healthy",
                            "detail": (rt.engine.plan.policy + " / " + rt.engine.plan.solver_status) if rt.engine.plan else "warming up",
                            "last_cycle_ms": round(rt.engine.last_cycle_ms, 1)},
    }
    overall = "healthy" if all(c["status"] in ("healthy", "disabled") for c in comps.values()) else "degraded"
    if snap is None:
        overall = "down"
    return {
        "status": overall, "components": comps, "api": rt.api_stats.summary(),
        "snapshot_age_s": round(age, 1) if age is not None else None, "stale": stale,
        "mode": "cached-state (degraded)" if (stale or not sim_ok) and snap else "live",
        "process": {"cpu_pct": _PROC.cpu_percent(None), "rss_mb": round(_PROC.memory_info().rss / 1e6, 1),
                    "uptime_s": round(time.time() - _START)},
        "version": VERSION, "build": GIT_SHA,
    }


def build_state(rt) -> dict:
    """Dashboard payload. The heavy body is cached per data version (many operators, one computation);
    health is cheap and always fresh."""
    snap = rt.store.snapshot
    if snap is None:
        return {"ready": False, "health": build_health(rt)}
    c = rt.cfg
    key = (id(snap), snap.fetched_at, rt.engine.version, id(rt.engine.plan),
           (c.auto_execute, c.active_policy, c.forecaster, rt.engine.paused, c.policy_rolled_back))
    cached = getattr(rt, "_state_cache", None)
    if cached is None or cached[0] != key:
        cached = (key, _build_body(rt, snap))
        rt._state_cache = cached
    return {**cached[1], "health": build_health(rt)}


def _build_body(rt, snap) -> dict:
    eng = rt.engine
    plan = eng.plan
    risks = [dataclasses.asdict(r) for r in plan.risks] if plan else []
    stations = []
    for s in snap.stations.values():
        stations.append({
            "id": s.id, "name": s.name, "region_id": s.region_id, "status": s.status, "profile": s.demand_profile,
            "demand_multiplier": s.demand_multiplier,
            "fuels": {f: {"inventory": s.inventory.get(f, 0), "capacity": s.capacity.get(f, 0)} for f in snap.fuels},
        })
    depots = [{
        "id": d.id, "name": d.name, "region_id": d.region_id, "status": d.status, "dispatch_capacity": d.dispatch_capacity_per_tick,
        "fuels": {f: {"inventory": d.inventory.get(f, 0), "capacity": d.capacity.get(f, 0)} for f in snap.fuels},
    } for d in snap.depots.values()]
    incoming = [dataclasses.asdict(a) if dataclasses.is_dataclass(a) else a.model_dump() for a in snap.allocations
                if a.status in ("PENDING", "IN_TRANSIT")]
    arrivals = [a.model_dump() for a in snap.arrivals if a.status != "ARRIVED"][:12]
    demand = {}
    for s in snap.stations:
        demand[s] = {f: [round(v, 1) for _, v, _ in rt.store.series(s, f, 32)] for f in snap.fuels}
    return {
        "ready": True,
        "instance": snap.instance.model_dump(mode="json"),
        "metrics": snap.metrics.model_dump(),
        "stations": stations, "depots": depots,
        "routes": [r.model_dump() for r in snap.routes.values()],
        "in_transit": incoming, "supply_arrivals": arrivals, "events": [e.model_dump() for e in snap.events][:10],
        "demand": demand,
        "risks": risks,
        "recommendations": [d.to_dict() for d in eng.decisions.values() if d.status == "PROPOSED"],
        "incidents": [{"key": k, **{a: b for a, b in v.items() if not a.startswith("_")}} for k, v in eng.incidents.items()],
        "plan": {"policy": plan.policy, "solver_status": plan.solver_status, "runtime_ms": round(plan.runtime_ms, 1),
                 "fallback_used": plan.fallback_used, "fallback_reason": plan.fallback_reason, "tick": plan.tick,
                 "notes": plan.notes, "forecast_model": plan.forecast_model, "comparison": plan.comparison,
                 "cadence_ticks": round(eng.cadence, 1) if eng.cadence is not None else None} if plan else None,
        "settings": settings_view(rt),
        "source": {"kind": rt.client.kind, "label": rt.client.label, "supports_admin": rt.client.supports_admin},
    }


def settings_view(rt) -> dict:
    c = rt.cfg
    return {"auto_execute": c.auto_execute, "policy": c.active_policy, "forecaster": c.forecaster,
            "paused": rt.engine.paused, "rolled_back": c.policy_rolled_back, "decision_every_ticks": c.decision_every_ticks,
            "max_auto_liters": c.max_auto_liters, "min_confidence": c.min_confidence}
