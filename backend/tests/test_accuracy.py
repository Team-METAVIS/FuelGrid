from app.domain import models as M
from app.intelligence import planner
from app.intelligence.forecast import event_multiplier, seasonal_forecast, seasonal_v1_forecast
from app.intelligence.policies.common import precheck, usable_routes
from tests.conftest import disruption, make_snapshot, spike

LOW = {"station-mirpur": (300, 9000, 5000)}


def test_event_multiplier_follows_announced_spike_window():
    snap = make_snapshot(tick=10, events=[spike(12, 20, 2.5)])
    st = snap.stations["station-mirpur"]
    assert event_multiplier(snap, st, 11) == 1.0
    assert event_multiplier(snap, st, 12) == 2.5 and event_multiplier(snap, st, 19) == 2.5
    assert event_multiplier(snap, st, 20) == 1.0  # the end of the spike is anticipated too
    assert event_multiplier(snap, snap.stations["station-karnaphuli"], 15) == 1.0  # other region untouched


def test_v2_anticipates_a_scheduled_spike_v1_cannot(store, cfg):
    snap = make_snapshot(tick=10, hour=8, events=[spike(14, 30, 2.0, status="SCHEDULED")])
    v2 = seasonal_forecast(store, snap, "station-mirpur", "DIESEL", 16)
    v1 = seasonal_v1_forecast(store, snap, "station-mirpur", "DIESEL", 16)
    assert v2.per_tick[6] > 1.8 * v2.per_tick[0]  # jumps at tick 14 (index 3) already in the forecast
    assert abs(v1.per_tick[6] - v1.per_tick[0]) < 0.6 * v1.per_tick[0]  # v1 sees no such thing


def test_announced_disruption_removes_route_before_it_happens():
    snap = make_snapshot(tick=5, events=[disruption(6, 30, ["route-gazipur-mirpur"])])  # departs at tick 6
    assert "route-gazipur-mirpur" not in {r.id for r in usable_routes(snap)}
    later = make_snapshot(tick=5, events=[disruption(40, 50, ["route-gazipur-mirpur"])])
    assert "route-gazipur-mirpur" in {r.id for r in usable_routes(later)}


def test_planner_reroutes_around_announced_disruption(store, cfg):
    snap = make_snapshot(hour=8, station_inv=LOW, events=[disruption(1, 40, ["route-gazipur-mirpur"])])
    p = planner.plan(store, snap, cfg)
    assert all(r.route_id != "route-gazipur-mirpur" for r in p.recommendations)
    assert any(r.route_id == "route-patiya-mirpur" for r in p.recommendations if r.station_id == "station-mirpur")


def test_precheck_mirrors_simulator_rules():
    snap = make_snapshot()
    ok = ("depot-gazipur", "station-mirpur", "route-gazipur-mirpur", "DIESEL")
    assert precheck(snap, *ok, 3000) is None
    assert precheck(snap, *ok, 8000)[0] == "ROUTE_CAPACITY_EXCEEDED"
    assert precheck(snap, "depot-patiya", "station-mirpur", "route-gazipur-mirpur", "DIESEL", 100)[0] == "ROUTE_MISMATCH"
    assert precheck(snap, "depot-gazipur", "station-mirpur", "route-nope", "DIESEL", 100)[0] == "NOT_FOUND"
    assert precheck(snap, *ok, 7000)[0] == "DESTINATION_CAPACITY_EXCEEDED"  # 9000 + 7000 > 15000
    snap.depots["depot-gazipur"].inventory["DIESEL"] = 500
    assert precheck(snap, *ok, 1000)[0] == "INSUFFICIENT_INVENTORY"
    disrupted = make_snapshot(route_status={"route-gazipur-mirpur": "DISRUPTED"})
    assert precheck(disrupted, *ok, 100)[0] == "ROUTE_DISRUPTED"
    pending = make_snapshot(allocations=[M.Allocation(id=1, idempotency_key="k", source_depot_id="depot-gazipur", destination_station_id="station-tongi",
                                                       route_id="route-gazipur-tongi", fuel_type="PETROL", quantity=11000, created_tick=0, status="PENDING")])
    assert precheck(pending, *ok, 3000)[0] == "DISPATCH_CAPACITY_EXCEEDED"  # 11000 + 3000 > 12000
