import pytest
from fastapi.testclient import TestClient

from app.adapters.feed import FeedSource
from app.core.config import Settings
from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from app.domain import models as M
from app.domain.errors import AllocationRejected
from app.intelligence import eta
from app.intelligence.bottlenecks import analyse
from app.intelligence.policies.common import Need
from app.intelligence.projection import incoming_by_tick
from app.main import create_app
from tests.conftest import make_snapshot
from tests.test_engine import LOW, FakeClient
from tests.test_feed import tel, topo


def alloc(i, route, status, exp, actual=None, dep="depot-gazipur", st="station-mirpur", q=3000.0):
    return M.Allocation(id=i, idempotency_key=f"k{i}", source_depot_id=dep, destination_station_id=st, route_id=route, fuel_type="DIESEL",
                        quantity=q, created_tick=0, expected_arrival_tick=exp, actual_arrival_tick=actual, status=status)


def test_late_roads_are_learned_and_applied_to_estimated_arrival():
    history = [alloc(i, "route-gazipur-mirpur", "ARRIVED", exp=10, actual=13) for i in range(1, 9)]  # this road runs 3 ticks late
    snap = make_snapshot(tick=20, allocations=history + [alloc(99, "route-gazipur-mirpur", "IN_TRANSIT", exp=25)])
    late = eta.route_lateness(snap)["route-gazipur-mirpur"]
    assert late["samples"] == 8 and 2.0 < late["mean_late_ticks"] < 3.0 and late["share_late"] == 1.0
    ship = eta.report(snap)["shipments"][0]
    assert ship["expected_tick"] == 25 and ship["estimated_tick"] > 25 and ship["risk"] == "usually late on this road"
    assert incoming_by_tick(snap, "station-mirpur", "DIESEL")[25 + snap.late_by_route()["route-gazipur-mirpur"]] == 3000.0, "projection must use the learned delay"


def test_few_samples_do_not_swing_the_estimate_and_on_time_roads_stay_on_time():
    one = make_snapshot(allocations=[alloc(1, "route-gazipur-mirpur", "ARRIVED", exp=10, actual=14)])
    assert eta.route_lateness(one)["route-gazipur-mirpur"]["mean_late_ticks"] < 1.5, "one late shipment is not a trend"
    ok = make_snapshot(tick=5, allocations=[alloc(1, "route-gazipur-mirpur", "ARRIVED", exp=3, actual=3), alloc(2, "route-gazipur-mirpur", "IN_TRANSIT", exp=9)])
    assert eta.report(ok)["shipments"][0]["estimated_tick"] == 9


def test_shipment_on_a_disrupted_road_is_flagged_at_risk():
    snap = make_snapshot(tick=5, route_status={"route-gazipur-mirpur": "DISRUPTED"}, allocations=[alloc(1, "route-gazipur-mirpur", "IN_TRANSIT", exp=9)])
    assert eta.report(snap)["shipments"][0]["risk"] == "road currently disrupted"


def test_supply_delay_risk_and_estimated_arrival():
    snap = make_snapshot(tick=10)
    snap.arrivals = [M.SupplyArrival(id="a", depot_id="depot-gazipur", fuel_type="DIESEL", quantity=1, planned_tick=8, actual_tick=11, status="ARRIVED"),
                     M.SupplyArrival(id="b", depot_id="depot-gazipur", fuel_type="DIESEL", quantity=5000, planned_tick=20, status="SCHEDULED"),
                     M.SupplyArrival(id="c", depot_id="depot-patiya", fuel_type="PETROL", quantity=5000, planned_tick=30, status="DELAYED")]
    rep = eta.report(snap)
    by = {s["id"]: s for s in rep["supply"]}
    assert by["c"]["delay_risk"] == 1.0 and by["b"]["delay_risk"] == 0.5 and by["b"]["estimated_tick"] >= 20 and rep["supply_delayed_share"] == 0.5


def test_bottleneck_analysis_names_the_binding_constraint():
    snap = make_snapshot(tick=1)
    # gazipur may send 12,000 per tick: a plan using all of it must be reported as a dispatch bottleneck
    lines = [("route-gazipur-mirpur", "DIESEL", "station-mirpur", 7000.0), ("route-gazipur-tongi", "DIESEL", "station-tongi", 5000.0)]
    items = analyse(snap, Settings(database_url=None), [], lines)
    assert any(i["kind"] == "dispatch_capacity" and i["where"] == "depot-gazipur" and i["utilization"] >= 0.97 for i in items)
    assert any(i["kind"] == "road_maximum" and i["where"] == "route-gazipur-mirpur" for i in items)
    need = Need("station-karnaphuli", "DIESEL", need=9000.0, headroom=9000.0, weight=30, eta_min=3, severity="CRITICAL")
    closed = make_snapshot(route_status={"route-patiya-karnaphuli": "DISRUPTED", "route-gazipur-karnaphuli": "DISRUPTED"})
    gap = analyse(closed, Settings(database_url=None), [need], [])
    assert gap[0]["kind"] == "unfilled_need" and "closed" in gap[0]["detail"] and gap[0]["severity"] == "CRITICAL"


