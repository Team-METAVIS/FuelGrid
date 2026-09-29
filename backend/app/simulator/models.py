"""Strict pydantic models for simulator payloads. Invalid payloads are rejected (see client)."""
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Fuel(StrEnum):
    DIESEL = "DIESEL"
    PETROL = "PETROL"
    OCTANE = "OCTANE"


FUELS = [Fuel.DIESEL, Fuel.PETROL, Fuel.OCTANE]


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Instance(_M):
    id: int
    scenario_id: str
    seed: int
    sim_time: datetime
    tick: int = Field(ge=0)
    tick_minutes: int = Field(gt=0)
    status: str


class Depot(_M):
    id: str
    name: str
    region_id: str
    status: str
    dispatch_capacity_per_tick: float = Field(ge=0)
    capacity: dict[str, float]
    inventory: dict[str, float]


class Station(_M):
    id: str
    name: str
    region_id: str
    status: str
    demand_profile: str
    demand_multiplier: float = Field(ge=0)
    capacity: dict[str, float]
    inventory: dict[str, float]


class Route(_M):
    id: str
    source_depot_id: str
    destination_station_id: str
    transit_ticks: int = Field(ge=0)
    max_shipment: float = Field(gt=0)
    status: str


class SupplyArrival(_M):
    id: str
    depot_id: str
    fuel_type: str
    quantity: float
    planned_tick: int
    actual_tick: int | None = None
    status: str


class SimEvent(_M):
    id: int
    type: str
    start_tick: int
    end_tick: int
    status: str
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
    id: int
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
    fuel_type: Fuel
    quantity: float = Field(gt=0)
