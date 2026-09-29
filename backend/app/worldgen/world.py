"""An independent, deliberately different fuel network.

Purpose: prove FuelGrid is not tied to the organizer's simulator. This world has a different topology, different products
(including LPG), a different clock (30-minute ticks), smooth daily demand curves, weekday/weekend seasonality, trends and
autocorrelated noise. None of it is known to FuelGrid in advance: the platform must learn it from telemetry.

It also injects the messy dynamics of a real network so adaptation can be measured:
    demand_shift        permanent step change in demand (regime change)
    seasonality_shift   the daily peaks move by several hours (concept drift)
    demand_shock        a sudden, unannounced surge at one station for a while
    sensor_dropout      several stations stop reporting
    road_closure        a route becomes unusable (status change)
    new_station         a station appears mid-run (topology change)
    capacity_change     a depot loses dispatch capacity
plus a small rate of corrupted readings to exercise data-quality validation.

The world is pure and deterministic given its seed; it does not know how it is connected (in-process or over HTTP)."""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

FUELS = ["DIESEL", "PETROL", "OCTANE", "LPG"]
START = datetime(2026, 3, 2, 0, 0)  # a Monday


@dataclass
class _Station:
    id: str
    name: str
    region: str
    capacity: dict[str, float]
    inventory: dict[str, float]
    daily: dict[str, float]
    peaks: list[tuple[float, float, float]]  # (hour, width_h, amplitude)
    weekend: float
    trend: float
    sigma: float
    status: str = "OPEN"
    noise: dict[str, float] = field(default_factory=dict)
    shock: float = 1.0
    shock_until: int = -1


@dataclass
class _Depot:
    id: str
    name: str
    region: str
    capacity: dict[str, float]
    inventory: dict[str, float]
    dispatch: float
    status: str = "OPEN"


@dataclass
class _Route:
    id: str
    depot: str
    station: str
    transit: int
    max_shipment: float
    status: str = "AVAILABLE"
    reopen_tick: int = -1


