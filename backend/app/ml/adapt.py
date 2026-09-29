"""python -m app.ml.adapt

The judges' question: "in a real situation everything is dynamic, so how does the math cope?"  This experiment measures it.

The SAME independent world (a network the platform has never seen) and the SAME schedule of surprises are replayed under
five ways of forecasting demand, each feeding the same optimizer in a closed loop (plan -> approve -> world executes):

  1. expert profile        hand-set formula (knows the simulator's pattern, cannot learn)
  2. moving average        the classic simple approach
  3. trained, frozen       the trained model with online adaptation and retraining switched off
  4. trained + adaptation  online correction follows level shifts within a few ticks
  5. trained + adapt + retrain   also retrains a challenger on collected data; promoted only if clearly better

Surprises (ticks after warm-up): demand jumps 40% (t=150), daily peaks move 3 hours (t=300), three stations stop
reporting (t=450), a new station appears (t=520), an unannounced surge hits one station (t=600).
Output: docs/adaptation_report.json (figures, UI) and docs/ADAPTATION.md."""
import asyncio
import json
import time
from pathlib import Path

import numpy as np

from app.adapters.feed import FeedSource, TopologyIn
from app.core.config import Settings
from app.core.logging import setup_logging
from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from app.ml.manager import MODEL_DIR, manager
from app.ml.model import DemandModel
from app.state.store import StateStore
from app.state.sync import Synchronizer
from app.worldgen.driver import orders_for_world, push_tick
from app.worldgen.world import World

DOCS = Path(__file__).resolve().parents[3] / "docs"
REPLAN_EVERY = 2  # re-plan hourly (30-minute ticks). Every 6 h is throughput-limited by design (one shipment per route and fuel per plan)
SCHEDULE = {150: ("demand_shift", 1.4), 300: ("seasonality_shift", 1.0), 450: ("sensor_dropout", 1.0), 520: ("new_station", 1.0), 600: ("demand_shock", 1.8)}
CONFIGS = [
    ("Expert profile (hand-set)", dict(forecaster="seasonal", auto_retrain=False)),
    ("Moving average", dict(forecaster="moving_avg", auto_retrain=False)),
    ("Trained model, frozen", dict(forecaster="learned", online_adaptation=False, auto_retrain=False)),
    ("Trained + online adaptation", dict(forecaster="learned", online_adaptation=True, auto_retrain=False)),
    ("Trained + adaptation + retraining", dict(forecaster="learned", online_adaptation=True, auto_retrain=True, retrain_every_ticks=240)),
]


async def run(name: str, overrides: dict, seed: int, warmup: int, ticks: int) -> dict:
    cfg = Settings(database_url=None, decision_every_ticks=REPLAN_EVERY, **overrides)
    feed, store = FeedSource(cfg), StateStore()
    sync = Synchronizer(feed, store)
    eng = DecisionEngine(cfg, store, feed, Repo(None), "adapt")
    eng.refresh = sync.refresh
    eng.bench = True  # this script drives cycles itself
    manager.champion = None
    manager.registry.clear()
    manager.last_train_tick = 0  # the retraining schedule counts from go-live
    manager.bias.clear()
    manager.over.clear()
    if overrides.get("forecaster") == "learned":
        manager._set_champion(DemandModel.loads((MODEL_DIR / "champion.joblib").read_bytes()), "base")
    world = World(seed)
    feed.set_topology(TopologyIn(**world.topology()))
    for _ in range(warmup):
        push_tick(feed, world, [])
    world.legacy = False
    served0, unmet0, shipped0 = world.served, world.unmet, world.shipped
    rows, seen, retrains = [], 0, []
    for k in range(1, ticks + 1):
        if k in SCHEDULE:
            world.inject(*SCHEDULE[k])
        push_tick(feed, world, orders_for_world(feed))
        snap = await sync.refresh()
        eng._score_forecasts()
        if snap and k % REPLAN_EVERY == 0:
            await eng.cycle(snap)
            for d in [d for d in eng.decisions.values() if d.status == "PROPOSED"]:
                await eng.approve(d.id, actor="experiment")
            why = manager.due(snap.tick, cfg, drift=False)
            if why:
                res = await manager.retrain(store, snap, why)
                retrains.append({"tick": k, "status": res["status"], "message": res.get("message", res.get("reason", ""))})
        fresh = eng.ape_n - seen
        new = list(eng.ape)[-fresh:] if fresh > 0 else []
        seen = eng.ape_n
        rows.append({"tick": k, "mape": float(np.mean(new)) if new else None, "served": world.served - served0, "unmet": world.unmet - unmet0})
    # windowed service level and rolling error (24-tick windows) for the figures
    series = []
    for a in range(0, ticks, 24):
        blk = rows[a:a + 24]
        ms = [r["mape"] for r in blk if r["mape"] is not None]
        served = blk[-1]["served"] - (rows[a - 1]["served"] if a else 0)
        unmet = blk[-1]["unmet"] - (rows[a - 1]["unmet"] if a else 0)
        series.append({"tick": a + 24, "mape": float(np.mean(ms)) if ms else None, "service_level": served / max(served + unmet, 1e-9), "unmet": unmet})
    out = {"name": name, "series": series, "final_service_level": rows[-1]["served"] / max(rows[-1]["served"] + rows[-1]["unmet"], 1e-9),
           "unmet_liters": rows[-1]["unmet"], "shipped_liters": world.shipped - shipped0, "mean_mape": float(np.nanmean([r["mape"] for r in rows if r["mape"] is not None])), "retrains": retrains}
    print(f"{name:38s} service {out['final_service_level']:.2%}  unmet {out['unmet_liters']:>10,.0f} L  shipped {out['shipped_liters']:>9,.0f} L  mean 1-step error {out['mean_mape']:.1%}  retrains {[r['status'] for r in retrains]}", flush=True)
    return out


