"""Demand forecasters. Registry pattern => swap / version / fall back without touching callers.

seasonal (v2, default)
    expected demand = hour-of-day prior x region factor x event multiplier x residual level
    * prior          : the simulator's documented daily profile
    * region factor  : /v1/regions demand_factor
    * event multiplier: reconstructed from /v1/events, so a spike is anticipated the moment it is announced and
                        its end is anticipated too (no lag from a moving average)
    * residual level : EWMA of observed / (prior x region x multiplier). It is ~1.0 when the world behaves as
                        explained; a sustained departure means *unexplained* demand and is flagged as an anomaly.
seasonal_v1   the earlier model (EWMA of observed/prior only) - kept for A/B comparison and rollback
moving_avg    trailing mean, the last-resort fallback
"""
import statistics
from datetime import timedelta

from app.intelligence.priors import prior_per_tick
from app.intelligence.types import Forecast
from app.state.store import Snapshot, StateStore

V1 = "seasonal-ewma-v1"
V2 = "seasonal-events-v2"


# ----------------------------------------------------------------------------------------------- helpers
def _future_hours(snap: Snapshot, horizon: int) -> list[int]:
    t0 = snap.instance.sim_time
    return [(t0 + timedelta(minutes=snap.tick_minutes * k)).hour for k in range(1, horizon + 1)]


def _affects(params: dict, station) -> bool:
    """Event filters: an empty list means 'all'."""
    sids, rids = params.get("station_ids") or [], params.get("region_ids") or []
    if not sids and not rids:
        return True
    return station.id in sids or station.region_id in rids


def event_multiplier(snap: Snapshot, station, tick: int) -> float:
    """Demand multiplier the simulator applies to `station` at `tick`, from announced spike events."""
    m = 1.0
    for e in snap.events:
        if e.type == "demand_spike" and e.start_tick <= tick < e.end_tick and _affects(e.parameters, station):
            m *= float(e.parameters.get("multiplier", 1.5))
    return m


def _ratio_series_v1(store: StateStore, snap: Snapshot, sid: str, fuel: str, n: int) -> list[float]:
    st = snap.stations[sid]
    out = []
    for _, d, sim_time in store.series(sid, fuel, n):
        p = prior_per_tick(st.demand_profile, fuel, sim_time.hour, snap.tick_minutes)
        out.append(d / p if p > 0 else 1.0)
    return out


def _ewma(xs: list[float], a: float) -> float:
    level = xs[0]
    for r in xs[1:]:
        level = a * r + (1 - a) * level
    return level


# ----------------------------------------------------------------------------------------------- v2
def seasonal_forecast(store: StateStore, snap: Snapshot, sid: str, fuel: str, horizon: int) -> Forecast:
    st = snap.stations[sid]
    rf = store.regions.get(st.region_id, 1.0)
    series = store.series(sid, fuel, 48)
    ratios, ticks = [], []
    for t, d, sim_time in series:
        expected = prior_per_tick(st.demand_profile, fuel, sim_time.hour, snap.tick_minutes) * rf * event_multiplier(snap, st, t)
        if expected > 0:
            ratios.append(d / expected)
            ticks.append(t)
    if len(ratios) >= 3:
        resid = _ewma(ratios, 0.25)
        cv = statistics.pstdev(ratios) / max(statistics.fmean(ratios), 1e-6)
        base = statistics.median(ratios[:-3]) if len(ratios) > 8 else 1.0
        sd = statistics.pstdev(ratios[:-3]) if len(ratios) > 8 else 0.12
        z = (statistics.fmean(ratios[-3:]) - base) / max(sd, 0.05)
    else:
        resid, cv, z = 1.0, 0.2, 0.0
    hours = _future_hours(snap, horizon)
    per_tick = []
    for k, h in enumerate(hours, start=1):
        base_rate = prior_per_tick(st.demand_profile, fuel, h, snap.tick_minutes) * rf
        per_tick.append(base_rate * event_multiplier(snap, st, snap.tick + k) * resid)
    sigma_rel = max(0.07, min(cv, 0.6))
    conf = max(0.0, min(1.0, 1 - 2.0 * sigma_rel)) * min(1.0, len(ratios) / 8)
    total_level = per_tick[0] / max(prior_per_tick(st.demand_profile, fuel, hours[0], snap.tick_minutes), 1e-6) if per_tick else 1.0
    # unexplained demand: residual well above 1 for a sustained stretch (spikes announced as events are NOT anomalies)
    anomaly = z > 3.0 and resid > 1.25
    return Forecast(sid, fuel, per_tick, sigma_rel, round(conf, 3), round(total_level, 3), V2, anomaly=anomaly, z=z)


# ----------------------------------------------------------------------------------------------- v1
def seasonal_v1_forecast(store: StateStore, snap: Snapshot, sid: str, fuel: str, horizon: int) -> Forecast:
    """prior(hour-of-day profile) x level, level = EWMA of observed/prior. sigma from residual spread."""
    st = snap.stations[sid]
    ratios = _ratio_series_v1(store, snap, sid, fuel, 48)
    if len(ratios) >= 3:
        level = _ewma(ratios, 0.35)
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
    return Forecast(sid, fuel, per_tick, sigma_rel, round(conf, 3), level, V1, anomaly=z > 3.0 and level > 1.3, z=z)


# ----------------------------------------------------------------------------------------------- fallback
def moving_average_forecast(store: StateStore, snap: Snapshot, sid: str, fuel: str, horizon: int) -> Forecast:
    """Fallback: trailing mean, or a capacity-proportional guess if there is no history at all."""
    vals = [d for _, d, _ in store.series(sid, fuel, 8)]
    if vals:
        avg = statistics.fmean(vals)
        sd = statistics.pstdev(vals) / avg if avg > 0 and len(vals) > 1 else 0.3
    else:
        avg, sd = snap.stations[sid].capacity.get(fuel, 10000) / 96 / 2, 0.5
    return Forecast(sid, fuel, [avg] * horizon, max(0.15, min(sd, 0.6)), 0.3 if vals else 0.1, 1.0, "moving-average-v1")


FORECASTERS = {"seasonal": seasonal_forecast, "seasonal_v1": seasonal_v1_forecast, "moving_avg": moving_average_forecast}
MODEL_VERSION = V2
