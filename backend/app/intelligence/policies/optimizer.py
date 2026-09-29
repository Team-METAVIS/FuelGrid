"""OR-Tools CP-SAT constrained allocation. Deterministic (fixed seed, single worker).

Decision vars  x[route, fuel] in {0..max_shipment/100}  (units of 100 L)
Minimize       sum W(station,fuel) * shortfall  +  transit_cost * x  +  eps * x
Subject to     depot stock - reserve, depot dispatch capacity / tick, route max shipment,
               station headroom, only routes/stations/depots that are currently usable.
"""
from ortools.sat.python import cp_model

from app.intelligence.policies.common import MIN_SHIPMENT, UNIT, Need, dispatch_remaining, usable_routes
from app.state.store import Snapshot

FUEL_KEYS = ("DIESEL", "PETROL", "OCTANE")


class SolverFailure(Exception):
    pass


def solve(snap: Snapshot, needs: list[Need], cfg) -> tuple[list[tuple[str, str, str, float]], str]:
    """Returns ([(route_id, fuel, station_id, liters)], status)."""
    routes = {r.id: r for r in usable_routes(snap)}
    if not needs or not routes:
        return [], "NOOP"
    model = cp_model.CpModel()
    need_by = {(n.sid, n.fuel): n for n in needs}
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    for r in routes.values():
        for (sid, fuel), n in need_by.items():
            if r.destination_station_id != sid:
                continue
            ub = int(min(r.max_shipment, n.headroom) // UNIT)
            if ub > 0:
                x[(r.id, fuel)] = model.NewIntVar(0, ub, f"x_{r.id}_{fuel}")

    critical = {n.sid for n in needs if n.severity == "CRITICAL"}
    disp = dispatch_remaining(snap)
    for d in snap.depots.values():
        for fuel in FUEL_KEYS:
            vs = [v for (rid, f), v in x.items() if f == fuel and routes[rid].source_depot_id == d.id]
            if vs:
                serves_critical = any(
                    routes[rid].destination_station_id in critical for (rid, f) in x if f == fuel and routes[rid].source_depot_id == d.id
                )
                reserve = 0.0 if serves_critical else cfg.depot_reserve_frac * d.capacity.get(fuel, 0.0)
                avail = max(0.0, d.inventory.get(fuel, 0.0) - reserve)
                model.Add(sum(vs) <= int(avail // UNIT))
        allv = [v for (rid, f), v in x.items() if routes[rid].source_depot_id == d.id]
        if allv:
            model.Add(sum(allv) <= int(disp.get(d.id, 0.0) // UNIT))

    obj = []
    for (sid, fuel), n in need_by.items():
        vs = [v for (rid, f), v in x.items() if f == fuel and routes[rid].destination_station_id == sid]
        if not vs:
            continue
        need_u = int(n.need // UNIT)
        short = model.NewIntVar(0, max(need_u, 0), f"short_{sid}_{fuel}")
        delivered = sum(vs)
        model.Add(delivered <= need_u + 5)  # never grossly over-deliver
        model.Add(short >= need_u - delivered)
        # convex (fairness) penalty: the deeper half of a shortfall costs double, so scarce fuel is spread to
        # equalise cover across stations instead of fully serving one and starving another
        deep = model.NewIntVar(0, max(need_u, 0), f"deep_{sid}_{fuel}")
        model.Add(deep >= short - need_u // 2)
        obj.append(n.weight * 10 * (short + deep))
    for (rid, _fuel), v in x.items():
        obj.append((routes[rid].transit_ticks + 1) * v)  # tie-breaker: prefer short routes, ship less
    model.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = cfg.optimizer_timeout_s
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = 0
    st = solver.Solve(model)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SolverFailure(solver.StatusName(st))
    out = []
    for (rid, fuel), v in x.items():
        q = solver.Value(v) * UNIT
        if q <= 0:
            continue
        sid = routes[rid].destination_station_id
        if q < MIN_SHIPMENT and need_by[(sid, fuel)].severity != "CRITICAL":
            continue
        out.append((rid, fuel, sid, float(q)))
    return out, solver.StatusName(st)
