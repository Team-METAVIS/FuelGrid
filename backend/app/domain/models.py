"""Canonical domain model.

Every data source (the organizer's simulator, a live telemetry feed, a CSV replay, ...) is translated into these types by
an adapter. Nothing above the adapters knows or cares where the data came from. Fuels are plain strings, so a network
with different products works unchanged."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Instance(_M):
    """The clock and identity of the world being observed."""
    id: int = 1
    scenario_id: str = "live"
    scenario_version: str | None = None
    seed: int | None = None
    sim_time: datetime  # wall-clock time of the observation for live data
    tick: int = Field(ge=0)
    tick_minutes: int = Field(gt=0)
    status: str = "RUNNING"


class Region(_M):
    id: str
    name: str
    demand_factor: float = Field(default=1.0, gt=0)


class Depot(_M):
    id: str
    name: str
    region_id: str = ""
    status: str = "OPEN"
    dispatch_capacity_per_tick: float = Field(ge=0)
    capacity: dict[str, float]
    inventory: dict[str, float]


class Station(_M):
    id: str
    name: str
    region_id: str = ""
    status: str = "OPEN"
    demand_profile: str = "unknown"  # only meaningful to the simulator; learned models never read it
    demand_multiplier: float = Field(default=1.0, ge=0)
    capacity: dict[str, float]
    inventory: dict[str, float]


class Route(_M):
    id: str
    source_depot_id: str
    destination_station_id: str
    transit_ticks: int = Field(ge=0)
    max_shipment: float = Field(gt=0)
    status: str = "AVAILABLE"


class SupplyArrival(_M):
    id: str
    depot_id: str
    fuel_type: str
    quantity: float
    planned_tick: int
    actual_tick: int | None = None
    status: str = "SCHEDULED"


class SimEvent(_M):
    id: int
    type: str
    start_tick: int
    end_tick: int
    status: str = "ACTIVE"
    parameters: dict = {}


class Allocation(_M):
    id: int
    idempotency_key: str
    source_depot_id: str
    destination_station_id: str
    route_id: str
    fuel_type: str
    quantity: float
    created_tick: int
    departure_tick: int | None = None
    expected_arrival_tick: int | None = None
    actual_arrival_tick: int | None = None
    status: str
    failure_reason: str | None = None


class DemandRow(_M):
    id: int = 0
    station_id: str
    fuel_type: str
    tick: int
    sim_time: datetime
    demand_liters: float
    served_liters: float
    unmet_liters: float


class Metrics(_M):
    served_demand_liters: float
    unmet_demand_liters: float
    service_level: float
    allocation_liters: float
    allocation_failures: int


class AllocationRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=150)
    source_depot_id: str
    destination_station_id: str
    route_id: str
    fuel_type: str = Field(min_length=1, max_length=40)
    quantity: float = Field(gt=0)
