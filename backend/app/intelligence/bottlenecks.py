"""Bottleneck analytics: which limit is actually holding the network back right now?

After every plan we look at how close each constraint is to binding (depot sending capacity, depot stock, road maximum) and,
for any need the plan could not fully cover, which constraint on the candidate roads explains the gap."""
from app.intelligence.policies.common import dispatch_remaining, usable_routes
from app.state.store import Snapshot

FUEL_RESERVE = 0.10


def analyse(snap: Snapshot, cfg, needs, lines) -> list[dict]:
    items: list[dict] = []
    disp = dispatch_remaining(snap)
    used_disp: dict[str, float] = {}
    used_stock: dict[tuple[str, str], float] = {}
    for rid, fuel, _sid, q in lines:
        r = snap.routes[rid]
        used_disp[r.source_depot_id] = used_disp.get(r.source_depot_id, 0.0) + q
        used_stock[(r.source_depot_id, fuel)] = used_stock.get((r.source_depot_id, fuel), 0.0) + q
        if q >= 0.98 * r.max_shipment:
            items.append({"kind": "road_maximum", "where": rid, "detail": f"{q:,.0f} L is the road's maximum load of {r.max_shipment:,.0f} L", "utilization": 1.0, "severity": "WATCH"})
    for did, used in used_disp.items():
        cap = disp.get(did, 0.0)
        util = used / cap if cap > 0 else 1.0
        if util >= 0.85:
            items.append({"kind": "dispatch_capacity", "where": did, "detail": f"{used:,.0f} of {cap:,.0f} L sending capacity used this tick", "utilization": round(min(util, 1.0), 2),
                          "severity": "WARNING" if util >= 0.97 else "WATCH"})
    for (did, fuel), used in used_stock.items():
        d = snap.depots[did]
        avail = max(0.0, d.inventory.get(fuel, 0.0) - FUEL_RESERVE * d.capacity.get(fuel, 0.0))
        util = used / avail if avail > 0 else 1.0
        if util >= 0.8:
            items.append({"kind": "depot_stock", "where": f"{did} {fuel}", "detail": f"plan draws {used:,.0f} of {avail:,.0f} L available above the reserve", "utilization": round(min(util, 1.0), 2),
                          "severity": "WARNING" if util >= 0.95 else "WATCH"})
    delivered: dict[tuple[str, str], float] = {}
    for _rid, fuel, sid, q in lines:
        delivered[(sid, fuel)] = delivered.get((sid, fuel), 0.0) + q
    open_routes = {r.id for r in usable_routes(snap)}
    for n in needs:
        got = delivered.get((n.sid, n.fuel), 0.0)
        gap = n.need - got
        if gap > 500 and gap > 0.15 * n.need:
            cand = [r for r in snap.routes.values() if r.destination_station_id == n.sid]
            why = []
            if not any(r.id in open_routes for r in cand):
                why.append("every road to it is closed or its depot is closed")
            else:
                for r in cand:
                    if r.id not in open_routes:
                        continue
                    d = snap.depots[r.source_depot_id]
                    if d.inventory.get(n.fuel, 0.0) < 500:
                        why.append(f"{d.name} is out of {n.fuel.lower()}")
                    elif disp.get(d.id, 0.0) <= used_disp.get(d.id, 0.0) + 1:
                        why.append(f"{d.name} has no sending capacity left this tick")
                    elif delivered.get((n.sid, n.fuel), 0.0) >= r.max_shipment - 1:
                        why.append(f"road {r.id} is at its maximum load")
            if n.headroom <= 0:
                why.append("the station tank is full")
            items.append({"kind": "unfilled_need", "where": f"{snap.stations[n.sid].name} {n.fuel}", "detail": f"{gap:,.0f} L still short after the plan" + (f": {'; '.join(dict.fromkeys(why))}" if why else ""),
                          "utilization": round(min(1.0, got / n.need), 2), "severity": "CRITICAL" if n.severity == "CRITICAL" else "WARNING", "shortfall_l": round(gap)})
    order = {"CRITICAL": 0, "WARNING": 1, "WATCH": 2}
    items.sort(key=lambda x: (order.get(x["severity"], 3), -x["utilization"]))
    return items[:8]
