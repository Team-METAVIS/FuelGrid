"""Inventory projection, stockout risk and counterfactual impact of a candidate plan."""
import math

from app.intelligence.types import Forecast, Risk
from app.state.store import Snapshot

SEV_ORDER = {"OK": 0, "WATCH": 1, "WARNING": 2, "CRITICAL": 3}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def incoming_by_tick(
    snap: Snapshot, sid: str, fuel: str, extra: list[tuple[int, float]] | None = None
) -> dict[int, float]:
    """Liters arriving at a station per tick from in-flight allocations (+ hypothetical `extra`)."""
    out: dict[int, float] = {}
    for a in snap.transit_to(sid, fuel):
        r = snap.routes.get(a.route_id)
        eta = (a.expected_arrival_tick or (snap.tick + 1 + (r.transit_ticks if r else 2))) + snap.late_by_route().get(a.route_id, 0)
        out[eta] = out.get(eta, 0) + a.quantity
    for eta, q in extra or []:
        out[eta] = out.get(eta, 0) + q
    return out


def simulate(inv0: float, cap: float, fc: list[float], arrivals: dict[int, float], tick0: int):
    """Deterministic roll-forward. Returns (first stockout offset or None, unmet liters, end inventory)."""
    inv, unmet, first = inv0, 0.0, None
    for k, d in enumerate(fc, start=1):
        inv = min(cap, inv + arrivals.get(tick0 + k, 0.0))
        if d > inv:
            unmet += d - inv
            if first is None:
                first = k
            inv = 0.0
        else:
            inv -= d
    return first, unmet, inv


def stockout_prob(inv0: float, fc: list[float], arrivals_total: float, sigma_rel: float) -> float:
    """P(cumulative demand > inventory + incoming) under a normal error model."""
    mu = sum(fc)
    sd = max(1.0, sigma_rel * mu)
    return 1 - _norm_cdf((inv0 + arrivals_total - mu) / sd)


def assess(snap: Snapshot, f: Forecast, cfg, extra: list[tuple[int, float]] | None = None) -> Risk:
    st = snap.stations[f.station_id]
    inv0, cap = st.inventory.get(f.fuel, 0.0), st.capacity.get(f.fuel, 0.0)
    arr = incoming_by_tick(snap, f.station_id, f.fuel, extra)
    H = len(f.per_tick)
    first, _unmet, _ = simulate(inv0, cap, f.per_tick, arr, snap.tick)
    incoming = sum(q for t, q in arr.items() if t <= snap.tick + H)
    p = stockout_prob(inv0, f.per_tick, incoming, f.sigma_rel)
    hrs = None if first is None else first * snap.tick_minutes / 60
    sev = "OK"
    if st.status != "OPEN":
        sev = "WATCH"  # cannot be resupplied anyway
    elif first is not None and first <= cfg.critical_cover_ticks:
        sev = "CRITICAL"
    elif first is not None or p > 0.5:
        sev = "WARNING"
    elif p > 0.15:
        sev = "WATCH"
    signals = [f"demand level x{f.level:.2f} vs baseline", f"P(stockout)={p:.0%}"]
    if f.anomaly:
        signals.append(f"demand anomaly z={f.z:.1f}")
    if st.demand_multiplier > 1.05:
        signals.append(f"demand_multiplier {st.demand_multiplier:.2f}")
    if st.status != "OPEN":
        signals.append(f"station {st.status}")
    return Risk(f.station_id, f.fuel, inv0, cap, incoming, sum(f.per_tick), first, hrs, round(p, 4), sev,
                f.confidence, signals)
