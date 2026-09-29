"""python -m app.ml.train

Trains the demand model on collected data, runs the evaluation experiments, saves the champion and writes
docs/model_report.json (used by the UI and the README figures) and docs/MODEL.md.

Experiments (all walk-forward on data the model did not train on):
  E1  held-out simulator scenario      train: other sim scenarios + generated worlds      test: sim 'severe_crisis'
  E2  unseen generated network         train: sim + worlds 1-3                            test: world 4
  E3a zero-shot: simulator -> world    train: simulator only                              test: world 4
  E3b zero-shot: worlds -> simulator   train: generated worlds only                       test: sim 'severe_crisis'
  E4  future window                    train: first 75% of every series                   test: last 25%"""
import json
import time
from pathlib import Path

import numpy as np
from sklearn.inspection import permutation_importance

from app.intelligence.priors import prior_per_tick
from app.ml import datasets as D
from app.ml.backtest import backtest
from app.ml.features import FEATURES, SeriesData
from app.ml.manager import manager
from app.ml.model import DemandModel

DOCS = Path(__file__).resolve().parents[3] / "docs"
REGION = {"region-dhaka": 1.0, "region-chattogram": 1.08}


def expert(s: SeriesData, i: int, h: int) -> float:
    """A hand-set model that KNOWS the simulator's documented demand pattern (and announced events) but never learns."""
    m = s.meta
    hour = int(s.minutes(i + h) % 1440 // 60)
    mult = s.mult[i + h] if i + h < s.n else s.mult[-1]
    return prior_per_tick(m["profile"], m["fuel"], hour, s.tick_minutes) * REGION.get(m["region"], 1.0) * mult


def sel(series: list[SeriesData], prefix: str, exclude: str | None = None) -> list[SeriesData]:
    return [s for s in series if s.origin.startswith(prefix) and not (exclude and s.origin == exclude)]


def run_experiment(name: str, train: list[SeriesData], test: list[SeriesData], from_frac: float, with_expert: bool) -> dict:
    t = time.time()
    model = DemandModel.fit(train, stride=4)
    res = backtest(model, test, from_frac=from_frac, stride=4, extra={"expert profile": expert} if with_expert else None)
    res.update({"name": name, "train_series": len(train), "train_rows": model.meta["rows"], "test_series": len(test), "fit_seconds": round(time.time() - t, 1)})
    print(f"{name}: model WAPE h1/h8/h32 = {res['wape']['model']['1']:.3f}/{res['wape']['model']['8']:.3f}/{res['wape']['model']['32']:.3f}  "
          f"naive {res['wape']['naive']['8']:.3f} yesterday {res['wape']['yesterday']['8']:.3f} coverage {res['coverage_80']['8']:.2f}", flush=True)
    return res


def main() -> None:
    sim = D.load("sim_all")
    worlds = {i: D.load(f"world_{i}") for i in (1, 2, 3, 4)}
    all_worlds = [s for w in worlds.values() for s in w]
    report: dict = {"experiments": []}
    holdout = "sim:severe_crisis"
    report["experiments"].append(run_experiment("E1 held-out simulator scenario", [s for s in sim if s.origin != holdout] + all_worlds, sel(sim, holdout), 0.3, True))
    report["experiments"].append(run_experiment("E2 unseen generated network", sim + worlds[1] + worlds[2] + worlds[3], worlds[4], 0.5, False))
    report["experiments"].append(run_experiment("E3a zero-shot: simulator-only model on a new world", sim, worlds[4], 0.5, False))
    report["experiments"].append(run_experiment("E3b zero-shot: worlds-only model on the simulator", all_worlds, sel(sim, holdout), 0.3, True))

    everything = sim + all_worlds
    # E4 needs per-series cut points; keys repeat across origins, so give each series a unique key for this experiment
    uniq = [SeriesData(s.key + "@" + s.origin, s.minutes0, s.y, s.mult, s.tick_minutes, s.origin, s.meta) for s in everything]
    until = {u.key: int(u.n * 0.75) for u in uniq}
    t = time.time()
    m4 = DemandModel.fit(uniq, stride=4, until=until)
    e4 = backtest(m4, uniq, start=until, stride=4)
    e4.update({"name": "E4 future window (train first 75%, test last 25%)", "train_series": len(uniq), "train_rows": m4.meta["rows"], "test_series": len(uniq), "fit_seconds": round(time.time() - t, 1)})
    report["experiments"].append(e4)
    print("E4 model WAPE", e4["wape"]["model"], "naive", e4["wape"]["naive"], flush=True)

    # what did the model learn? permutation importance on the future window
    hs = np.array([1, 4, 8, 16, 32])
    xs, ys = [], []
    from app.ml.features import rows_at
    rng = np.random.default_rng(0)
    for u in rng.choice(len(uniq), size=min(40, len(uniq)), replace=False):
        s = uniq[u]
        for i in range(until[s.key], s.n - 33, 12):
            X, scale = rows_at(s, i, hs)
            xs.append(X)
            ys.append(s.y[i + hs] / scale)
    Xt, yt = np.vstack(xs), np.concatenate(ys)
    imp = permutation_importance(m4.models[0.5], Xt[:4000], yt[:4000], n_repeats=3, random_state=0, scoring="neg_mean_absolute_error")
    order = np.argsort(-imp.importances_mean)
    report["importance"] = [{"feature": FEATURES[k], "importance": round(float(imp.importances_mean[k]), 4)} for k in order[:10]]

    # the champion: trained on everything
    t = time.time()
    champion = DemandModel.fit(everything, stride=4, meta={"source": "offline", "reason": "initial training on simulator + generated worlds"})
    version = f"gbm-{time.strftime('%Y%m%d')}-base"
    champion.meta["version"] = version
    metrics = {"E4_future_window": e4["wape"], "E1_heldout_scenario": report["experiments"][0]["wape"], "coverage_80": e4["coverage_80"]}
    manager.save_bundled(champion, version, metrics)
    report["champion"] = {"version": version, "rows": champion.meta["rows"], "series": len(everything), "ticks": int(sum(s.n for s in everything)),
                          "origins": sorted({s.origin for s in everything}), "fit_seconds": round(time.time() - t, 1), "artifact_kb": len(champion.dumps()) // 1024,
                          "algorithm": champion.meta["algorithm"]}
    report["generated"] = time.time()
    (DOCS / "model_report.json").write_text(json.dumps(report), encoding="utf-8")
    write_markdown(report)
    print("champion saved:", version, report["champion"])


def write_markdown(r: dict) -> None:
    L = ["# Demand model: training and evaluation\n",
         "FuelGrid's forecaster is a **trained model**, not a hand-written formula: gradient-boosted quantile regression (scikit-learn), "
         "pooled across every station and fuel, giving a forecast and an 80% prediction band. It never reads the simulator's published "
         "demand profile; it learns time-of-day, day-of-week, momentum, and the effect of announced events from data.\n",
         f"**Champion `{r['champion']['version']}`**: {r['champion']['rows']:,} training rows from {r['champion']['series']} series "
         f"({r['champion']['ticks']:,} observations) across {', '.join(r['champion']['origins'])}; model file {r['champion']['artifact_kb']} KB.\n",
         "Error metric: **WAPE** = total absolute error / total actual demand (lower is better). Horizon *h* is ticks ahead. "
         "Coverage is the share of outcomes inside the 10-90% band (ideal: 80%).\n"]
    for e in r["experiments"]:
        cols = ["model", "naive", "yesterday", "average"] + (["expert profile"] if "expert profile" in e["wape"] else [])
        L += [f"\n## {e['name']}\n", f"Trained on {e['train_series']} series ({e['train_rows']:,} rows); tested on {e['test_series']} series, walk-forward.\n",
              "| Horizon | " + " | ".join(cols) + " | Coverage (80%) |", "|---|" + "---:|" * (len(cols) + 1)]
        for h in e["horizons"]:
            L.append(f"| {h} | " + " | ".join(f"{e['wape'][c][str(h)]:.1%}" for c in cols) + f" | {e['coverage_80'][str(h)]:.0%} |")
    L += ["\n## What the model relies on (permutation importance)\n", "| Feature | Importance |", "|---|---:|"]
    L += [f"| {x['feature']} | {x['importance']:.4f} |" for x in r["importance"]]
    (DOCS / "MODEL.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
