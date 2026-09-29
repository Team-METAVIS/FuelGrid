"""Planner: forecast -> risk -> policy (with automatic fallbacks) -> impact estimate -> review flags."""
import time

from app.core import metrics as m
from app.core.logging import get_logger
from app.intelligence.bottlenecks import analyse
from app.intelligence.forecast import FORECASTERS
from app.intelligence.policies import optimizer, rules
from app.intelligence.policies.common import compute_needs, usable_routes
from app.intelligence.projection import SEV_ORDER, assess, incoming_by_tick, simulate
from app.intelligence.types import Forecast, Plan, Recommendation, Risk
from app.ml.manager import manager
from app.state.store import Snapshot, StateStore

log = get_logger("planner")
POLICIES = {"optimizer": optimizer.solve, "rules": rules.solve}


def forecast_all(store: StateStore, snap: Snapshot, cfg, forecaster: str | None = None) -> tuple[dict, str | None]:
    """Returns forecasts; on forecaster failure falls back to moving average (recorded)."""
    name, reason, out = forecaster or cfg.forecaster, None, {}
    if name == "learned":
        try:
            got = manager.forecast_batch(store, snap, cfg.horizon_ticks, adapt=cfg.online_adaptation)
        except Exception as e:  # never let the model take the platform down
            got, reason = None, f"{type(e).__name__}: {e}"
            log.error("learned_forecaster_failed", error=reason)
        if got is None:
            reason = reason or "no trained model available"
            m.FALLBACK.labels("forecaster", "no_model").inc()
            name = "moving_avg"
        else:
            out = dict(got)
            cold = 0
            for s in snap.stations:  # brand-new or sparsely observed series: plain moving average until the model can take over
                for f in snap.fuels:
                    if (s, f) not in out:
                        out[(s, f)] = FORECASTERS["moving_avg"](store, snap, s, f, cfg.horizon_ticks)
                        cold += 1
            return out, None  # cold-start series on a moving average are normal warm-up, not a fault
    for attempt in (name, "moving_avg"):
        try:
            fn = FORECASTERS[attempt]
            out = {(s, f): fn(store, snap, s, f, cfg.horizon_ticks) for s in snap.stations for f in snap.fuels}
            if attempt != name:
                m.FALLBACK.labels("forecaster", reason or "error").inc()
            return out, reason
        except Exception as e:  # model unavailable -> fallback (spec section 11)
            reason = f"{type(e).__name__}: {e}"
            log.error("forecaster_failed", forecaster=attempt, error=reason)
    raise RuntimeError("all forecasters failed")


def _unmet_total(snap: Snapshot, forecasts, lines) -> float:
    """Expected unmet liters over the horizon if `lines` were dispatched (counterfactual roll-forward)."""
    by: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for rid, fuel, sid, q in lines:
        by.setdefault((sid, fuel), []).append((snap.tick + 1 + snap.routes[rid].transit_ticks, q))
    total = 0.0
    for (sid, fuel), f in forecasts.items():
        st = snap.stations[sid]
        arr = incoming_by_tick(snap, sid, fuel, by.get((sid, fuel)))
        total += simulate(st.inventory.get(fuel, 0.0), st.capacity.get(fuel, 0.0), f.per_tick, arr, snap.tick)[1]
    return total


def _compare(snap, cfg, forecasts, needs, policy, lines) -> dict:
    """Shadow evaluation: what would the *other* policy and doing nothing have achieved on this same state?"""
    out = {"none": round(_unmet_total(snap, forecasts, [])), policy: round(_unmet_total(snap, forecasts, lines)),
           "shipped": {policy: round(sum(x[3] for x in lines))}}
    other = "rules" if policy == "optimizer" else "optimizer"
    try:
        olines, _ = POLICIES[other](snap, needs, cfg)
        out[other] = round(_unmet_total(snap, forecasts, olines))
        out["shipped"][other] = round(sum(x[3] for x in olines))
    except Exception:  # shadow is best-effort and must never affect the live decision
        pass
    return out


def _alternatives(snap: Snapshot, sid: str, fuel: str, chosen: str) -> list[dict]:
    alts = []
    for r in snap.routes.values():
        if r.destination_station_id != sid or r.id == chosen:
            continue
        d = snap.depots[r.source_depot_id]
        ok = r.status == "AVAILABLE" and d.status in ("OPEN", "CONSTRAINED")
        alts.append({
            "route_id": r.id, "depot_id": d.id, "transit_ticks": r.transit_ticks,
            "depot_stock": d.inventory.get(fuel, 0.0), "feasible": ok,
            "why_not": None if ok else f"route {r.status}" if r.status != "AVAILABLE" else f"depot {d.status}",
        })
    return alts


