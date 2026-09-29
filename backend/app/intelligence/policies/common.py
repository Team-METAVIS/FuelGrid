"""Shared helpers for allocation policies."""
from dataclasses import dataclass

from app.intelligence.projection import incoming_by_tick, simulate
from app.intelligence.types import Forecast, Risk
from app.state.store import Snapshot

MIN_SHIPMENT = 500.0
UNIT = 100.0  # optimizer works in 100 L units (integers)


@dataclass
class Need:
    sid: str
    fuel: str
    need: float  # liters wanted on top of what is already projected
    headroom: float  # liters the station can still absorb
    weight: int
    eta_min: int
    severity: str


def usable_routes(snap: Snapshot):
    """Routes that the simulator would accept right now (status checks from the validation order)."""
    out = []
    for r in snap.routes.values():
        d, s = snap.depots.get(r.source_depot_id), snap.stations.get(r.destination_station_id)
        if not d or not s:
            continue
        if r.status == "AVAILABLE" and s.status == "OPEN" and d.status in ("OPEN", "CONSTRAINED"):
            out.append(r)
    return out


def dispatch_remaining(snap: Snapshot) -> dict[str, float]:
    """Dispatch capacity left this tick per depot (pending + departing-this-tick already count)."""
    used: dict[str, float] = {}
    for a in snap.allocations:
        if a.status == "PENDING" or (a.status == "IN_TRANSIT" and a.departure_tick == snap.tick):
            used[a.source_depot_id] = used.get(a.source_depot_id, 0) + a.quantity
    return {d.id: max(0.0, d.dispatch_capacity_per_tick - used.get(d.id, 0.0)) for d in snap.depots.values()}


def compute_needs(snap: Snapshot, forecasts: dict[tuple[str, str], Forecast], risks: dict[tuple[str, str], Risk], cfg,
                  routes) -> list[Need]:
    needs = []
    sev_w = {"CRITICAL": 30, "WARNING": 10, "WATCH": 3, "OK": 1}
    for (sid, fuel), f in forecasts.items():
        st = snap.stations[sid]
        rt = [r for r in routes if r.destination_station_id == sid]
        if not rt or st.status != "OPEN":
            continue
        risk = risks[(sid, fuel)]
        eta = 1 + min(r.transit_ticks for r in rt)
        eta = min(eta, len(f.per_tick) - 1)
        arr = incoming_by_tick(snap, sid, fuel)
        cap = st.capacity.get(fuel, 0.0)
        _, _, inv_eta = simulate(st.inventory.get(fuel, 0.0), cap, f.per_tick[:eta], arr, snap.tick)
        cover = cfg.target_cover_ticks
        window = f.per_tick[eta:eta + cover] or f.per_tick[-cover:]
        dem = sum(window)
        safety = 1.28 * f.sigma_rel * dem  # ~P90 buffer (uncertainty-aware)
        later = sum(q for t, q in arr.items() if snap.tick + eta < t <= snap.tick + eta + cover)
        need = max(0.0, dem + safety - inv_eta - later)
        headroom = max(0.0, min(cap - inv_eta - later, cap - st.inventory.get(fuel, 0.0)))
        # only act on real shortages: at risk, or noticeably low (avoid draining depots for nothing)
        if risk.severity == "OK" and inv_eta > 0.35 * cap:
            continue
        if need >= MIN_SHIPMENT * 0.5 and headroom > 0:
            tts = risk.ticks_to_stockout
            urgency = 1 + 4 / (1 + tts) if tts is not None else 1.0  # imminent stockouts weigh more
            needs.append(Need(sid, fuel, need, headroom, max(1, round(sev_w[risk.severity] * urgency)), eta, risk.severity))
    return needs
