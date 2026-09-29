"""Parameter sweep = experiment tracking. Every run is replayed on the same deterministic world and recorded
(Supabase table fg_experiments + docs/TUNING.md), so default settings are chosen by measurement, not by feel.

python -m app.scenarios.sweep --scenarios scarcity,severe_crisis --ticks 192
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

from app.core.apistats import ApiStats
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.main import build_runtime
from app.scenarios.runner import run_scenario

OUT = Path(__file__).resolve().parents[3] / "docs"

# one-factor-at-a-time around the defaults, plus the defaults themselves
GRID = [
    ("baseline (cover 32, z 2.0, reserve 10%)", {}),
    ("shorter cover (16 ticks)", {"target_cover_ticks": 16}),
    ("longer cover (32 ticks)", {"target_cover_ticks": 32}),
    ("small safety buffer (z 0.5)", {"safety_z": 0.5}),
    ("large safety buffer (z 2.0)", {"safety_z": 2.0}),
    ("no depot reserve", {"depot_reserve_frac": 0.0}),
    ("large depot reserve (20%)", {"depot_reserve_frac": 0.2}),
]

COMBOS = [
    ("current defaults (cover 24, z 1.28)", {}),
    ("cover 32, z 1.28", {"target_cover_ticks": 32}),
    ("cover 32, z 2.0", {"target_cover_ticks": 32, "safety_z": 2.0}),
    ("cover 40, z 1.28", {"target_cover_ticks": 40}),
    ("cover 40, z 2.0", {"target_cover_ticks": 40, "safety_z": 2.0}),
]
GRIDS = {"single": GRID, "combos": COMBOS}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="scarcity,severe_crisis")
    ap.add_argument("--ticks", type=int, default=192)
    ap.add_argument("--grid", default="single", choices=list(GRIDS))
    ap.add_argument("--out", default="tuning")
    a = ap.parse_args()
    cfg = get_settings()
    setup_logging("ERROR")
    rt = build_runtime(cfg, ApiStats())
    await rt.repo.start()
    rows = []
    for label, overrides in GRIDS[a.grid]:
        saved = {k: getattr(cfg, k) for k in overrides}
        for k, v in overrides.items():
            setattr(cfg, k, v)
        per = {}
        for sc in a.scenarios.split(","):
            r = await run_scenario(rt, sc, "optimizer", a.ticks)
            per[sc] = {k: r[k] for k in ("service_level", "unmet_l", "allocated_l", "rejected_decisions", "forecast_mape")}
            rt.repo.experiment({"name": f"sweep: {label} / {sc}", "policy": "optimizer", "forecaster": cfg.forecaster,
                                "model_version": "seasonal-events-v2", "scenario": sc,
                                "metrics": {**per[sc], "overrides": overrides}})
        for k, v in saved.items():
            setattr(cfg, k, v)
        rows.append({"label": label, "overrides": overrides, "per": per})
        s = " | ".join(f"{sc}: SL={p['service_level']:.2%} shipped={p['allocated_l']:,}" for sc, p in per.items())
        print(f"{label:44s} {s}", flush=True)
    (OUT / f"{a.out}_results.json").write_text(json.dumps({"generated": time.time(), "ticks": a.ticks, "rows": rows}))
    scs = a.scenarios.split(",")
    head = "| Setting | " + " | ".join(f"{s} service | {s} unmet L | {s} shipped L" for s in scs) + " |"
    lines = [
        "# Planner tuning sweep\n",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Optimizer policy, {a.ticks} ticks per run on the same deterministic world; "
        "one setting changed at a time. Higher service level is better; at equal service level, less fuel shipped is better "
        "(less waste and less trucking).\n",
        head, "|---|" + "---:|" * (3 * len(scs)),
    ]
    for r in rows:
        cells = []
        for sc in scs:
            p = r["per"][sc]
            cells += [f"{p['service_level']:.2%}", f"{p['unmet_l']:,}", f"{p['allocated_l']:,}"]
        lines.append(f"| {r['label']} | " + " | ".join(cells) + " |")
    (OUT / f"{a.out.upper()}.md").write_text("\n".join(lines) + "\n")
    await rt.repo.flush()
    await rt.client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
