"""Generic live-feed adapter.

Any real system (station sensors, an ERP, a SCADA gateway, a data pipeline) can drive FuelGrid without being a simulator:

    POST /api/feed/topology    describe depots, stations, routes, capacities (re-send any time: the network is dynamic)
    POST /api/feed/telemetry   push inventory readings, demand, status changes, supply arrivals, announced events
    GET  /api/feed/orders      pull dispatch orders that operators approved (or an optional webhook receives them)
    POST /api/feed/orders/{id}/ack   report an order as in transit / arrived / failed

The adapter validates everything, tracks data quality, carries forward the last known reading when a sensor drops out and
reports the feed as stale when it goes silent. It implements the same contract as the simulator adapter, so the rest of the
system cannot tell the difference."""
import asyncio
import math
import statistics
import time
from collections import deque
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import models as M
from app.domain.errors import AllocationRejected, SourceUnavailable
from app.domain.quality import Quality

log = get_logger("feed")


# ------------------------------------------------------------------------------------------------ wire formats
class TopologyIn(BaseModel):
    tick_minutes: int = Field(default=15, gt=0, le=1440)
    regions: list[M.Region] = []
    depots: list[M.Depot] = []
    stations: list[M.Station] = []
    routes: list[M.Route] = []


class Reading(BaseModel):
    entity_id: str  # depot or station id
    fuel: str
    liters: float


class DemandReading(BaseModel):
    station_id: str
    fuel: str
    liters: float  # demand during the interval that just ended
    served: float | None = None
    unmet: float | None = None


class StatusChange(BaseModel):
    entity_id: str  # depot, station or route id
    status: str


class SupplyIn(BaseModel):
    id: str
    depot_id: str
    fuel: str
    quantity: float
    planned_tick: int
    status: str = "SCHEDULED"


class EventIn(BaseModel):
    id: int | None = None
    type: str
    start_tick: int
    end_tick: int
    status: str = "ACTIVE"
    parameters: dict = {}


class Ack(BaseModel):
    order_id: int
    status: str  # IN_TRANSIT | ARRIVED | FAILED | CANCELLED
    departure_tick: int | None = None
    arrival_tick: int | None = None
    reason: str | None = None


class TelemetryIn(BaseModel):
    time: datetime | None = None
    tick: int | None = None
    inventory: list[Reading] = []
    demand: list[DemandReading] = []
    status: list[StatusChange] = []
    supply: list[SupplyIn] = []
    events: list[EventIn] = []
    acks: list[Ack] = []


def _finite(x: float) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


