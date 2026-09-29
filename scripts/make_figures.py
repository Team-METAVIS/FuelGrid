"""Generate every statistical figure in the README from the real result files (nothing is drawn by hand).

    backend/.venv/Scripts/python scripts/make_figures.py

Inputs (all produced by the project's own tools):
  docs/benchmark_results.json    python -m app.scenarios.cli
  docs/model_report.json         python -m app.ml.train
  docs/adaptation_report.json    python -m app.ml.adapt
  docs/tuning_*.json             python -m app.scenarios.sweep
  loadtest/results/*_stats.csv   bash loadtest/run.sh
Output: docs/img/*.png"""
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS, OUT = ROOT / "docs", ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
INDIGO, SKY, AMBER, GREEN, SLATE, ROSE = "#4f46e5", "#0ea5e9", "#f59e0b", "#10b981", "#94a3b8", "#f43f5e"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e2e8f0", "grid.linewidth": 0.8, "axes.axisbelow": True, "figure.dpi": 130,
                     "axes.titleweight": "bold", "axes.titlesize": 11.5, "legend.frameon": False})


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(OUT / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", name)


def benchmark() -> None:
    d = load(DOCS / "benchmark_results.json")
    if not d:
        return
    rows = d["results"]
    scen = list(dict.fromkeys(r["scenario"] for r in rows))
    pol = {"none": ("Do nothing", SLATE), "rules": ("Simple rules", SKY), "optimizer": ("FuelGrid optimizer", INDIGO)}
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    w = 0.26
    for k, (p, (lab, col)) in enumerate(pol.items()):
        v = [next((r["service_level"] * 100 for r in rows if r["scenario"] == s and r["policy"] == p), np.nan) for s in scen]
        bars = ax.bar(np.arange(len(scen)) + (k - 1) * w, v, w, label=lab, color=col)
        for b, x in zip(bars, v, strict=True):
            if not np.isnan(x):
                ax.text(b.get_x() + b.get_width() / 2, x + 0.8, f"{x:.1f}", ha="center", fontsize=7.5, color="#334155")
    ax.set_xticks(np.arange(len(scen)), [s.replace("_", "\n") for s in scen], fontsize=8.5)
    ax.set_ylabel("Share of demand served (%)")
    ax.set_ylim(0, 108)
    ax.set_title("Decision quality on identical, replayed crises")
    ax.legend(ncol=3, loc="lower left")
    save(fig, "benchmark.png")


def model() -> None:
    r = load(DOCS / "model_report.json")
    if not r:
        return
    ex = r["experiments"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.9), sharey=True)
    pick = [e for e in ex if e["name"].startswith(("E1", "E2", "E4"))]
    style = {"model": ("Trained model", INDIGO, 2.6), "naive": ("Same as now", SLATE, 1.5), "yesterday": ("Same as yesterday", SKY, 1.5), "average": ("Moving average", AMBER, 1.5), "expert profile": ("Hand-set expert", GREEN, 1.5)}
    for ax, e in zip(axes, pick, strict=False):
        for k, (lab, col, lw) in style.items():
            if k in e["wape"]:
                ax.plot(e["horizons"], [e["wape"][k][str(h)] * 100 for h in e["horizons"]], marker="o", ms=4, lw=lw, color=col, label=lab)
        ax.set_title(e["name"], fontsize=9.5)
        ax.set_xlabel("Ticks ahead")
    axes[0].set_ylabel("Forecast error, WAPE (%)  lower is better")
    axes[0].legend(fontsize=8)
    save(fig, "forecast_error.png")

    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for i, e in enumerate(ex):
        ax.plot(e["horizons"], [e["coverage_80"][str(h)] * 100 for h in e["horizons"]], marker="o", ms=4, lw=1.6, label=e["name"].split(" ", 1)[0] + " " + e["name"].split(" ", 1)[1][:34])
    ax.axhline(80, color=ROSE, ls="--", lw=1.2)
    ax.text(e["horizons"][-1], 80.8, "ideal 80%", color=ROSE, ha="right", fontsize=8)
    ax.set_ylim(60, 100)
    ax.set_xlabel("Ticks ahead")
    ax.set_ylabel("Outcomes inside the 10-90% band (%)")
    ax.set_title("Uncertainty is honest: interval calibration")
    ax.legend(fontsize=7, loc="lower right")
    save(fig, "calibration.png")

    imp = r.get("importance", [])[:8][::-1]
    if imp:
        fig, ax = plt.subplots(figsize=(6.2, 3.4))
        ax.barh([x["feature"].replace("_", " ") for x in imp], [x["importance"] for x in imp], color=INDIGO)
        ax.set_xlabel("Permutation importance (error increase when scrambled)")
        ax.set_title("What the trained model relies on")
        ax.grid(axis="y", visible=False)
        save(fig, "importance.png")


