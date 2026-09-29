"""The demand model: gradient-boosted quantile regression, pooled across every station and fuel.

Three models (10th, 50th and 90th percentile) give a forecast *and* an honest uncertainty band, which the optimizer turns
into a safety buffer. Trained with scikit-learn's histogram gradient boosting; inference for the whole network is three
vectorised calls."""
import io
from datetime import UTC, datetime

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from app.ml.features import FEATURES, SeriesData, rows_at, training_matrix

QUANTILES = (0.1, 0.5, 0.9)
HORIZON = 32


class DemandModel:
    def __init__(self, models: dict[float, HistGradientBoostingRegressor], meta: dict):
        self.models, self.meta = models, meta

    # ------------------------------------------------------------------ training
    @classmethod
    def fit(cls, series: list[SeriesData], horizon: int = HORIZON, stride: int = 4, until: dict[str, int] | None = None,
            seed: int = 0, max_iter: int = 150, max_rows: int = 250_000, meta: dict | None = None) -> "DemandModel":
        # h is a model feature, so training on a spread of horizons is enough: the model interpolates between them
        horizons = np.array(sorted({h for h in (1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 28, 32) if h <= horizon} | {horizon}))
        X, y = training_matrix(series, horizons, stride=stride, until=until)
        if len(y) > max_rows:  # bound training time so retraining stays an online-friendly operation
            keep = np.random.default_rng(seed).choice(len(y), size=max_rows, replace=False)
            X, y = X[keep], y[keep]
        # a feature can be entirely unavailable (e.g. 'same time last week' when only 6 days of history exist): neutralise it
        X[:, np.isnan(X).all(axis=0)] = 0.0
        if len(y) < 500:
            raise ValueError(f"not enough training data ({len(y)} rows); need history from more stations or a longer run")
        models = {}
        for q in QUANTILES:
            m = HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=max_iter, learning_rate=0.08, max_leaf_nodes=24,
                                              min_samples_leaf=60, l2_regularization=1.0, early_stopping=False, random_state=seed)
            models[q] = m.fit(X, y)
        info = {
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"), "rows": int(len(y)), "series": len(series),
            "ticks": int(sum((until or {}).get(s.key, s.n) if until else s.n for s in series)),
            "origins": sorted({s.origin for s in series if s.origin}), "features": FEATURES, "horizon": horizon, "stride": stride,
            "algorithm": "HistGradientBoosting quantile x3 (p10, p50, p90), pooled", **(meta or {}),
        }
        return cls(models, info)

    # ------------------------------------------------------------------ inference
    def predict_rows(self, X: np.ndarray) -> np.ndarray:
        """(n, 3) normalised quantiles, non-crossing and non-negative."""
        out = np.column_stack([self.models[q].predict(X) for q in QUANTILES])
        return np.clip(np.sort(out, axis=1), 0.0, None)

    def forecast_many(self, jobs: list[tuple[SeriesData, int, np.ndarray | None]], horizon: int) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, float]]:
        """For every (series, anchor index, announced future multipliers) return (p50, p10, p90, scale) in real units."""
        hs = np.arange(1, horizon + 1)
        blocks, scales = [], []
        for s, i, fm in jobs:
            X, scale = rows_at(s, i, hs, fm)
            blocks.append(X)
            scales.append(scale)
        q = self.predict_rows(np.vstack(blocks)).reshape(len(jobs), horizon, 3)
        return [(q[k, :, 1] * scales[k], q[k, :, 0] * scales[k], q[k, :, 2] * scales[k], scales[k]) for k in range(len(jobs))]

    def forecast_many_var(self, jobs: list[tuple[SeriesData, int, np.ndarray | None]], horizon: int, offsets: list[int]) -> list[tuple[np.ndarray, np.ndarray, np.ndarray, float]]:
        """Like forecast_many, but job k is forecast `offsets[k]` steps further out and those first steps are dropped.
        (Used when the newest observation is a few ticks behind the clock.) One batched prediction for all jobs."""
        blocks, scales, lens = [], [], []
        for (s, i, fm), off in zip(jobs, offsets, strict=True):
            hs = np.arange(1, horizon + off + 1)
            X, scale = rows_at(s, i, hs, fm)
            blocks.append(X)
            scales.append(scale)
            lens.append(len(hs))
        q = self.predict_rows(np.vstack(blocks))
        out, at = [], 0
        for k, n in enumerate(lens):
            blk = q[at:at + n][offsets[k]:] * scales[k]
            out.append((blk[:, 1], blk[:, 0], blk[:, 2], scales[k]))
            at += n
        return out

    # ------------------------------------------------------------------ persistence
    def dumps(self) -> bytes:
        buf = io.BytesIO()
        joblib.dump({"models": self.models, "meta": self.meta}, buf, compress=3)
        return buf.getvalue()

    @classmethod
    def loads(cls, blob: bytes) -> "DemandModel":
        d = joblib.load(io.BytesIO(blob))
        return cls(d["models"], d["meta"])