class FeedSource:
    kind = "feed"
    label = "Live telemetry feed"
    supports_admin = False
    supports_stream = False

    def __init__(self, cfg: Settings):
        self.s = cfg
        self.last_error: str | None = None
        self._stale_flag = False
        self.on_change = None  # set by the runtime: wakes the synchronizer when data arrives
        self.quality = Quality()
        self.tick_minutes = 15
        self.tick = 0
        self.time: datetime | None = None
        self.received_at: float | None = None
        self.regions_: dict[str, M.Region] = {}
        self.depots_: dict[str, M.Depot] = {}
        self.stations_: dict[str, M.Station] = {}
        self.routes_: dict[str, M.Route] = {}
        self.arrivals_: dict[str, M.SupplyArrival] = {}
        self.events_: dict[int, M.SimEvent] = {}
        self.orders: dict[int, M.Allocation] = {}
        self._by_key: dict[str, int] = {}
        self._next_order = 1
        self._next_event = 1
        self.rows: deque[M.DemandRow] = deque(maxlen=400_000)
        self._row_id = 0
        self._series_tail: dict[tuple[str, str], deque[float]] = {}
        self._last_read_tick: dict[str, int] = {}  # "entity/fuel" -> tick of last real reading
        self.served_total = 0.0
        self.unmet_total = 0.0
        self.topology_version = 0
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ contract properties
    @property
    def breaker_open(self) -> bool:
        return False

    @property
    def last_stale(self) -> bool:
        """True when the feed has gone silent for longer than the configured limit."""
        return self._silence_s() is not None and self._silence_s() > self.s.feed_stale_after_s

    def _silence_s(self) -> float | None:
        return None if self.received_at is None else time.time() - self.received_at

    async def aclose(self) -> None:
        for t in list(self._tasks):
            t.cancel()

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change()

    # ------------------------------------------------------------------ topology (dynamic: send it again whenever it changes)
    def set_topology(self, t: TopologyIn) -> dict:
        added = {"new_depots": 0, "new_stations": 0, "new_routes": 0}
        self.tick_minutes = t.tick_minutes
        for r in t.regions:
            self.regions_[r.id] = r
        for d in t.depots:
            added["new_depots"] += d.id not in self.depots_
            old = self.depots_.get(d.id)
            self.depots_[d.id] = d if old is None or d.inventory else d.model_copy(update={"inventory": old.inventory})
        for s in t.stations:
            added["new_stations"] += s.id not in self.stations_
            old = self.stations_.get(s.id)
            self.stations_[s.id] = s if old is None or s.inventory else s.model_copy(update={"inventory": old.inventory})
        for r in t.routes:
            added["new_routes"] += r.id not in self.routes_
            self.routes_[r.id] = r
        # entities that are no longer described disappear (a closed depot, a decommissioned station)
        if t.depots:
            self.depots_ = {k: v for k, v in self.depots_.items() if k in {d.id for d in t.depots}}
        if t.stations:
            self.stations_ = {k: v for k, v in self.stations_.items() if k in {s.id for s in t.stations}}
        if t.routes or t.stations or t.depots:
            self.routes_ = {k: v for k, v in self.routes_.items()
                            if v.source_depot_id in self.depots_ and v.destination_station_id in self.stations_ and (not t.routes or k in {r.id for r in t.routes})}
        self.topology_version += 1
        self.received_at = time.time()
        self._notify()
        log.info("feed_topology", **added, depots=len(self.depots_), stations=len(self.stations_), routes=len(self.routes_))
        return {"ok": True, **added, "depots": len(self.depots_), "stations": len(self.stations_), "routes": len(self.routes_), "version": self.topology_version}

    # ------------------------------------------------------------------ telemetry
    def ingest(self, b: TelemetryIn) -> dict:
        q = self.quality
        q.batches += 1
        if not self.stations_ and not self.depots_:
            q.reject("no_topology", "telemetry received before any topology", self.tick)
            return {"accepted": 0, "rejected": 1, "error": "send /api/feed/topology first"}
        # --- clock
        if b.time is not None:
            t = b.time.astimezone(UTC).replace(tzinfo=None) if b.time.tzinfo else b.time
            if self.time is not None and t < self.time - timedelta(seconds=1):
                q.reject("out_of_order", f"batch time {t.isoformat()} is before {self.time.isoformat()}", self.tick)
                return {"accepted": 0, "rejected": 1, "error": "out of order batch"}
        else:
            t = (self.time or datetime.now(UTC).replace(tzinfo=None)) + timedelta(minutes=self.tick_minutes)
        if b.tick is not None:
            new_tick = b.tick
        elif self.time is not None and t > self.time:
            new_tick = self.tick + max(1, round((t - self.time).total_seconds() / 60 / self.tick_minutes))
        else:
            new_tick = self.tick
        self.tick, self.time = max(new_tick, 0), t
        acc0, rej0 = q.accepted, q.rejected

        # --- status changes
        for sc in b.status:
            target = self.depots_.get(sc.entity_id) or self.stations_.get(sc.entity_id) or self.routes_.get(sc.entity_id)
            if target is None:
                q.reject("unknown_entity", f"status for {sc.entity_id}", self.tick)
                continue
            target.status = sc.status
            q.ok()

        # --- inventory readings
        seen: set[str] = set()
        for r in b.inventory:
            owner = self.stations_.get(r.entity_id) or self.depots_.get(r.entity_id)
            if owner is None:
                q.reject("unknown_entity", f"inventory for {r.entity_id}", self.tick)
                continue
            if not _finite(r.liters) or r.liters < 0:
                q.reject("invalid_value", f"{r.entity_id}/{r.fuel} = {r.liters}", self.tick)
                continue
            cap = owner.capacity.get(r.fuel)
            if cap is None:
                q.reject("unknown_fuel", f"{r.entity_id} does not hold {r.fuel}", self.tick)
                continue
            liters = r.liters
            if liters > cap * 1.05:
                q.flag("over_capacity", f"{r.entity_id}/{r.fuel} {liters:.0f} L exceeds capacity {cap:.0f} L; clamped", self.tick)
                liters = cap
            else:
                q.ok()
            prev = owner.inventory.get(r.fuel)
            if prev is not None and abs(liters - prev) > 0.6 * cap and self._last_read_tick.get(f"{r.entity_id}/{r.fuel}") is not None:
                q.flag("large_jump", f"{r.entity_id}/{r.fuel} moved {liters - prev:+.0f} L in one step", self.tick)
            owner.inventory[r.fuel] = liters
            key = f"{r.entity_id}/{r.fuel}"
            self._last_read_tick[key] = self.tick
            seen.add(key)

        # --- demand observations (what the forecaster learns from)
        for d in b.demand:
            st = self.stations_.get(d.station_id)
            if st is None or d.fuel not in st.capacity:
                q.reject("unknown_entity", f"demand for {d.station_id}/{d.fuel}", self.tick)
                continue
            if not _finite(d.liters) or d.liters < 0:
                q.reject("invalid_value", f"demand {d.station_id}/{d.fuel} = {d.liters}", self.tick)
                continue
            tail = self._series_tail.setdefault((d.station_id, d.fuel), deque(maxlen=48))
            if len(tail) >= 12 and d.liters > 8 * max(statistics.median(tail), 1.0):
                q.flag("demand_outlier", f"{d.station_id}/{d.fuel} demand {d.liters:.0f} L is >8x its recent median", self.tick)
            else:
                q.ok()
            tail.append(d.liters)
            served = d.served if d.served is not None else d.liters
            unmet = d.unmet if d.unmet is not None else max(0.0, d.liters - served)
            self._row_id += 1
            self.rows.append(M.DemandRow(id=self._row_id, station_id=d.station_id, fuel_type=d.fuel, tick=self.tick, sim_time=self.time or datetime.now(UTC).replace(tzinfo=None),
                                         demand_liters=d.liters, served_liters=served, unmet_liters=unmet))
            self.served_total += served
            self.unmet_total += unmet

        # --- supply and events
        for sp in b.supply:
            if sp.depot_id not in self.depots_ or not _finite(sp.quantity) or sp.quantity < 0:
                q.reject("invalid_supply", f"supply {sp.id}", self.tick)
                continue
            self.arrivals_[sp.id] = M.SupplyArrival(id=sp.id, depot_id=sp.depot_id, fuel_type=sp.fuel, quantity=sp.quantity, planned_tick=sp.planned_tick, status=sp.status)
            q.ok()
        for ev in b.events:
            eid = ev.id if ev.id is not None else self._next_event
            self._next_event = max(self._next_event, eid) + 1
            self.events_[eid] = M.SimEvent(id=eid, type=ev.type, start_tick=ev.start_tick, end_tick=ev.end_tick, status=ev.status, parameters=ev.parameters)
            q.ok()

        # --- order acknowledgements from the executing system
        for a in b.acks:
            if not self.ack(a):
                q.reject("unknown_order", f"ack for order {a.order_id}", self.tick)
            else:
                q.ok()

        # --- sensor dropout: keep the last known reading, but say so
        stale = {}
        for owner in list(self.stations_.values()) + list(self.depots_.values()):
            for fuel in owner.capacity:
                key = f"{owner.id}/{fuel}"
                if key not in seen and b.inventory:
                    last = self._last_read_tick.get(key)
                    if last is not None and self.tick - last >= 2:
                        stale[key] = self.tick - last
        q.stale_series = stale
        if stale:
            q.flag("missing_readings", f"{len(stale)} series without a fresh reading (last known value kept)", self.tick)
        self.received_at = time.time()
        q.last_batch_at = self.received_at
        self._notify()
        return {"accepted": q.accepted - acc0, "rejected": q.rejected - rej0, "tick": self.tick, "quality": round(q.score, 3)}

    # ------------------------------------------------------------------ orders (the write side)
    async def create_allocation(self, req: M.AllocationRequest) -> M.Allocation:
        existing = self._by_key.get(req.idempotency_key)
        if existing is not None:
            o = self.orders[existing]
            same = (o.source_depot_id, o.destination_station_id, o.route_id, o.fuel_type, o.quantity) == (req.source_depot_id, req.destination_station_id, req.route_id, req.fuel_type, req.quantity)
            if not same:
                raise AllocationRejected(409, "IDEMPOTENCY_KEY_MISMATCH", "key already used for a different order")
            return o
        route = self.routes_.get(req.route_id)
        if route is None or req.source_depot_id not in self.depots_ or req.destination_station_id not in self.stations_:
            raise AllocationRejected(404, "NOT_FOUND", "unknown depot, station or route")
        if (route.source_depot_id, route.destination_station_id) != (req.source_depot_id, req.destination_station_id):
            raise AllocationRejected(409, "ROUTE_MISMATCH", "route connects different endpoints")
        if req.quantity > route.max_shipment:
            raise AllocationRejected(409, "ROUTE_CAPACITY_EXCEEDED", "quantity above route maximum")
        o = M.Allocation(id=self._next_order, idempotency_key=req.idempotency_key, source_depot_id=req.source_depot_id,
                         destination_station_id=req.destination_station_id, route_id=req.route_id, fuel_type=req.fuel_type,
                         quantity=req.quantity, created_tick=self.tick, expected_arrival_tick=self.tick + 1 + route.transit_ticks, status="PENDING")
        self._next_order += 1
        self.orders[o.id] = o
        self._by_key[o.idempotency_key] = o.id
        if self.s.feed_webhook_url:
            t = asyncio.create_task(self._webhook(o))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)
        return o

    async def _webhook(self, o: M.Allocation) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as h:
                await h.post(self.s.feed_webhook_url, json=o.model_dump(mode="json"))
        except Exception as e:  # the pull endpoint remains the source of truth
            log.warning("feed_webhook_failed", error=str(e)[:100])

    async def cancel_allocation(self, order_id: int) -> dict:
        o = self.orders.get(order_id)
        if o is None:
            raise AllocationRejected(404, "ALLOCATION_NOT_FOUND", "unknown order")
        if o.status != "PENDING":
            raise AllocationRejected(409, "CANNOT_CANCEL", f"order is {o.status}")
        o.status = "CANCELLED"
        return o.model_dump(mode="json")

    def ack(self, a: Ack) -> bool:
        o = self.orders.get(a.order_id)
        if o is None:
            return False
        o.status = a.status
        if a.departure_tick is not None:
            o.departure_tick = a.departure_tick
        if a.arrival_tick is not None:
            (setattr(o, "actual_arrival_tick", a.arrival_tick) if a.status == "ARRIVED" else setattr(o, "expected_arrival_tick", a.arrival_tick))
        if a.reason:
            o.failure_reason = a.reason
        return True

    def pending_orders(self, status: str | None = None) -> list[M.Allocation]:
        return [o for o in self.orders.values() if status is None or o.status == status]

    # ------------------------------------------------------------------ contract reads
    def _require(self) -> None:
        if not (self.stations_ or self.depots_):
            raise SourceUnavailable("no data received from the feed yet")

    async def instance(self) -> M.Instance:
        self._require()
        return M.Instance(scenario_id="live-feed", tick=self.tick, sim_time=self.time or datetime.now(UTC).replace(tzinfo=None), tick_minutes=self.tick_minutes,
                          status="STALE" if self.last_stale else "LIVE")

    async def regions(self) -> list[M.Region]:
        return list(self.regions_.values())

    async def depots(self) -> list[M.Depot]:
        self._require()
        return [d.model_copy(deep=True) for d in self.depots_.values()]

    async def stations(self) -> list[M.Station]:
        self._require()
        return [s.model_copy(deep=True) for s in self.stations_.values()]

    async def routes(self) -> list[M.Route]:
        return list(self.routes_.values())

    async def supply_arrivals(self) -> list[M.SupplyArrival]:
        return sorted(self.arrivals_.values(), key=lambda a: a.planned_tick)

    async def events(self) -> list[M.SimEvent]:
        return sorted(self.events_.values(), key=lambda e: -e.id)

    async def allocations(self) -> list[M.Allocation]:
        return sorted(self.orders.values(), key=lambda o: -o.id)

    async def metrics(self) -> M.Metrics:
        total = self.served_total + self.unmet_total
        moving = sum(o.quantity for o in self.orders.values() if o.status in ("IN_TRANSIT", "ARRIVED"))
        return M.Metrics(served_demand_liters=self.served_total, unmet_demand_liters=self.unmet_total,
                         service_level=(self.served_total / total) if total else 1.0, allocation_liters=moving,
                         allocation_failures=sum(1 for o in self.orders.values() if o.status == "FAILED"))

    async def demand_history(self, station_id: str | None = None, limit: int = 2000) -> list[M.DemandRow]:
        rows = self.rows if station_id is None else [r for r in self.rows if r.station_id == station_id]
        return list(rows)[-limit:]

    # ------------------------------------------------------------------ status for the UI
    def status(self) -> dict:
        return {
            "kind": self.kind, "tick": self.tick, "time": self.time.isoformat() if self.time else None, "tick_minutes": self.tick_minutes,
            "depots": len(self.depots_), "stations": len(self.stations_), "routes": len(self.routes_),
            "fuels": sorted({f for s in self.stations_.values() for f in s.capacity}),
            "orders": {s: sum(1 for o in self.orders.values() if o.status == s) for s in ("PENDING", "IN_TRANSIT", "ARRIVED", "FAILED", "CANCELLED")},
            "topology_version": self.topology_version, "stale": self.last_stale,
            "quality": self.quality.snapshot(self._silence_s()),
        }
