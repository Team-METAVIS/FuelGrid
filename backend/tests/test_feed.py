import time
from datetime import datetime, timedelta

import pytest

from app.adapters.feed import Ack, FeedSource, TelemetryIn, TopologyIn
from app.core.config import Settings
from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from app.domain import models as M
from app.domain.errors import AllocationRejected, SourceUnavailable
from app.state.store import StateStore
from app.state.sync import Synchronizer
from app.worldgen.driver import orders_for_world, push_tick
from app.worldgen.world import World

T0 = datetime(2026, 3, 2)


def topo(**kw) -> TopologyIn:
    return TopologyIn(
        tick_minutes=30,
        depots=[M.Depot(id="D", name="Depot", dispatch_capacity_per_tick=9000, capacity={"LPG": 50000, "DIESEL": 60000}, inventory={"LPG": 40000, "DIESEL": 50000})],
        stations=[M.Station(id="S1", name="One", capacity={"LPG": 10000, "DIESEL": 12000}, inventory={"LPG": 6000, "DIESEL": 8000}),
                  M.Station(id="S2", name="Two", capacity={"LPG": 8000, "DIESEL": 9000}, inventory={"LPG": 5000, "DIESEL": 6000})],
        routes=[M.Route(id="R1", source_depot_id="D", destination_station_id="S1", transit_ticks=2, max_shipment=5000),
                M.Route(id="R2", source_depot_id="D", destination_station_id="S2", transit_ticks=3, max_shipment=4000)], **kw)


def tel(tick, inv=None, dem=None, **kw) -> TelemetryIn:
    return TelemetryIn(time=T0 + timedelta(minutes=30 * tick), tick=tick, inventory=inv or [], demand=dem or [], **kw)


@pytest.fixture
def feed():
    f = FeedSource(Settings(database_url=None))
    f.set_topology(topo())
    return f


def test_telemetry_before_topology_is_refused_politely():
    f = FeedSource(Settings(database_url=None))
    out = f.ingest(tel(1))
    assert out["rejected"] == 1 and "topology" in out["error"]


def test_valid_bad_and_suspicious_readings_are_handled_differently(feed):
    out = feed.ingest(tel(1, inv=[
        {"entity_id": "S1", "fuel": "LPG", "liters": 5500},       # fine
        {"entity_id": "S1", "fuel": "DIESEL", "liters": -40},     # impossible
        {"entity_id": "S9", "fuel": "LPG", "liters": 100},        # unknown station
        {"entity_id": "S2", "fuel": "COAL", "liters": 100},       # product this station does not hold
        {"entity_id": "S2", "fuel": "LPG", "liters": 99999},      # over capacity: clamp and flag
    ], dem=[{"station_id": "S1", "fuel": "LPG", "liters": float("nan")}]))
    assert out["rejected"] == 4 and feed.stations_["S2"].inventory["LPG"] == 8000
    assert feed.stations_["S1"].inventory["LPG"] == 5500 and feed.stations_["S1"].inventory["DIESEL"] == 8000  # bad value ignored
    reasons = feed.quality.reasons
    assert reasons["invalid_value"] == 2 and reasons["unknown_entity"] == 1 and reasons["unknown_fuel"] == 1 and reasons["over_capacity"] == 1
    assert 0 < feed.quality.score < 1


def test_out_of_order_batches_are_rejected_and_do_not_move_the_clock(feed):
    feed.ingest(tel(5))
    out = feed.ingest(tel(3))
    assert "out of order" in out["error"] and feed.tick == 5


def test_a_silent_sensor_keeps_its_last_value_and_is_reported(feed):
    for k in range(1, 5):
        feed.ingest(tel(k, inv=[{"entity_id": e, "fuel": "LPG", "liters": 5000 - 10 * k} for e in ("S1", "S2")]))
    feed.ingest(tel(5, inv=[{"entity_id": "S1", "fuel": "LPG", "liters": 4900}]))  # S2 stops reporting
    feed.ingest(tel(6, inv=[{"entity_id": "S1", "fuel": "LPG", "liters": 4890}]))
    assert feed.stations_["S2"].inventory["LPG"] == 4960  # last known value carried forward
    assert feed.quality.stale_series.get("S2/LPG", 0) >= 2 and feed.quality.reasons["missing_readings"] >= 1


