"""Demand forecasters. Registry pattern => swap / version / fall back without touching callers."""
import statistics
from datetime import timedelta

from app.intelligence.priors import prior_per_tick
from app.intelligence.types import Forecast
from app.state.store import Snapshot, StateStore

MODEL_VERSION = "seasonal-ewma-v1"


def _future_hours(snap: Snapshot, horizon: int) -> list[int]:
    t0 = snap.instance.sim_time
    return [(t0 + timedelta(minutes=snap.tick_minutes * k)).hour for k in range(1, horizon + 1)]


def _ratio_series(store: StateStore, snap: Snapshot, sid: str, fuel: str, n: int) -> list[float]:
    st = snap.stations[sid]
    out = []
    for _, d, sim_time in store.series(sid, fuel, n):
        p = prior_per_tick(st.demand_profile, fuel, sim_time.hour, snap.tick_minutes)
        out.append(d / p if p > 0 else 1.0)
    return out


def seasonal_forecast(store: StateStore, snap: Snapshot, sid: str, fuel: str, horizon: int) -> Forecast:
    """prior(hour-of-day profile) x level, level = EWMA of observed/prior. sigma from residual spread."""
    st = snap.stations[sid]
    ratios = _ratio_series(store, snap, sid, fuel, 48)
    if len(ratios) >= 3:
        level, a = ratios[0], 0.35
        for r in ratios[1:]:
            level = a * r + (1 - a) * level
        mean = statistics.fmean(ratios)
        cv = (statistics.pstdev(ratios) / mean) if mean > 0 else 0.3
        base = statistics.median(ratios[:-3]) if len(ratios) > 8 else 1.0
        recent = statistics.fmean(ratios[-3:])
        sd = statistics.pstdev(ratios[:-3]) if len(ratios) > 8 else 0.15
        z = (recent - base) / max(sd, 0.05)
    else:
        level, cv, z = 1.0, 0.3, 0.0
    hours = _future_hours(snap, horizon)
    per_tick = [prior_per_tick(st.demand_profile, fuel, h, snap.tick_minutes) * level for h in hours]
    sigma_rel = max(0.08, min(cv, 0.6))
    conf = max(0.0, min(1.0, (1 - 2.0 * sigma_rel))) * min(1.0, len(ratios) / 12)
    return Forecast(sid, fuel, per_tick, sigma_rel, round(conf, 3), level, MODEL_VERSION,
                    anomaly=z > 3.0 and level > 1.3, z=z)


def moving_average_forecast(store: StateStore, snap: Snapshot, sid: str, fuel: str, horizon: int) -> Forecast:
    """Fallback: trailing mean, or a capacity-proportional guess if there is no history at all."""
    vals = [d for _, d, _ in store.series(sid, fuel, 8)]
    if vals:
        avg = statistics.fmean(vals)
        sd = statistics.pstdev(vals) / avg if avg > 0 and len(vals) > 1 else 0.3
    else:
        avg, sd = snap.stations[sid].capacity.get(fuel, 10000) / 96 / 2, 0.5
    return Forecast(sid, fuel, [avg] * horizon, max(0.15, min(sd, 0.6)), 0.3 if vals else 0.1, 1.0,
                    "moving-average-v1")


FORECASTERS = {"seasonal": seasonal_forecast, "moving_avg": moving_average_forecast}
