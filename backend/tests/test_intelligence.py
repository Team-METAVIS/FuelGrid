from app.intelligence import planner
from app.intelligence.forecast import seasonal_forecast
from app.intelligence.policies.common import usable_routes
from app.intelligence.projection import simulate, stockout_prob
from tests.conftest import make_snapshot

LOW = {"station-mirpur": (300, 9000, 5000)}  # mirpur diesel nearly out


def test_forecast_uses_prior_without_history(store, cfg):
    snap = make_snapshot()
    f = seasonal_forecast(store, snap, "station-mirpur", "DIESEL", 16)
    assert len(f.per_tick) == 16 and all(x > 0 for x in f.per_tick)
    assert f.confidence < 0.5  # no history => honest low confidence


def test_projection_detects_stockout():
    first, unmet, _ = simulate(1000, 10000, [400] * 10, {}, 0)
    assert first == 3 and unmet > 0
    assert simulate(1000, 10000, [400] * 10, {2: 5000}, 0)[0] is None


def test_stockout_prob_monotonic():
    assert stockout_prob(500, [400] * 5, 0, 0.1) > stockout_prob(5000, [400] * 5, 0, 0.1)


def test_optimizer_recommends_for_low_station(store, cfg):
    snap = make_snapshot(hour=8, station_inv=LOW)
    p = planner.plan(store, snap, cfg, policy="optimizer")
    recs = [r for r in p.recommendations if r.station_id == "station-mirpur" and r.fuel == "DIESEL"]
    assert recs, "must resupply the nearly-empty station"
    assert p.solver_status in ("OPTIMAL", "FEASIBLE") and not p.fallback_used
    for r in recs:
        route = snap.routes[r.route_id]
        assert r.quantity <= route.max_shipment
        assert r.risk_after <= r.risk_before
        assert r.alternatives is not None


def test_optimizer_respects_constraints(store, cfg):
    snap = make_snapshot(station_inv={s: (500, 500, 500) for s in ("station-mirpur", "station-tongi", "station-karnaphuli", "station-coxsbazar")})
    p = planner.plan(store, snap, cfg, policy="optimizer")
    per_depot: dict[str, float] = {}
    for r in p.recommendations:
        per_depot[r.depot_id] = per_depot.get(r.depot_id, 0) + r.quantity
        assert r.quantity <= snap.routes[r.route_id].max_shipment
    for d, q in per_depot.items():
        assert q <= snap.depots[d].dispatch_capacity_per_tick  # dispatch capacity per tick


def test_disrupted_route_is_avoided(store, cfg):
    snap = make_snapshot(hour=8, station_inv=LOW, route_status={"route-gazipur-mirpur": "DISRUPTED"})
    assert "route-gazipur-mirpur" not in {r.id for r in usable_routes(snap)}
    p = planner.plan(store, snap, cfg, policy="optimizer")
    for r in p.recommendations:
        assert r.route_id != "route-gazipur-mirpur"
    # should re-route from the other depot (alternative allocation under regional disruption)
    assert any(r.route_id == "route-patiya-mirpur" for r in p.recommendations if r.station_id == "station-mirpur")


def test_solver_failure_falls_back_to_rules(store, cfg, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("solver crashed")

    monkeypatch.setitem(planner.POLICIES, "optimizer", boom)
    p = planner.plan(store, make_snapshot(hour=8, station_inv=LOW), cfg, policy="optimizer")
    assert p.fallback_used and p.policy == "rules" and p.recommendations


def test_forecaster_failure_falls_back(store, cfg, monkeypatch):
    def boom(*a, **k):
        raise ValueError("model unavailable")

    monkeypatch.setitem(planner.FORECASTERS, "seasonal", boom)
    p = planner.plan(store, make_snapshot(hour=8, station_inv=LOW), cfg)
    assert p.forecast_model == "moving-average-v1" and p.notes


def test_determinism(store, cfg):
    snap = make_snapshot(hour=8, station_inv=LOW)
    a = [(r.route_id, r.fuel, r.quantity) for r in planner.plan(store, snap, cfg).recommendations]
    b = [(r.route_id, r.fuel, r.quantity) for r in planner.plan(store, snap, cfg).recommendations]
    assert a == b
