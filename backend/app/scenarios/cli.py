"""python -m app.scenarios.cli --scenarios all --policies none,rules,optimizer --ticks 192"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from app.core.apistats import ApiStats
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.main import build_runtime
from app.scenarios.library import SCENARIOS
from app.scenarios.runner import run_scenario

OUT = Path(__file__).resolve().parents[3] / "docs"
POLICY_ORDER = ["none", "rules", "optimizer"]


def markdown(results: list[dict], ticks: int = 0) -> str:
    intro = (
        "# Benchmark results\n\n"
        f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Each run resets the deterministic simulator (fixed seed), "
        "injects the scenario, then plays it under one policy. 1 tick = 15 simulated minutes.\n\n"
        "Policies: `none` = do nothing, `rules` = greedy rule-based baseline, `optimizer` = OR-Tools planner.\n"
    )
    lines = [
        intro,
        "| Scenario | Policy | Ticks | Service level | Unmet (L) | Served (L) | Shipped (L) | Rejected | Cycle avg/p95 ms |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| {r['scenario']} | {r['policy']} | {r['ticks']} | {r['service_level']:.2%} | {r['unmet_l']:,} | "
            f"{r['served_l']:,} | {r['allocated_l']:,} | {r['rejected_decisions']} | {r['cycle_ms_avg']}/{r['cycle_ms_p95']} |"
        )
    return "\n".join(lines) + "\n"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="all")
    ap.add_argument("--policies", default="none,rules,optimizer")
    ap.add_argument("--ticks", type=int, default=192)
    ap.add_argument("--forecaster", default=None)
    a = ap.parse_args()
    cfg = get_settings()
    setup_logging("ERROR")
    rt = build_runtime(cfg, ApiStats())
    await rt.repo.start()
    names = list(SCENARIOS) if a.scenarios == "all" else a.scenarios.split(",")
    results = []
    for sc in names:
        for pol in a.policies.split(","):
            r = await run_scenario(rt, sc, pol, a.ticks, a.forecaster, progress=print)
            results.append(r)
            print(f"{sc:18s} {pol:10s} SL={r['service_level']:.2%} unmet={r['unmet_l']:>8,} L "
                  f"shipped={r['allocated_l']:>8,} rejected={r['rejected_decisions']} cycle={r['cycle_ms_avg']}ms ({r['wall_s']}s)")
            rt.repo.experiment({"name": f"{sc}/{pol}", "policy": pol, "forecaster": r["forecaster"],
                                "model_version": "seasonal-ewma-v1", "scenario": sc,
                                "metrics": {k: v for k, v in r.items() if k != "series"}})
    OUT.mkdir(exist_ok=True)
    f = OUT / "benchmark_results.json"
    old = json.loads(f.read_text())["results"] if f.exists() else []
    fresh = {(r["scenario"], r["policy"]) for r in results}
    merged = [r for r in old if (r["scenario"], r["policy"]) not in fresh] + results
    order = list(SCENARIOS)
    merged.sort(key=lambda r: (order.index(r["scenario"]) if r["scenario"] in order else 99, POLICY_ORDER.index(r["policy"])))
    f.write_text(json.dumps({"generated": time.time(), "ticks": a.ticks, "results": merged}))
    (OUT / "BENCHMARK.md").write_text(markdown(merged))
    await asyncio.sleep(2)  # let buffered DB writes flush
    await rt.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