def adaptation() -> None:
    r = load(DOCS / "adaptation_report.json")
    if not r:
        return
    cols = [AMBER, SLATE, SKY, GREEN, INDIGO]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.2))
    for ax, key, lab in ((axes[0], "mape", "1-step forecast error (%)"), (axes[1], "service_level", "Service level (%)")):
        for j, res in enumerate(r["results"]):
            xs = [s["tick"] for s in res["series"] if s[key] is not None]
            ys = [s[key] * 100 for s in res["series"] if s[key] is not None]
            ax.plot(xs, ys, color=cols[j], lw=2.6 if j >= 3 else 1.4, label=res["name"])
        for t, k in r["schedule"].items():
            ax.axvline(int(t), color=ROSE, ls=":", lw=1)
            ax.text(int(t) + 3, ax.get_ylim()[1] * 0.98, k.replace("_", " "), rotation=90, va="top", fontsize=7, color=ROSE)
        ax.set_xlabel("Ticks since go-live")
        ax.set_ylabel(lab)
    axes[1].set_ylim(60, 100.5)
    axes[0].legend(fontsize=7.5, loc="upper left")
    fig.suptitle("Coping with a changing world: same network, same surprises, five ways of forecasting", fontsize=11.5, fontweight="bold")
    save(fig, "adaptation.png")


def tuning() -> None:
    a, b = load(DOCS / "tuning_results.json"), load(DOCS / "tuning_combos_results.json")
    if not a:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    for ax, d, ttl in ((axes[0], a, f"One setting at a time ({a['ticks']} ticks)"), (axes[1], b, f"Combinations ({b['ticks']} ticks)" if b else "")):
        if not d:
            ax.axis("off")
            continue
        scs = list(d["rows"][0]["per"])
        w = 0.8 / len(scs)
        for k, sc in enumerate(scs):
            ax.bar(np.arange(len(d["rows"])) + k * w, [r["per"][sc]["service_level"] * 100 for r in d["rows"]], w, label=sc.replace("_", " "), color=[INDIGO, SKY][k % 2])
        ax.set_xticks(np.arange(len(d["rows"])) + w * (len(scs) - 1) / 2, [r["label"].split("(")[0].strip().replace(" ", "\n", 1) for r in d["rows"]], fontsize=7)
        lo = min(r["per"][sc]["service_level"] for r in d["rows"] for sc in scs) * 100
        ax.set_ylim(max(0, lo - 3), 101)
        ax.set_ylabel("Service level (%)")
        ax.set_title(ttl)
        ax.legend(fontsize=8)
    save(fig, "tuning.png")


def load_test() -> None:
    def rd(name):
        p = ROOT / "loadtest" / "results" / f"{name}_stats.csv"
        return {r["Name"]: r for r in csv.DictReader(p.open(encoding="utf-8"))} if p.exists() else None
    n, s = rd("normal"), rd("stress")
    if not n:
        return
    names = [k for k in n if k != "Aggregated"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.1))
    x = np.arange(len(names))
    for ax, d, ttl in ((axes[0], n, "50 concurrent users"), (axes[1], s, "250 concurrent users (stress)")):
        if not d:
            ax.axis("off")
            continue
        for k, (col, lab) in enumerate((("50%", "p50"), ("95%", "p95"), ("99%", "p99"))):
            ax.bar(x + (k - 1) * 0.27, [float(d[nm][col]) for nm in names if nm in d], 0.27, label=lab, color=[GREEN, AMBER, ROSE][k])
        agg = d["Aggregated"]
        ax.set_title(f"{ttl}: {float(agg['Requests/s']):.0f} req/s, {int(agg['Failure Count'])} failures of {int(agg['Request Count']):,}")
        ax.set_xticks(x, [nm.replace("GET ", "").replace("POST ", "").replace(" (full decision path)", "\n(decision)") for nm in names], rotation=35, ha="right", fontsize=7.5)
        ax.set_ylabel("Response time (ms)")
        ax.legend(fontsize=8)
    save(fig, "load_test.png")


if __name__ == "__main__":
    for f in (benchmark, model, adaptation, tuning, load_test):
        f()