def plan(store: StateStore, snap: Snapshot, cfg, policy: str | None = None, forecaster: str | None = None) -> Plan:
    t0 = time.perf_counter()
    notes: list[str] = []
    forecasts, fc_fallback = forecast_all(store, snap, cfg, forecaster)
    if fc_fallback:
        notes.append(f"forecaster fallback: {fc_fallback}")
    risks: dict[tuple[str, str], Risk] = {k: assess(snap, f, cfg) for k, f in forecasts.items()}
    routes = usable_routes(snap)
    needs = compute_needs(snap, forecasts, risks, cfg, routes)

    policy = policy or cfg.active_policy
    fallback_used, fb_reason, status = False, None, ""
    try:
        lines, status = POLICIES[policy](snap, needs, cfg)
    except Exception as e:
        fb_reason = f"{policy} failed ({type(e).__name__}: {e})"
        log.error("policy_failed", policy=policy, error=fb_reason)
        m.FALLBACK.labels("policy", type(e).__name__).inc()
        lines, status = rules.solve(snap, needs, cfg)
        fallback_used, policy = True, "rules"

    comparison = _compare(snap, cfg, forecasts, needs, policy, lines)
    try:
        bottlenecks = analyse(snap, cfg, needs, lines)
    except Exception:  # analytics must never affect a decision
        bottlenecks = []
    recs = _build_recs(snap, cfg, policy, forecasts, risks, lines)
    if recs:
        m.RECS.labels("proposed").inc(len(recs))
    return Plan(snap.tick, policy, recs, sorted(risks.values(), key=lambda r: (-SEV_ORDER[r.severity], -r.stockout_prob)),
                status, (time.perf_counter() - t0) * 1000, fallback_used, fb_reason, notes,
                pred1={k: f.per_tick[0] for k, f in forecasts.items()},
                raw1={k: (f.raw1, f.hi1) for k, f in forecasts.items() if f.raw1 is not None},
                anomalies=[(f.station_id, f.fuel, f.z, f.level) for f in forecasts.values() if f.anomaly],
                forecast_model=next(iter(forecasts.values())).model, comparison=comparison, forecasts=forecasts, bottlenecks=bottlenecks)


def _build_recs(snap, cfg, policy, forecasts: dict[tuple[str, str], Forecast], risks, lines) -> list[Recommendation]:
    by_key: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for rid, fuel, sid, q in lines:
        by_key.setdefault((sid, fuel), []).append((rid, q))
    recs = []
    for (sid, fuel), items in by_key.items():
        f, before = forecasts[(sid, fuel)], risks[(sid, fuel)]
        extra = [(snap.tick + 1 + snap.routes[rid].transit_ticks, q) for rid, q in items]
        after = assess(snap, f, cfg, extra)
        st = snap.stations[sid]
        arr0 = incoming_by_tick(snap, sid, fuel)
        arr1 = incoming_by_tick(snap, sid, fuel, extra)
        inv0, cap = st.inventory.get(fuel, 0.0), st.capacity.get(fuel, 0.0)
        _, unmet_b, _ = simulate(inv0, cap, f.per_tick, arr0, snap.tick)
        _, unmet_a, _ = simulate(inv0, cap, f.per_tick, arr1, snap.tick)
        for rid, q in items:
            r = snap.routes[rid]
            hrs = before.hours_to_stockout
            reasons = [
                f"{st.name} {fuel}: {inv0:,.0f} L on hand vs {before.demand_horizon:,.0f} L expected demand "
                f"over next {len(f.per_tick) * snap.tick_minutes / 60:.0f}h",
                *before.signals,
                f"{r.source_depot_id} -> {sid} via {rid} ({r.transit_ticks} ticks, max {r.max_shipment:,.0f} L)",
                f"solver: {policy}",
            ]
            low_conf = f.confidence < cfg.min_confidence
            recs.append(Recommendation(
                tick=snap.tick, station_id=sid, fuel=fuel, depot_id=r.source_depot_id, route_id=rid, quantity=q,
                severity=before.severity, hours_to_stockout=hrs, inventory=inv0, demand_horizon=before.demand_horizon,
                risk_before=before.stockout_prob, risk_after=after.stockout_prob, unmet_before=unmet_b,
                unmet_after=unmet_a, confidence=f.confidence, policy=policy, reasons=reasons,
                alternatives=_alternatives(snap, sid, fuel, rid), requires_review=low_conf,
                review_reason="forecast confidence below threshold" if low_conf else None,
            ))
    recs.sort(key=lambda r: (-SEV_ORDER[r.severity], r.station_id))
    return recs
