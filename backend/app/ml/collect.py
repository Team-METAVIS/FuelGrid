"""python -m app.ml.collect [--sim] [--worlds]   -> writes ml_data/*.json.gz

Simulator data is collected by resetting the simulator and stepping it through scenarios (needs the simulator running).
World data is generated locally and needs nothing."""
import argparse
import asyncio

from app.core.config import get_settings
from app.ml import datasets as D
from app.scenarios.library import SCENARIOS
from app.simulator.client import SimulatorClient

SIM_SCENARIOS = ["baseline", "demand_spike", "combined_crisis", "scarcity", "severe_crisis"]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--worlds", action="store_true")
    ap.add_argument("--ticks", type=int, default=576, help="simulator ticks per scenario")
    a = ap.parse_args()
    if a.worlds or not a.sim:
        for seed, changes in D.DEFAULT_WORLD_CHANGES.items():
            s = D.world_series(seed, 1500, changes)
            print("world", seed, len(s), "series ->", D.save(s, f"world_{seed}"))
    if a.sim:
        client = SimulatorClient(get_settings())
        try:
            s = await D.collect_simulator(client, {k: SCENARIOS[k] for k in SIM_SCENARIOS}, a.ticks)
        finally:
            await client.aclose()
        print("simulator", len(s), "series ->", D.save(s, "sim_all"))


if __name__ == "__main__":
    asyncio.run(main())
