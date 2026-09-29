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


def route_blocked_at(snap: Snapshot, route_id: str, tick: int) -> bool:
    """True if an announced route_disruption covers `tick` (a shipment that departs then would FAIL)."""
    for e in snap.events:
        if e.type == "route_disruption" and e.start_tick <= tick < e.end_tick:
            ids = e.parameters.get("route_ids") or []
            if not ids or route_id in ids:
                return True
    return False


def usable_routes(snap: Snapshot):
    """Routes the simulator would accept for a shipment created now (it departs next tick).
    Uses live status plus announced disruptions, so we do not ship into a road that is about to close."""
    out = []
    depart = snap.tick + 1
    for r in snap.routes.values():
        d, s = snap.depots.get(r.source_depot_id), snap.stations.get(r.destination_station_id)
        if not d or not s:
            continue
        if r.status == "AVAILABLE" and s.status == "OPEN" and d.status in ("OPEN", "CONSTRAINED") and not route_blocked_at(snap, r.id, depart):
            out.append(r)
    return out


def precheck(snap: Snapshot, depot_id: str, station_id: str, route_id: str, fuel: str, qty: float) -> tuple[str, str] | None:
    """Mirror of the simulator's validation order (guide section 5.2). Returns (code, message) or None if valid.
    Catching these locally avoids a rejected call and gives the operator a precise reason."""
    r, d, s = snap.routes.get(route_id), snap.depots.get(depot_id), snap.stations.get(station_id)
    if not r or not d or not s:
        return "NOT_FOUND", "unknown depot, station or route"
    if r.source_depot_id != depot_id or r.destination_station_id != station_id:
        return "ROUTE_MISMATCH", "route does not connect this depot and station"
    if d.status not in ("OPEN", "CONSTRAINED"):
        return "DEPOT_CLOSED", f"depot is {d.status}"
    if s.status != "OPEN":
        return "STATION_CLOSED", f"station is {s.status}"
    if r.status != "AVAILABLE" or route_blocked_at(snap, route_id, snap.tick + 1):
        return "ROUTE_DISRUPTED", "route is disrupted or about to be"
    if qty > r.max_shipment:
        return "ROUTE_CAPACITY_EXCEEDED", f"{qty:,.0f} L exceeds the route maximum of {r.max_shipment:,.0f} L"
    if d.inventory.get(fuel, 0.0) < qty:
        return "INSUFFICIENT_INVENTORY", f"depot holds {d.inventory.get(fuel, 0.0):,.0f} L"
    if dispatch_remaining(snap).get(depot_id, 0.0) < qty:
        return "DISPATCH_CAPACITY_EXCEEDED", "depot dispatch capacity for this tick is used up"
    if s.inventory.get(fuel, 0.0) + qty > s.capacity.get(fuel, 0.0):
        return "DESTINATION_CAPACITY_EXCEEDED", "station tank would overflow"
    return None


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
        safety = cfg.safety_z * f.sigma_rel * dem  # uncertainty-aware buffer (z=1.28 ~ P90)
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
