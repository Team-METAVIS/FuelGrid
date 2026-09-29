"""Rule-based greedy policy. Serves as (a) the automatic fallback and (b) the benchmark baseline."""
from app.intelligence.policies.common import MIN_SHIPMENT, UNIT, Need, dispatch_remaining, usable_routes
from app.state.store import Snapshot


def solve(snap: Snapshot, needs: list[Need], cfg) -> tuple[list[tuple[str, str, str, float]], str]:
    routes = usable_routes(snap)
    disp = dispatch_remaining(snap)
    stock = {(d.id, f): d.inventory.get(f, 0.0) for d in snap.depots.values() for f in ("DIESEL", "PETROL", "OCTANE")}
    out = []
    for n in sorted(needs, key=lambda n: (-n.weight, n.sid)):
        left = n.need
        for r in sorted((r for r in routes if r.destination_station_id == n.sid), key=lambda r: r.transit_ticks):
            if left < MIN_SHIPMENT * 0.5:
                break
            d = snap.depots[r.source_depot_id]
            reserve = 0.0 if n.severity == "CRITICAL" else cfg.depot_reserve_frac * d.capacity.get(n.fuel, 0.0)
            q = min(left, r.max_shipment, n.headroom, stock[(d.id, n.fuel)] - reserve, disp[d.id])
            q = (q // UNIT) * UNIT
            if q < MIN_SHIPMENT and not (n.severity == "CRITICAL" and q > 0):
                continue
            out.append((r.id, n.fuel, n.sid, q))
            left -= q
            stock[(d.id, n.fuel)] -= q
            disp[d.id] -= q
    return out, "RULES"
