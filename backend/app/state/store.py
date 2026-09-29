import bisect
import time
from collections import defaultdict
from dataclasses import dataclass, field

from app.domain import models as M


@dataclass
class Snapshot:
    instance: M.Instance
    depots: dict[str, M.Depot]
    stations: dict[str, M.Station]
    routes: dict[str, M.Route]
    arrivals: list[M.SupplyArrival]
    events: list[M.SimEvent]
    allocations: list[M.Allocation]
    metrics: M.Metrics
    fetched_at: float = field(default_factory=time.time)
    stale: bool = False

    @property
    def fuels(self) -> list[str]:
        """Every product present anywhere in the network (works for any fuel set)."""
        found: set[str] = set()
        for st in self.stations.values():
            found.update(st.capacity)
        for d in self.depots.values():
            found.update(d.capacity)
        return sorted(found)

    @property
    def tick(self) -> int:
        return self.instance.tick

    @property
    def tick_minutes(self) -> int:
        return self.instance.tick_minutes

    def age_s(self) -> float:
        return time.time() - self.fetched_at

    def in_transit(self) -> list[M.Allocation]:
        return [a for a in self.allocations if a.status in ("PENDING", "IN_TRANSIT")]

    def late_by_route(self) -> dict[str, int]:
        """Whole ticks each road usually runs late (learned from delivered shipments; empty when everything is on time)."""
        c = self.__dict__.get("_late")
        if c is None:
            from app.intelligence.eta import route_lateness

            c = {k: round(v["mean_late_ticks"]) for k, v in route_lateness(self).items()}
            self.__dict__["_late"] = c
        return c

    def transit_to(self, station_id: str, fuel: str) -> list[M.Allocation]:
        """In-flight shipments per (station, fuel), indexed once per snapshot (planning asks 12x per cycle)."""
        idx = self.__dict__.get("_transit_idx")
        if idx is None or self.__dict__.get("_transit_n") != len(self.allocations):
            idx = {}
            for a in self.allocations:
                if a.status in ("PENDING", "IN_TRANSIT"):
                    idx.setdefault((a.destination_station_id, a.fuel_type), []).append(a)
            self.__dict__["_transit_idx"], self.__dict__["_transit_n"] = idx, len(self.allocations)
        return idx.get((station_id, fuel), [])


class StateStore:
    """Latest good snapshot + accumulated demand history. Survives simulator outages (cached-state mode)."""

    def __init__(self):
        self.snapshot: Snapshot | None = None
        self.regions: dict[str, float] = {}  # region id -> demand factor (static world data, fetched once)
        # (station, fuel) -> {tick: (demand, served, unmet, sim_time)}
        self.demand: dict[tuple[str, str], dict[int, tuple[float, float, float, object]]] = defaultdict(dict)
        self._order: dict[tuple[str, str], list[int]] = defaultdict(list)  # sorted ticks per series

    def ingest_demand(self, rows: list[M.DemandRow]) -> int:
        n = 0
        for r in rows:
            key = (r.station_id, r.fuel_type)
            d = self.demand[key]
            if r.tick not in d:
                n += 1
                order = self._order[key]
                if not order or r.tick > order[-1]:
                    order.append(r.tick)
                else:
                    bisect.insort(order, r.tick)
            d[r.tick] = (r.demand_liters, r.served_liters, r.unmet_liters, r.sim_time)
        return n

    def series(self, station_id: str, fuel: str, last: int | None = None) -> list[tuple[int, float, object]]:
        key = (station_id, fuel)
        d = self.demand.get(key, {})
        ticks = self._order.get(key, [])
        if last:
            ticks = ticks[-last:]
        return [(t, d[t][0], d[t][3]) for t in ticks if t in d]

    def clear(self):
        self.demand.clear()
        self._order.clear()
