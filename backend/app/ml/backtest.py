"""Honest offline evaluation.

Walk-forward on data the model never saw: for many anchor times in the held-out window, forecast several horizons ahead and
compare with what actually happened. Reported against simple baselines any operator could use, so "is it any good?" has a
concrete answer:

    naive        tomorrow looks like right now
    yesterday    same time yesterday
    average      mean of the last 8 ticks
    (optional)   extra baselines, e.g. an expert's hand-set profile

Metrics: WAPE (sum of absolute errors / sum of actual demand, the fairest single number), interval coverage (the 10-90%
band should contain about 80% of outcomes) and pinball loss for the three quantiles."""
from collections.abc import Callable

import numpy as np

from app.ml.features import MIN_HISTORY, SeriesData, rows_at
from app.ml.model import QUANTILES, DemandModel

HORIZONS = (1, 4, 8, 16, 32)


def _pinball(y: np.ndarray, p: np.ndarray, q: float) -> float:
    d = y - p
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def backtest(model: DemandModel | None, series: list[SeriesData], from_frac: float = 0.75, horizons: tuple[int, ...] = HORIZONS, stride: int = 5,
             extra: dict[str, Callable[[SeriesData, int, int], float]] | None = None, start: dict[str, int] | None = None) -> dict:
    """`start` overrides the first evaluated index per series (used to evaluate exactly the window a challenger did not train on)."""
    errs: dict[str, dict[int, list]] = {}
    ys: dict[int, list[float]] = {h: [] for h in horizons}
    cover: dict[int, list[float]] = {h: [] for h in horizons}
    pin: dict[int, list[float]] = {h: [] for h in horizons}
    base = {"naive": lambda s, i, h: s.y[i], "yesterday": None, "average": lambda s, i, h: float(np.mean(s.y[max(0, i - 7):i + 1]))}
    names = (["model"] if model else []) + ["naive", "yesterday", "average"] + list(extra or {})
    for n in names:
        errs[n] = {h: [] for h in horizons}
    for s in series:
        tpd = max(1, round(1440 / s.tick_minutes))
        first = max(MIN_HISTORY, (start or {}).get(s.key, int(s.n * from_frac)))
        for i in range(first, s.n - 1, stride):
            valid = [h for h in horizons if i + h < s.n]
            if not valid:
                continue
            vh = np.array(valid)
            actual = s.y[i + vh]
            if model:
                X, scale = rows_at(s, i, vh)
                q = model.predict_rows(X) * scale
            for k, h in enumerate(valid):
                a = float(actual[k])
                ys[h].append(a)
                if model:
                    errs["model"][h].append(abs(a - q[k, 1]))
                    cover[h].append(float(q[k, 0] <= a <= q[k, 2]))
                    pin[h].append(sum(_pinball(np.array([a]), np.array([q[k, m]]), qq) for m, qq in enumerate(QUANTILES)) / 3)
                errs["naive"][h].append(abs(a - base["naive"](s, i, h)))
                back = -(-h // tpd) * tpd
                errs["yesterday"][h].append(abs(a - (s.y[i + h - back] if i + h - back >= 0 else s.y[i])))
                errs["average"][h].append(abs(a - base["average"](s, i, h)))
                for nm, fn in (extra or {}).items():
                    errs[nm][h].append(abs(a - fn(s, i, h)))
    out = {"horizons": list(horizons), "samples": {str(h): len(ys[h]) for h in horizons}, "wape": {}, "coverage_80": {}, "pinball": {}}
    for n in names:
        out["wape"][n] = {str(h): round(float(np.sum(errs[n][h]) / max(np.sum(ys[h]), 1e-9)), 4) for h in horizons if ys[h]}
    if model:
        out["coverage_80"] = {str(h): round(float(np.mean(cover[h])), 3) for h in horizons if cover[h]}
        out["pinball"] = {str(h): round(float(np.mean(pin[h])), 3) for h in horizons if pin[h]}
    return out


def headline(result: dict) -> float:
    """One number for champion/challenger comparison: mean WAPE of the model over the planning-relevant horizons."""
    w = result["wape"]["model"]
    vals = [w[str(h)] for h in (1, 4, 8, 16) if str(h) in w]
    return float(np.mean(vals)) if vals else float("inf")
