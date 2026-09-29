"""Estimated arrival and transport-delay prediction.

Learns, from shipments and deliveries that already completed, how late each road and each depot's supply actually runs, and
applies that to what is still on its way. Works on any source: it only needs planned vs actual arrival ticks.

  * Roads: for every shipment that arrived, lateness = actual arrival - expected arrival (early is not credited). The mean
    lateness per road (smoothed towards zero when there are few samples) is added to the ETA of shipments still in transit.
  * Supply: for delivered supply, lateness = actual - planned tick; the same idea gives an estimated arrival for scheduled and
    delayed supply, plus a delay risk from the share of currently delayed deliveries.
  * A shipment on a road that is currently disrupted is flagged at risk."""
from app.state.store import Snapshot

PRIOR_STRENGTH = 3.0  # pseudo-samples of "on time": few observations must not swing the estimate


def route_lateness(snap: Snapshot) -> dict[str, dict]:
    raw: dict[str, list[int]] = {}
    for a in snap.allocations:
        if a.status == "ARRIVED" and a.actual_arrival_tick is not None and a.expected_arrival_tick is not None:
            raw.setdefault(a.route_id, []).append(max(0, a.actual_arrival_tick - a.expected_arrival_tick))
    out = {}
    for rid, xs in raw.items():
        n = len(xs)
        out[rid] = {"samples": n, "mean_late_ticks": sum(xs) / (n + PRIOR_STRENGTH), "share_late": sum(1 for x in xs if x > 0) / n}
    return out


def supply_lateness(snap: Snapshot) -> tuple[float, float]:
    """(mean lateness of delivered supply in ticks, share of open supply that is currently delayed)."""
    done = [max(0, a.actual_tick - a.planned_tick) for a in snap.arrivals if a.status == "ARRIVED" and a.actual_tick is not None]
    open_ = [a for a in snap.arrivals if a.status != "ARRIVED"]
    mean = sum(done) / (len(done) + PRIOR_STRENGTH) if done else 0.0
    risk = sum(1 for a in open_ if a.status == "DELAYED") / len(open_) if open_ else 0.0
    return mean, risk


def report(snap: Snapshot) -> dict:
    late = route_lateness(snap)
    mean_supply, delayed_share = supply_lateness(snap)
    ship = []
    for a in snap.in_transit():
        r = snap.routes.get(a.route_id)
        exp = a.expected_arrival_tick if a.expected_arrival_tick is not None else snap.tick + 1 + (r.transit_ticks if r else 2)
        add = round(late.get(a.route_id, {}).get("mean_late_ticks", 0.0))
        risk = "road currently disrupted" if r and r.status != "AVAILABLE" else ("usually late on this road" if add > 0 else None)
        ship.append({"id": a.id, "route_id": a.route_id, "fuel": a.fuel_type, "quantity": a.quantity, "expected_tick": exp, "estimated_tick": exp + add, "risk": risk})
    supply = []
    for a in snap.arrivals:
        if a.status == "ARRIVED":
            continue
        add = round(mean_supply)
        supply.append({"id": a.id, "depot_id": a.depot_id, "fuel": a.fuel_type, "quantity": a.quantity, "planned_tick": a.planned_tick,
                       "estimated_tick": a.planned_tick + add, "status": a.status, "delay_risk": round(delayed_share, 2) if a.status != "DELAYED" else 1.0})
    return {"routes": [{"route_id": k, **v} for k, v in sorted(late.items())], "shipments": ship, "supply": supply[:12],
            "supply_mean_late_ticks": round(mean_supply, 2), "supply_delayed_share": round(delayed_share, 2)}
