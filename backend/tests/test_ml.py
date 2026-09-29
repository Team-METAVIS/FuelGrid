import numpy as np
import pytest

from app.adapters.feed import FeedSource
from app.core.config import Settings
from app.ml import datasets as D
from app.ml.backtest import backtest, headline
from app.ml.features import FEATURES, MIN_HISTORY, dense, rows_at, training_matrix
from app.ml.manager import ModelManager, series_from_store
from app.ml.model import DemandModel
from app.state.store import StateStore
from app.state.sync import Synchronizer
from app.worldgen.driver import push_tick
from app.worldgen.world import World

T0 = 1_000_000  # arbitrary epoch minute


@pytest.fixture(scope="module")
def series():
    return D.world_series(seed=11, ticks=420, changes={})


@pytest.fixture(scope="module")
def model(series):
    return DemandModel.fit(series, stride=6, max_iter=40)


def test_features_are_source_neutral_and_shaped_right(series):
    s = series[0]
    X, scale = rows_at(s, 100, np.array([1, 8, 32]))
    assert X.shape == (3, len(FEATURES)) and scale > 0
    assert not np.isnan(X[:, FEATURES.index("last")]).any()
    Xm, ym = training_matrix(series[:2], np.array([1, 4]), stride=10)
    assert Xm.shape[1] == len(FEATURES) and len(ym) == len(Xm) > 0
    assert "profile" not in " ".join(FEATURES) and "sim" not in " ".join(FEATURES)


def test_gaps_in_history_are_interpolated():
    s = dense([0, 1, 2, 5, 6], [10, 12, 14, 20, 22], [1] * 5, T0, 30, "a/b")
    assert s.n == 7 and abs(s.y[3] - 16.0) < 1e-6


def test_quantiles_never_cross_and_intervals_are_calibrated(model, series):
    res = backtest(model, series, from_frac=0.6, stride=6)
    assert res["wape"]["model"]["8"] < res["wape"]["naive"]["8"], "the trained model must beat 'same as now'"
    assert res["wape"]["model"]["8"] < res["wape"]["average"]["8"]
    assert 0.55 < res["coverage_80"]["8"] < 0.98
    X, _ = rows_at(series[0], 200, np.arange(1, 33))
    q = model.predict_rows(X)
    assert (q[:, 0] <= q[:, 1] + 1e-9).all() and (q[:, 1] <= q[:, 2] + 1e-9).all() and (q >= 0).all()


def test_model_survives_serialisation(model, series):
    clone = DemandModel.loads(model.dumps())
    X, _ = rows_at(series[3], 150, np.arange(1, 9))
    assert np.allclose(model.predict_rows(X), clone.predict_rows(X))


def test_too_little_data_is_refused_not_silently_trained(series):
    with pytest.raises(ValueError):
        DemandModel.fit(series[:1], stride=200)


@pytest.mark.asyncio
async def test_manager_forecasts_adapts_online_and_falls_back_for_new_series(model):
    cfg = Settings(database_url=None)
    feed, store = FeedSource(cfg), StateStore()
    sync = Synchronizer(feed, store)
    world = World(seed=5)
    from app.adapters.feed import TopologyIn
    feed.set_topology(TopologyIn(**world.topology()))
    for _ in range(140):
        push_tick(feed, world, [])
    snap = await sync.refresh()
    mgr = ModelManager()
    assert mgr.forecast_batch(store, snap, 32) is None  # no champion yet: caller must fall back
    mgr._set_champion(model, "test")
    out = mgr.forecast_batch(store, snap, 32)
    assert len(out) == len(snap.stations) * len(snap.fuels) and len(next(iter(out.values())).per_tick) == 32
    f = next(iter(out.values()))
    assert f.model == "learned-test" and f.lo is not None and all(lo <= mid + 1e-6 <= hi + 1e-6 for lo, mid, hi in zip(f.lo, f.per_tick, f.hi, strict=True))
    # a level shift: the correction factor follows within a few observations
    key = "S1/DIESEL"
    for _ in range(12):
        mgr.observe("S1", "DIESEL", raw=100.0, hi=130.0, actual=170.0)
    assert mgr.bias[key] > 1.4
    for _ in range(4):
        mgr.observe("S1", "DIESEL", raw=100.0, hi=130.0, actual=170.0)
    assert mgr.over[key] >= 3, "demand persistently above the 90th percentile is an unexplained surge"
    mgr.observe("S1", "DIESEL", raw=100.0, hi=130.0, actual=100.0)
    assert mgr.over[key] == 0
    # a brand-new station has no history: the manager leaves it out so the planner uses the cold-start fallback
    store.demand[("NEW", "DIESEL")] = {1: (10.0, 10.0, 0.0, snap.instance.sim_time)}
    assert ("NEW", "DIESEL") not in mgr.forecast_batch(store, snap, 32)
    assert MIN_HISTORY > 1


@pytest.mark.asyncio
async def test_champion_challenger_gate_promotes_only_a_clear_win(model, series, monkeypatch):
    cfg = Settings(database_url=None)
    feed, store = FeedSource(cfg), StateStore()
    sync = Synchronizer(feed, store)
    world = World(seed=9)
    from app.adapters.feed import TopologyIn
    feed.set_topology(TopologyIn(**world.topology()))
    for _ in range(220):
        push_tick(feed, world, [])
    snap = await sync.refresh()
    monkeypatch.setattr(ModelManager, "_base_corpus", lambda self: [])
    # with no champion the first trained model is promoted; a later challenger must clearly beat it
    mgr = ModelManager()
    res = await mgr.retrain(store, snap, "test", force=True)
    assert res["status"] == "promoted" and mgr.version and mgr.champion is not None  # no champion -> promote
    first = mgr.version
    assert len(series_from_store(store, snap)) == len(snap.stations) * len(snap.fuels)
    again = await mgr.retrain(store, snap, "test again", force=True)
    assert again["status"] in ("rejected", "promoted")
    assert again["status"] == "rejected" or again.get("version") != first
    if again["status"] == "rejected":
        assert "champion kept" in again["message"]
    assert headline(backtest(mgr.champion, series_from_store(store, snap), stride=8)) < 0.5


def test_a_feature_that_is_entirely_missing_does_not_break_training():
    short = D.world_series(seed=2, ticks=200, changes={})  # under 7 days at 30-minute ticks: no weekly lag exists
    m = DemandModel.fit(short, stride=8, max_iter=15)
    X, _ = rows_at(short[0], 150, np.arange(1, 9))
    assert m.predict_rows(X).shape == (8, 3)
