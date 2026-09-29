"""Deterministic benchmark runner: reset -> inject scenario -> step N ticks -> plan/execute -> score.

The simulator is deterministic (same seed + actions + events => identical world), so policies are compared on
identical worlds. "none" is the do-nothing control; "rules" is the greedy baseline; "optimizer" is CP-SAT."""
import statistics
import time
from collections.abc import Callable

from app.scenarios.library import SCENARIOS


async def reset_world(rt):
    c = rt.client
    await c.admin("POST", "/admin/faults/clear")
    await c.admin("POST", "/admin/pause")
    await c.admin("POST", "/admin/reset")
    await c.admin("POST", "/admin/pause")
    rt.store.clear()
    rt.sync.warm = False
    rt.sync.last_tick = -1
    rt.engine.reset()


async def run_scenario(rt, scenario: str, policy: str, ticks: int = 192, forecaster: str | None = None,
                       progress: Callable[[str], None] | None = None) -> dict:
    spec = SCENARIOS[scenario]
    e, c = rt.engine, rt.client
    e.bench = True
    prev = (rt.cfg.auto_execute, rt.cfg.forecaster)
    rt.cfg.auto_execute = False
    if forecaster:
        rt.cfg.forecaster = forecaster
    try:
        await reset_world(rt)
        for ev in spec["events"]:
            await c.admin("POST", "/admin/events", ev)
        await rt.sync.refresh()
        every = rt.cfg.decision_every_ticks
        cycle_ms, series, liters, fallbacks = [], [], 0.0, 0
        t0 = time.time()
        for t in range(ticks):
            await c.admin("POST", "/admin/step")
            snap = await rt.sync.refresh()
            if snap is None:
                continue
            if policy != "none" and snap.tick % every == 0:
                plan = await e.cycle(snap, force_policy=policy)
                if plan:
                    cycle_ms.append(plan.runtime_ms)
                    fallbacks += int(plan.fallback_used)
                    for d in [d for d in e.decisions.values() if d.status == "PROPOSED"]:
                        await e.approve(d.id, actor="benchmark")
                        liters += d.rec.quantity if d.status == "EXECUTED" else 0
            if t % 8 == 0:
                series.append({"tick": snap.tick, "service_level": snap.metrics.service_level,
                               "unmet": snap.metrics.unmet_demand_liters})
            if progress and t % 48 == 47:
                progress(f"  {scenario}/{policy} tick {snap.tick}: SL={snap.metrics.service_level:.4f}")
        m = await c.metrics()
        failed = sum(1 for d in e.decisions.values() if d.status == "FAILED")
        return {
            "scenario": scenario, "policy": policy, "forecaster": rt.cfg.forecaster, "ticks": ticks,
            "service_level": round(m.service_level, 5), "served_l": round(m.served_demand_liters),
            "unmet_l": round(m.unmet_demand_liters), "allocated_l": round(m.allocation_liters),
            "sim_allocation_failures": m.allocation_failures, "rejected_decisions": failed,
            "decisions": len(e.decisions), "fallbacks": fallbacks,
            "cycle_ms_avg": round(statistics.fmean(cycle_ms), 1) if cycle_ms else 0.0,
            "cycle_ms_p95": round(sorted(cycle_ms)[int(len(cycle_ms) * 0.95)], 1) if cycle_ms else 0.0,
            "forecast_mape": round(e.mape(), 4) if e.mape() is not None else None,
            "wall_s": round(time.time() - t0, 1), "series": series,
        }
    finally:
        e.bench = False
        rt.cfg.auto_execute, rt.cfg.forecaster = prev
        await c.admin("POST", "/admin/pause")
