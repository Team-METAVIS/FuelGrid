"""Feature engineering for the demand model.

One pooled model serves every station and fuel. Demand is divided by a per-series scale (recent mean), so the model learns
*shapes and dynamics* (time of day, day of week, momentum, spikes) rather than memorising the size of any one station. That
is what lets it work on a network it has never seen and start giving sensible forecasts for a brand-new station after a
few observations. Nothing in here knows about the simulator: only the time series, the clock and (optionally) announced
demand multipliers."""
from dataclasses import dataclass, field

import numpy as np

FEATURES = [
    "hours_ahead", "hod_sin", "hod_cos", "dow_sin", "dow_cos", "weekend",
    "last", "mean4", "mean16", "mean_day", "lag_day", "lag_2day", "lag_week",
    "mult_target", "mult_now", "tick_minutes", "vol16", "level_ratio",
]
MIN_HISTORY = 24  # observations needed before the model forecasts a series (else: cold-start fallback)


@dataclass
class SeriesData:
    key: str                 # "station/fuel"
    minutes0: int            # minutes since epoch of the first observation
    y: np.ndarray            # demand per tick, contiguous (gaps interpolated)
    mult: np.ndarray         # announced demand multiplier per tick (1.0 when none)
    tick_minutes: int
    origin: str = ""         # provenance label ("sim:baseline", "world:7", "live")
    meta: dict = field(default_factory=dict)  # optional context (station profile, region) used only by baselines, never by the model

    @property
    def n(self) -> int:
        return len(self.y)

    def minutes(self, i: int | np.ndarray) -> int | np.ndarray:
        return self.minutes0 + i * self.tick_minutes


def dense(ticks: list[int], values: list[float], mult: list[float], minutes_at_first: int, tick_minutes: int, key: str, origin: str = "") -> SeriesData | None:
    """Turn (tick, value) pairs, possibly with gaps, into a contiguous series (gaps filled by linear interpolation)."""
    if len(ticks) < 2:
        return None
    t = np.asarray(ticks)
    lo, hi = int(t.min()), int(t.max())
    grid = np.arange(lo, hi + 1)
    y = np.interp(grid, t, np.asarray(values, dtype=float))
    m = np.interp(grid, t, np.asarray(mult, dtype=float))
    return SeriesData(key, minutes_at_first, y, m, tick_minutes, origin)


def _cyc(minutes: np.ndarray) -> tuple[np.ndarray, ...]:
    mod = minutes % 1440
    dow = ((minutes // 1440) + 3) % 7  # 1970-01-01 was a Thursday; Monday = 0
    a, b = 2 * np.pi * mod / 1440, 2 * np.pi * dow / 7
    return np.sin(a), np.cos(a), np.sin(b), np.cos(b), (dow >= 5).astype(float)


def _at(y: np.ndarray, idx: np.ndarray, limit: int) -> np.ndarray:
    """y[idx] where 0 <= idx <= limit, else NaN (gradient boosting handles missing values natively)."""
    out = np.full(idx.shape, np.nan)
    ok = (idx >= 0) & (idx <= limit)
    out[ok] = y[idx[ok]]
    return out


def rows_at(s: SeriesData, i: int, horizons: np.ndarray, future_mult: np.ndarray | None = None) -> tuple[np.ndarray, float]:
    """Feature rows for forecasting `horizons` steps ahead of anchor index `i` (the last observation used).
    Returns (X[len(horizons), F], scale)."""
    tpd = max(1, round(1440 / s.tick_minutes))
    lo = max(0, i - 4 * tpd + 1)
    scale = max(float(np.mean(s.y[lo:i + 1])), 1e-6)
    y = s.y / scale
    last = y[i]
    m4 = float(np.mean(y[max(0, i - 3):i + 1]))
    m16 = float(np.mean(y[max(0, i - 15):i + 1]))
    mday = float(np.mean(y[max(0, i - tpd + 1):i + 1]))
    vol = float(np.std(y[max(0, i - 15):i + 1]))
    ratio = m4 / max(mday, 1e-6)
    h = horizons.astype(int)
    j = i + h
    k1 = -(-h // tpd)  # ceil(h / tpd): the nearest whole number of days back that is already observed
    k7 = 7 * (-(-h // (7 * tpd)))
    lag_day = _at(y, j - k1 * tpd, i)
    lag_2day = _at(y, j - (k1 + 1) * tpd, i)
    lag_week = _at(y, j - k7 * tpd, i)
    sin_h, cos_h, sin_d, cos_d, wk = _cyc(s.minutes(j))
    if future_mult is not None:
        mt = np.asarray(future_mult, dtype=float)[h - 1]
    else:
        mt = np.where(j < s.n, s.mult[np.minimum(j, s.n - 1)], 1.0)
    now = s.mult[i]
    X = np.column_stack([
        h * s.tick_minutes / 60.0, sin_h, cos_h, sin_d, cos_d, wk,
        np.full(h.shape, last), np.full(h.shape, m4), np.full(h.shape, m16), np.full(h.shape, mday),
        lag_day, lag_2day, lag_week, mt, np.full(h.shape, now), np.full(h.shape, s.tick_minutes),
        np.full(h.shape, vol), np.full(h.shape, ratio),
    ])
    return X, scale


def training_matrix(series: list[SeriesData], horizons: np.ndarray, stride: int = 3, first: int = MIN_HISTORY, until: dict[str, int] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Supervised rows: for many anchors and every horizon, features at the anchor -> normalised demand at the target."""
    xs, ys = [], []
    for s in series:
        end = s.n if until is None else min(s.n, until.get(s.key, s.n))
        for i in range(first, end - 1, stride):
            hs = horizons[i + horizons < end]
            if len(hs) == 0:
                continue
            X, scale = rows_at(s, i, hs)
            xs.append(X)
            ys.append(s.y[i + hs] / scale)
    if not xs:
        return np.empty((0, len(FEATURES))), np.empty(0)
    return np.vstack(xs), np.concatenate(ys)
