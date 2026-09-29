"""Training and evaluation data from two very different worlds.

  * the organizer's simulator, driven through several crisis scenarios (real data from the real environment)
  * independent generated worlds (other topology, products, clock, weekly seasonality) with regime changes injected

Collected datasets are cached as compressed JSON so a model can be retrained without re-running anything."""
import gzip
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from app.domain import models as M
from app.ml.covariates import announced_multiplier
from app.ml.features import SeriesData, dense
from app.worldgen.world import START, World

DATA = Path(__file__).resolve().parents[2] / "ml_data"


def _minutes(t: datetime) -> int:
    return int((t - datetime(1970, 1, 1)).total_seconds() // 60)


# ------------------------------------------------------------------------------------------------ independent worlds
def world_series(seed: int, ticks: int = 1500, changes: dict[int, tuple[str, float]] | None = None, origin: str | None = None) -> list[SeriesData]:
    """Run an independent world with its old min/max dispatcher and record the demand it produced."""
    w = World(seed)
    rows: dict[str, tuple[list[int], list[float]]] = {}
    plan = changes or {}
    for _ in range(ticks):
        if w.tick + 1 in plan:
            w.inject(*plan[w.tick + 1])
        tel = w.step([])
        for d in tel["demand"]:
            r = rows.setdefault(f"{d['station_id']}/{d['fuel']}", ([], []))
            r[0].append(tel["tick"])
            r[1].append(d["liters"])
    out = []
    for key, (t, v) in rows.items():
        s = dense(t, v, [1.0] * len(t), _minutes(START) + t[0] * w.tick_minutes, w.tick_minutes, key, origin or f"world:{seed}")
        if s:
            out.append(s)
    return out


DEFAULT_WORLD_CHANGES = {
    1: {500: ("demand_shift", 1.25), 900: ("seasonality_shift", 1.0)},
    2: {600: ("demand_shift", 0.8), 1000: ("demand_shock", 1.8)},
    3: {450: ("demand_shift", 1.4), 800: ("seasonality_shift", 1.0), 1100: ("demand_shock", 1.6)},
    4: {700: ("demand_shift", 1.15)},
}


# ------------------------------------------------------------------------------------------------ the simulator
async def collect_simulator(client, scenarios: dict[str, dict], ticks: int = 576, progress=print) -> list[SeriesData]:
    """Drive the simulator through each scenario (reset, inject events, step) and record demand plus announced events."""
    out: list[SeriesData] = []
    for name, spec in scenarios.items():
        await client.admin("POST", "/admin/faults/clear")
        await client.admin("POST", "/admin/pause")
        await client.admin("POST", "/admin/reset")
        await client.admin("POST", "/admin/pause")
        for ev in spec["events"]:
            await client.admin("POST", "/admin/events", ev)
        stations = {s.id: s for s in await client.stations()}
        rows: dict[str, dict[int, tuple[datetime, float]]] = {}
        for step in range(ticks):
            await client.admin("POST", "/admin/step")
            if step % 50 == 49 or step == ticks - 1:
                for r in await client.demand_history(None, 2000):
                    rows.setdefault(f"{r.station_id}/{r.fuel_type}", {})[r.tick] = (r.sim_time, r.demand_liters)
        events = await client.events()
        for key, d in rows.items():
            sid = key.split("/")[0]
            ticks_l = sorted(d)
            st = stations[sid]
            mult = [announced_multiplier(events, sid, st.region_id, t) for t in ticks_l]
            s = dense(ticks_l, [d[t][1] for t in ticks_l], mult, _minutes(d[ticks_l[0]][0]), 15, key, f"sim:{name}")
            if s:
                s.meta = {"profile": st.demand_profile, "region": st.region_id, "fuel": key.split("/")[1]}
                out.append(s)
        progress(f"  collected simulator scenario '{name}': {len(ticks_l)} ticks x {len(rows)} series")
    return out


# ------------------------------------------------------------------------------------------------ cache
def save(series: list[SeriesData], name: str) -> Path:
    DATA.mkdir(exist_ok=True)
    p = DATA / f"{name}.json.gz"
    payload = [{"key": s.key, "minutes0": s.minutes0, "y": [round(float(v), 3) for v in s.y], "mult": [round(float(v), 3) for v in s.mult],
                "tick_minutes": s.tick_minutes, "origin": s.origin, "meta": s.meta} for s in series]
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    return p


def load(name: str) -> list[SeriesData]:
    p = DATA / f"{name}.json.gz"
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [SeriesData(d["key"], d["minutes0"], np.asarray(d["y"]), np.asarray(d["mult"]), d["tick_minutes"], d["origin"], d.get("meta", {})) for d in json.load(f)]


def exists(name: str) -> bool:
    return (DATA / f"{name}.json.gz").exists()


__all__ = ["M", "world_series", "collect_simulator", "save", "load", "exists", "DEFAULT_WORLD_CHANGES"]