@pytest.mark.asyncio
async def test_orders_are_idempotent_validated_and_acknowledged(feed):
    feed.ingest(tel(1))
    req = M.AllocationRequest(idempotency_key="k1", source_depot_id="D", destination_station_id="S1", route_id="R1", fuel_type="LPG", quantity=3000)
    a = await feed.create_allocation(req)
    assert a.status == "PENDING" and a.expected_arrival_tick == 1 + 1 + 2
    assert (await feed.create_allocation(req)).id == a.id  # safe retry
    with pytest.raises(AllocationRejected) as e:
        await feed.create_allocation(req.model_copy(update={"quantity": 3500}))
    assert e.value.code == "IDEMPOTENCY_KEY_MISMATCH"
    with pytest.raises(AllocationRejected) as e:
        await feed.create_allocation(req.model_copy(update={"idempotency_key": "k2", "route_id": "R2"}))
    assert e.value.code == "ROUTE_MISMATCH"
    assert feed.ack(Ack(order_id=a.id, status="IN_TRANSIT", departure_tick=2, arrival_tick=4))
    assert feed.orders[a.id].status == "IN_TRANSIT" and not feed.pending_orders("PENDING")
    assert not feed.ack(Ack(order_id=999, status="ARRIVED"))


def test_a_feed_that_goes_quiet_is_reported_stale(feed):
    feed.ingest(tel(1))
    assert not feed.last_stale
    feed.received_at = time.time() - feed.s.feed_stale_after_s - 5
    assert feed.last_stale


def test_the_network_can_change_while_running(feed):
    bigger = topo()
    bigger.stations.append(M.Station(id="S3", name="New", capacity={"LPG": 7000, "DIESEL": 7000}, inventory={"LPG": 3000, "DIESEL": 3000}))
    bigger.routes.append(M.Route(id="R3", source_depot_id="D", destination_station_id="S3", transit_ticks=1, max_shipment=3000))
    assert feed.set_topology(bigger)["stations"] == 3
    smaller = topo()
    smaller.stations, smaller.routes = smaller.stations[:1], smaller.routes[:1]
    feed.set_topology(smaller)
    assert list(feed.stations_) == ["S1"] and list(feed.routes_) == ["R1"]


@pytest.mark.asyncio
async def test_source_with_no_data_is_unavailable_not_a_crash():
    f = FeedSource(Settings(database_url=None))
    with pytest.raises(SourceUnavailable):
        await f.instance()


@pytest.mark.asyncio
async def test_platform_runs_end_to_end_on_an_unseen_network():
    """Different topology, a product the simulator never had (LPG), 30-minute ticks: the core must not care."""
    cfg = Settings(database_url=None, forecaster="moving_avg")
    feed, store = FeedSource(cfg), StateStore()
    sync = Synchronizer(feed, store)
    eng = DecisionEngine(cfg, store, feed, Repo(None), "t")
    eng.refresh = sync.refresh
    world = World(seed=3)
    feed.set_topology(TopologyIn(**world.topology()))
    for _ in range(120):
        push_tick(feed, world, [])
    world.legacy = False
    executed = 0
    for _ in range(60):
        push_tick(feed, world, orders_for_world(feed))
        snap = await sync.refresh()
        assert snap is not None
        plan = await eng.cycle(snap)
        for d in [d for d in eng.decisions.values() if d.status == "PROPOSED"]:
            await eng.approve(d.id)
            executed += d.status == "EXECUTED"
    assert "LPG" in store.snapshot.fuels and len(store.snapshot.stations) == 8
    assert executed > 0 and plan is not None
    assert world.service_level > 0.85, f"closed loop should keep service healthy, got {world.service_level:.3f}"