def recovery(series: list[dict], change_tick: int) -> dict:
    """Forecast error in the 48 ticks before a surprise, in the 24 ticks after it, and 48-72 ticks after it."""
    def mean_of(lo: int, hi: int) -> float | None:
        v = [x["mape"] for x in series if x["mape"] is not None and lo < x["tick"] <= hi]
        return float(np.mean(v)) if v else None
    return {"before": mean_of(change_tick - 48, change_tick), "just_after": mean_of(change_tick, change_tick + 24), "later": mean_of(change_tick + 48, change_tick + 72)}


def markdown(report: dict) -> str:
    sched, results = report["schedule"], report["results"]
    lines = [
        "# Adaptation experiment: how the platform copes when the world changes\n",
        "The same unseen network and the same five surprises (demand +40% at t=150, daily peaks +3 h at t=300, three sensors silent at t=450, "
        "a new station at t=520, an unannounced surge at t=600) were replayed under five forecasting approaches, each driving the same optimizer "
        "in a closed loop with hourly re-planning. Higher service level and lower error are better.\n",
        "| Approach | Service level | Unmet demand (L) | Fuel shipped (L) | Mean 1-step forecast error | Model retrains |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        promoted = sum(1 for x in r["retrains"] if x["status"] == "promoted")
        lines.append(f"| {r['name']} | {r['final_service_level']:.2%} | {r['unmet_liters']:,.0f} | {r['shipped_liters']:,.0f} | {r['mean_mape']:.1%} | {promoted} promoted / {len(r['retrains'])} run |")
    lines += ["\n## Forecast error around each surprise\n", "Mean 1-step error: 48 ticks before -> in the 24 ticks after -> 48-72 ticks after.\n",
              "| Approach | " + " | ".join(f"{v.replace('_', ' ')} (t={k})" for k, v in sched.items()) + " |", "|---|" + "---:|" * len(sched)]
    for r in results:
        cells = []
        for k in sched:
            a = r["after_change"][k]
            cells.append(" -> ".join(f"{a[x]:.0%}" if a[x] is not None else "-" for x in ("before", "just_after", "later")))
        lines.append(f"| {r['name']} | " + " | ".join(cells) + " |")
    lines += ["\n## Model retraining log (last approach)\n"] + [f"- t={x['tick']}: **{x['status']}** - {x['message']}" for x in results[-1]["retrains"]]
    return "\n".join(lines) + "\n"


async def main() -> None:
    import sys

    setup_logging("ERROR")
    t = time.time()
    if "--report-only" in sys.argv:  # recompute the tables from the saved measurements
        report = json.loads((DOCS / "adaptation_report.json").read_text(encoding="utf-8"))
        for r in report["results"]:
            r["after_change"] = {k: recovery(r["series"], int(k)) for k in report["schedule"]}
        (DOCS / "adaptation_report.json").write_text(json.dumps(report), encoding="utf-8")
        (DOCS / "ADAPTATION.md").write_text(markdown(report), encoding="utf-8")
        return
    results = [await run(n, o, seed=7, warmup=240, ticks=700) for n, o in CONFIGS]
    for r in results:
        r["after_change"] = {str(k): recovery(r["series"], k) for k in SCHEDULE}
    report = {"schedule": {str(k): v[0] for k, v in SCHEDULE.items()}, "results": results, "seed": 7, "ticks": 700, "generated": time.time(), "seconds": round(time.time() - t)}
    (DOCS / "adaptation_report.json").write_text(json.dumps(report), encoding="utf-8")
    (DOCS / "ADAPTATION.md").write_text(markdown(report), encoding="utf-8")
    print("done in", round(time.time() - t), "s")


if __name__ == "__main__":
    asyncio.run(main())