class World:
    tick_minutes = 30

    def __init__(self, seed: int = 7, corrupt_rate: float = 0.004):
        self.rng = np.random.default_rng(seed)
        self.seed = seed
        self.corrupt_rate = corrupt_rate
        self.tick = 0
        self.depots: dict[str, _Depot] = {}
        self.stations: dict[str, _Station] = {}
        self.routes: dict[str, _Route] = {}
        self.level = 1.0  # global regime multiplier (demand_shift)
        self.peak_shift_h = 0.0  # seasonality_shift
        self.dropout: dict[str, int] = {}  # station id -> tick until which it does not report
        self.in_transit: list[dict] = []  # {arrive, station, fuel, qty, order}
        self.known_orders: set[int] = set()
        self.supply: list[dict] = []
        self.served = 0.0
        self.unmet = 0.0
        self.shipped = 0.0  # liters dispatched by the platform
        self.legacy = True  # a plain min/max dispatcher runs while history is being generated
        self.topology_dirty = True
        self.log: list[str] = []
        self._build()

    # ------------------------------------------------------------------ construction
    def _build(self) -> None:
        r = self.rng
        for i, region in enumerate(("North", "South", "East")):
            caps = {f: float(r.integers(70, 110) * 1000 * (0.5 if f == "LPG" else 1.0)) for f in FUELS}
            self.depots[f"D{i + 1}"] = _Depot(f"D{i + 1}", f"{region} Depot", region, caps, {f: c * r.uniform(0.6, 0.85) for f, c in caps.items()}, float(r.integers(40, 53) * 100))  # trucking capacity per tick is a real constraint
        depot_ids = list(self.depots)
        for j in range(8):
            self._add_station(j, depot_ids)

    def _add_station(self, j: int, depot_ids: list[str]) -> str:
        r = self.rng
        sid = f"S{j + 1}"
        region = self.depots[depot_ids[j % len(depot_ids)]].region
        daily = {f: float(r.lognormal(mean=math.log(9000 if f in ("DIESEL", "PETROL") else 4000 if f == "OCTANE" else 2500), sigma=0.4)) for f in FUELS}
        caps = {f: daily[f] * float(r.uniform(0.9, 1.3)) for f in FUELS}  # about a day of cover: timing matters
        peaks = [(float(r.uniform(6, 10)), float(r.uniform(1.2, 2.5)), float(r.uniform(0.8, 1.8))), (float(r.uniform(15, 20)), float(r.uniform(1.5, 3.0)), float(r.uniform(0.6, 1.6)))]
        st = _Station(sid, f"Station {j + 1}", region, caps, {f: c * r.uniform(0.55, 0.85) for f, c in caps.items()}, daily, peaks,
                      weekend=float(r.uniform(0.6, 1.35)), trend=float(r.uniform(-0.02, 0.05)), sigma=float(r.uniform(0.10, 0.18)))
        self.stations[sid] = st
        home = depot_ids[j % len(depot_ids)]
        self.routes[f"R{sid}-{home}"] = _Route(f"R{sid}-{home}", home, sid, int(r.integers(1, 4)), float(r.integers(5, 9) * 1000))
        if j % 2 == 0:  # a second, longer route gives the optimizer a real choice
            other = depot_ids[(j + 1) % len(depot_ids)]
            self.routes[f"R{sid}-{other}"] = _Route(f"R{sid}-{other}", other, sid, int(r.integers(3, 6)), float(r.integers(4, 7) * 1000))
        self.topology_dirty = True
        return sid

    # ------------------------------------------------------------------ demand physics
    @property
    def now(self) -> datetime:
        return START + timedelta(minutes=self.tick * self.tick_minutes)

    def _profile(self, st: _Station, hour: float) -> float:
        def raw(h: float) -> float:
            v = 1.0
            for m, w, a in st.peaks:
                d = min(abs(h - (m + self.peak_shift_h)), 24 - abs(h - (m + self.peak_shift_h)))
                v += a * math.exp(-(d * d) / (2 * w * w))
            return v
        norm = sum(raw(x + 0.5) for x in range(24)) / 24
        return raw(hour) / norm

    def demand(self, st: _Station, fuel: str) -> float:
        ticks_per_day = 1440 / self.tick_minutes
        t = self.now
        hour = t.hour + t.minute / 60
        dow = 1.0 if t.weekday() < 5 else st.weekend
        trend = 1 + st.trend * (self.tick / (ticks_per_day * 7))
        z = 0.5 * st.noise.get(fuel, 0.0) + float(self.rng.normal(0, st.sigma * 0.87))
        st.noise[fuel] = z
        shock = st.shock if self.tick < st.shock_until else 1.0
        return max(0.0, st.daily[fuel] / ticks_per_day * self._profile(st, hour) * dow * trend * self.level * shock * math.exp(z))

    # ------------------------------------------------------------------ dynamics injected on demand
    def inject(self, kind: str, magnitude: float = 1.4, duration: int = 24) -> str:
        r = self.rng
        sts = list(self.stations.values())
        if kind == "demand_shift":
            self.level *= magnitude
            msg = f"permanent demand shift x{magnitude:.2f} at tick {self.tick}"
        elif kind == "seasonality_shift":
            self.peak_shift_h += 3.0
            msg = f"daily demand peaks moved +3 h at tick {self.tick}"
        elif kind == "demand_shock":
            st = sts[int(r.integers(len(sts)))]
            st.shock, st.shock_until = magnitude, self.tick + duration
            msg = f"unannounced demand surge x{magnitude:.2f} at {st.name} for {duration} ticks"
        elif kind == "sensor_dropout":
            for st in r.choice(sts, size=min(3, len(sts)), replace=False):
                self.dropout[st.id] = self.tick + duration
            msg = f"3 stations stop reporting for {duration} ticks"
        elif kind == "road_closure":
            rt = list(self.routes.values())[int(r.integers(len(self.routes)))]
            rt.status, rt.reopen_tick = "DISRUPTED", self.tick + duration
            msg = f"road {rt.id} closed for {duration} ticks"
        elif kind == "new_station":
            sid = self._add_station(len(self.stations), list(self.depots))
            msg = f"new station {sid} added to the network"
        elif kind == "capacity_change":
            d = list(self.depots.values())[int(r.integers(len(self.depots)))]
            d.dispatch *= 0.5
            msg = f"{d.name} dispatch capacity halved"
        else:
            raise ValueError(f"unknown change: {kind}")
        self.log.append(msg)
        return msg

    # ------------------------------------------------------------------ what the outside world sees
    def topology(self) -> dict:
        self.topology_dirty = False
        return {
            "tick_minutes": self.tick_minutes,
            "regions": [{"id": n, "name": n} for n in sorted({d.region for d in self.depots.values()})],
            "depots": [{"id": d.id, "name": d.name, "region_id": d.region, "status": d.status, "dispatch_capacity_per_tick": d.dispatch,
                        "capacity": d.capacity, "inventory": {k: round(v, 1) for k, v in d.inventory.items()}} for d in self.depots.values()],
            "stations": [{"id": s.id, "name": s.name, "region_id": s.region, "status": s.status, "capacity": s.capacity,
                          "inventory": {k: round(v, 1) for k, v in s.inventory.items()}} for s in self.stations.values()],
            "routes": [{"id": r.id, "source_depot_id": r.depot, "destination_station_id": r.station, "transit_ticks": r.transit,
                        "max_shipment": r.max_shipment, "status": r.status} for r in self.routes.values()],
        }

    def step(self, new_orders: list[dict] | None = None) -> dict:
        """Advance one tick. `new_orders` are dispatch orders from the platform ({id, depot, station, route, fuel, qty})."""
        self.tick += 1
        acks: list[dict] = []
        status: list[dict] = []
        # roads reopen
        for rt in self.routes.values():
            if rt.status == "DISRUPTED" and self.tick >= rt.reopen_tick:
                rt.status = "AVAILABLE"
                status.append({"entity_id": rt.id, "status": "AVAILABLE"})
        # deliveries land
        keep = []
        for sh in self.in_transit:
            if sh["arrive"] <= self.tick:
                st = self.stations[sh["station"]]
                st.inventory[sh["fuel"]] = min(st.capacity[sh["fuel"]], st.inventory[sh["fuel"]] + sh["qty"])
                if sh["order"] is not None:
                    acks.append({"order_id": sh["order"], "status": "ARRIVED", "arrival_tick": self.tick})
            else:
                keep.append(sh)
        self.in_transit = keep
        # depot resupply once a day (about twice the network's daily demand in total), sometimes short
        if self.tick % 48 == 5:
            for d in self.depots.values():
                for f in FUELS:
                    d.inventory[f] = min(d.capacity[f], d.inventory[f] + d.capacity[f] * float(self.rng.uniform(0.35, 0.6)))
            self.supply.append({"id": f"SUP{self.tick}", "depot_id": "D1", "fuel": "DIESEL", "quantity": 0.0, "planned_tick": self.tick, "status": "ARRIVED"})
        # orders from the platform
        for o in new_orders or []:
            if o["id"] in self.known_orders:
                continue
            self.known_orders.add(o["id"])
            d, rt = self.depots.get(o["depot"]), self.routes.get(o["route"])
            if d is None or rt is None or rt.status != "AVAILABLE" or d.inventory.get(o["fuel"], 0) < o["qty"]:
                acks.append({"order_id": o["id"], "status": "FAILED", "reason": "route closed or depot stock too low"})
                continue
            d.inventory[o["fuel"]] -= o["qty"]
            self.shipped += o["qty"]
            self.in_transit.append({"arrive": self.tick + rt.transit, "station": o["station"], "fuel": o["fuel"], "qty": o["qty"], "order": o["id"]})
            acks.append({"order_id": o["id"], "status": "IN_TRANSIT", "departure_tick": self.tick, "arrival_tick": self.tick + rt.transit})
        # a plain min/max dispatcher stands in for the "old way" while history is being built
        if self.legacy:
            for st in self.stations.values():
                for f in FUELS:
                    if st.inventory[f] < 0.4 * st.capacity[f]:
                        rts = sorted((r for r in self.routes.values() if r.station == st.id and r.status == "AVAILABLE"), key=lambda r: r.transit)
                        if rts and self.depots[rts[0].depot].inventory[f] > 0.15 * self.depots[rts[0].depot].capacity[f]:
                            q = min(rts[0].max_shipment, st.capacity[f] * 0.5)
                            self.depots[rts[0].depot].inventory[f] -= q
                            self.in_transit.append({"arrive": self.tick + rts[0].transit, "station": st.id, "fuel": f, "qty": q, "order": None})
        # consumption
        demand, inv = [], []
        for st in self.stations.values():
            for f in FUELS:
                d = self.demand(st, f)
                served = min(d, st.inventory[f])
                st.inventory[f] -= served
                self.served += served
                self.unmet += d - served
                demand.append({"station_id": st.id, "fuel": f, "liters": round(d, 2), "served": round(served, 2), "unmet": round(d - served, 2)})
        # what sensors report (with dropouts and the odd corrupted value)
        for st in self.stations.values():
            if self.dropout.get(st.id, -1) > self.tick:
                continue
            for f in FUELS:
                v = st.inventory[f]
                if self.rng.random() < self.corrupt_rate:
                    v = -1.0 if self.rng.random() < 0.5 else v * 40
                inv.append({"entity_id": st.id, "fuel": f, "liters": round(v, 1)})
        for d in self.depots.values():
            for f in FUELS:
                inv.append({"entity_id": d.id, "fuel": f, "liters": round(d.inventory[f], 1)})
        return {"time": self.now.isoformat(), "tick": self.tick, "inventory": inv, "demand": demand, "status": status,
                "supply": self.supply[-3:], "events": [], "acks": acks}

    @property
    def service_level(self) -> float:
        t = self.served + self.unmet
        return self.served / t if t else 1.0
