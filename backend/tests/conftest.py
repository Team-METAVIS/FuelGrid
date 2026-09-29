"""Builds a synthetic Snapshot mirroring the simulator's fixed world (guide section 8) for offline tests."""
from datetime import datetime

import pytest

from app.core.config import Settings
from app.simulator import models as M
from app.state.store import Snapshot, StateStore

FUEL = ("DIESEL", "PETROL", "OCTANE")
DEPOTS = {
    "depot-gazipur": ("region-dhaka", 12000, (90000, 70000, 45000), (60000, 45000, 26000)),
    "depot-patiya": ("region-chattogram", 11000, (85000, 65000, 40000), (55000, 42000, 24000)),
}
STATIONS = {
    "station-mirpur": ("region-dhaka", "urban_high", (15000, 14000, 9000), (9000, 9000, 5000)),
    "station-tongi": ("region-dhaka", "industrial", (18000, 9000, 6000), (11000, 6000, 3500)),
    "station-karnaphuli": ("region-chattogram", "highway", (14000, 15000, 9000), (8500, 9500, 5200)),
    "station-coxsbazar": ("region-chattogram", "regional", (12000, 12000, 7000), (7500, 7500, 4200)),
}
ROUTES = [
    ("route-gazipur-mirpur", "depot-gazipur", "station-mirpur", 2, 7000),
    ("route-gazipur-tongi", "depot-gazipur", "station-tongi", 2, 6500),
    ("route-patiya-karnaphuli", "depot-patiya", "station-karnaphuli", 2, 7000),
    ("route-patiya-coxsbazar", "depot-patiya", "station-coxsbazar", 3, 6000),
    ("route-gazipur-karnaphuli", "depot-gazipur", "station-karnaphuli", 4, 5000),
    ("route-patiya-mirpur", "depot-patiya", "station-mirpur", 4, 5000),
]


def make_snapshot(tick=0, station_inv=None, route_status=None, allocations=None, hour=0) -> Snapshot:
    depots = {k: M.Depot(id=k, name=k, region_id=r, status="OPEN", dispatch_capacity_per_tick=dc,
                         capacity=dict(zip(FUEL, cap, strict=True)), inventory=dict(zip(FUEL, inv, strict=True)))
              for k, (r, dc, cap, inv) in DEPOTS.items()}
    stations = {}
    for k, (r, prof, cap, inv) in STATIONS.items():
        inv = (station_inv or {}).get(k, inv)
        stations[k] = M.Station(id=k, name=k, region_id=r, status="OPEN", demand_profile=prof, demand_multiplier=1.0,
                                capacity=dict(zip(FUEL, cap, strict=True)), inventory=dict(zip(FUEL, inv, strict=True)))
    routes = {i: M.Route(id=i, source_depot_id=d, destination_station_id=s, transit_ticks=t, max_shipment=mx,
                         status=(route_status or {}).get(i, "AVAILABLE")) for i, d, s, t, mx in ROUTES}
    inst = M.Instance(id=1, scenario_id="t", seed=1, sim_time=datetime(2026, 1, 1, hour), tick=tick, tick_minutes=15, status="PAUSED")
    return Snapshot(inst, depots, stations, routes, [], [], allocations or [],
                    M.Metrics(served_demand_liters=0, unmet_demand_liters=0, service_level=1, allocation_liters=0, allocation_failures=0))


@pytest.fixture
def cfg():
    return Settings(database_url=None)


@pytest.fixture
def store():
    return StateStore()