@pytest.mark.asyncio
async def test_a_tank_falling_faster_than_recorded_demand_is_an_incident(cfg, store):
    store.snapshot = make_snapshot(tick=10, hour=8, station_inv={"station-mirpur": (9000, 9000, 5000)})
    for t in range(1, 30):
        store.demand[("station-mirpur", "DIESEL")][t] = (90.0, 90.0, 0.0, store.snapshot.instance.sim_time)
    eng = DecisionEngine(cfg, store, FakeClient(), Repo(None), "t")
    await eng.cycle()
    assert not any(i["type"] == "abnormal_inventory_drop" for i in eng.incidents.values())
    store.snapshot = make_snapshot(tick=11, hour=8, station_inv={"station-mirpur": (4000, 9000, 5000)})  # -5,000 L, demand 90 L
    await eng.cycle()
    inc = [i for i in eng.incidents.values() if i["type"] == "abnormal_inventory_drop"]
    assert inc and "5,000" in inc[0]["message"]
    store.snapshot = make_snapshot(tick=12, hour=8, station_inv={"station-mirpur": (3910, 9000, 5000)})  # normal consumption again
    await eng.cycle()
    assert not any(i["type"] == "abnormal_inventory_drop" for i in eng.incidents.values()), "clears once behaviour is normal"


class CancellingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.cancelled = []
        self.refuse = False

    async def cancel_allocation(self, aid):
        if self.refuse:
            raise AllocationRejected(409, "CANNOT_CANCEL", "already departed")
        self.cancelled.append(aid)
        return {"id": aid, "status": "CANCELLED"}


@pytest.mark.asyncio
async def test_cancel_withdraws_a_sent_shipment_and_refunds_stock(cfg, store):
    store.snapshot = make_snapshot(hour=8, station_inv=LOW)
    eng = DecisionEngine(cfg, store, CancellingClient(), Repo(None), "t")
    await eng.cycle()
    did = next(d.id for d in eng.decisions.values() if d.status == "PROPOSED")
    with pytest.raises(ValueError):
        await eng.cancel(did)  # not sent yet
    await eng.approve(did)
    d = eng.decisions[did]
    stock = store.snapshot.depots[d.rec.depot_id].inventory[d.rec.fuel]
    await eng.cancel(did)
    assert d.status == "CANCELLED" and eng.client.cancelled == [d.sim_allocation_id]
    assert store.snapshot.depots[d.rec.depot_id].inventory[d.rec.fuel] == stock + d.rec.quantity
    assert any("cancelled" in a["message"] for a in eng.repo.mem_audit)


@pytest.mark.asyncio
async def test_cancel_refused_by_the_source_is_reported_not_hidden(cfg, store):
    store.snapshot = make_snapshot(hour=8, station_inv=LOW)
    client = CancellingClient()
    eng = DecisionEngine(cfg, store, client, Repo(None), "t")
    await eng.cycle()
    did = next(d.id for d in eng.decisions.values() if d.status == "PROPOSED")
    await eng.approve(did)
    client.refuse = True
    with pytest.raises(ValueError, match="CANNOT_CANCEL"):
        await eng.cancel(did)
    assert eng.decisions[did].status == "EXECUTED", "a refused cancel must not change the decision"


@pytest.mark.asyncio
async def test_feed_source_cancels_only_pending_orders():
    feed = FeedSource(Settings(database_url=None))
    feed.set_topology(topo())
    feed.ingest(tel(1))
    o = await feed.create_allocation(M.AllocationRequest(idempotency_key="c1", source_depot_id="D", destination_station_id="S1", route_id="R1", fuel_type="LPG", quantity=2000))
    assert (await feed.cancel_allocation(o.id))["status"] == "CANCELLED"
    with pytest.raises(AllocationRejected) as e:
        await feed.cancel_allocation(o.id)
    assert e.value.code == "CANNOT_CANCEL"


def test_state_exposes_regions_eta_bottlenecks_and_cancel_endpoint():
    app = create_app(Settings(database_url=None, forecaster="seasonal"), start_background=False)
    with TestClient(app) as c:
        rt = app.state.rt
        rt.engine.client = CancellingClient()
        rt.store.snapshot = make_snapshot(hour=8, station_inv=LOW)
        c.portal.call(rt.engine.cycle)
        s = c.get("/api/state").json()
        reg = {r["id"]: r for r in s["regions"]}
        assert set(reg) == {"region-dhaka", "region-chattogram"} and reg["region-dhaka"]["stations"] == 2
        assert reg["region-dhaka"]["forecast_8h"] > 0 and reg["region-dhaka"]["cover_hours"] is not None and "DIESEL" in reg["region-dhaka"]["fuels"]
        assert "shipments" in s["eta"] and isinstance(s["plan"]["bottlenecks"], list)
        rec = s["recommendations"][0]
        assert c.post(f"/api/decisions/{rec['id']}/cancel").status_code == 409  # not sent yet
        c.post(f"/api/decisions/{rec['id']}/approve")
        assert c.post(f"/api/decisions/{rec['id']}/cancel").json()["status"] == "CANCELLED"
        assert c.post("/api/decisions/99999/cancel").status_code == 404
