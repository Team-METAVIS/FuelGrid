"""Model lifecycle: load -> forecast -> adapt online -> retrain -> gate -> promote / roll back.

How the platform stays correct when the world keeps changing:

  1. Online adaptation (seconds). Every tick the model's one-step forecast is compared with what happened. A smoothed
     correction factor per station and fuel follows a level shift immediately, before any retraining. Demand persistently
     above the model's own 90th percentile is flagged as an unexplained surge.
  2. Retraining (minutes). On a schedule, or when forecast error drifts, a challenger model is trained on the history the
     platform has collected (plus a small base corpus while live history is short).
  3. Champion / challenger gate. The challenger and the current champion are both evaluated on the most recent window,
     which the challenger did not train on. Only a clear win is promoted, and the previous champion stays in the registry so
     the operator can roll back with one click.
  4. Cold start. A series with too little history uses a plain moving average until the model has enough to work with."""
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.core import metrics as m
from app.core.logging import get_logger
from app.intelligence.types import Forecast
from app.ml import datasets as D
from app.ml.backtest import backtest, headline
from app.ml.covariates import announced_multiplier
from app.ml.features import MIN_HISTORY, SeriesData, dense
from app.ml.model import DemandModel

log = get_logger("ml")
MODEL_DIR = Path(__file__).resolve().parents[2] / "ml_models"
PROMOTE_MARGIN = 0.97  # challenger must reduce error by at least 3% to replace the champion
Z80 = 1.2816


def series_from_store(store, snap, origin: str = "live", min_points: int = 2) -> list[SeriesData]:
    """Turn everything the platform has observed into training series (with announced events as covariates)."""
    out = []
    for (sid, fuel), d in store.demand.items():
        st = snap.stations.get(sid)
        if not d or len(d) < min_points:
            continue
        ticks = sorted(d)
        region = st.region_id if st else ""
        mult = [announced_multiplier(snap.events, sid, region, t) for t in ticks]
        first = d[ticks[0]][3]
        minutes0 = int((first - datetime(1970, 1, 1)).total_seconds() // 60)
        s = dense(ticks, [d[t][0] for t in ticks], mult, minutes0, snap.tick_minutes, f"{sid}/{fuel}", origin)
        if s:
            out.append(s)
    return out


class ModelManager:
    def __init__(self) -> None:
        self.champion: DemandModel | None = None
        self.version: str | None = None
        self.registry: list[dict] = []
        self.bias: dict[str, float] = {}
        self.over: dict[str, int] = {}
        self.training = False
        self.last_train_tick = -10**9
        self.last_result: dict | None = None
        self.repo = None
        self.bus = None
        self.audit = None  # callable(kind, message, severity)

    # ------------------------------------------------------------------ loading and registry
    async def load(self, repo=None) -> str | None:
        self.repo = repo
        if repo is not None and repo.up:
            try:
                rows = await repo.fetch("select version, status, source, meta, metrics, created_at from fg_models order by created_at desc limit 30")
                self.registry = [{**r, "created_at": str(r["created_at"])} for r in rows]
                champ = next((r for r in rows if r["status"] == "champion"), None)
                if champ:
                    blob = await repo.fetch("select artifact from fg_models where version=:v", {"v": champ["version"]})
                    self._set_champion(DemandModel.loads(bytes(blob[0]["artifact"])), champ["version"])
                    return self.version
            except Exception as e:
                log.warning("model_load_from_db_failed", error=str(e)[:120])
        p = MODEL_DIR / "champion.joblib"
        if p.exists():
            meta = json.loads((MODEL_DIR / "champion.json").read_text(encoding="utf-8")) if (MODEL_DIR / "champion.json").exists() else {}
            self._set_champion(DemandModel.loads(p.read_bytes()), meta.get("version", "bundled"))
            if not any(r["version"] == self.version for r in self.registry):
                self.registry.insert(0, {"version": self.version, "status": "champion", "source": "bundled", "meta": self.champion.meta, "metrics": meta.get("metrics", {}), "created_at": self.champion.meta.get("trained_at", "")})
            return self.version
        return None

    def _set_champion(self, model: DemandModel, version: str) -> None:
        self.champion, self.version = model, version
        self.bias.clear()
        self.over.clear()
        m.MODEL_INFO.info({"version": version})

    def _persist(self, version: str, model: DemandModel, status: str, source: str, metrics: dict) -> None:
        if self.repo is not None:
            self.repo.enqueue(
                "insert into fg_models (version, status, source, meta, metrics, artifact) values (:v, :s, :src, cast(:meta as jsonb), cast(:met as jsonb), :a) on conflict (version) do nothing",
                {"v": version, "s": status, "src": source, "meta": json.dumps(model.meta, default=str), "met": json.dumps(metrics, default=str), "a": model.dumps()})

    def _promote_db(self, version: str) -> None:
        if self.repo is not None:
            self.repo.enqueue("update fg_models set status = case when version = :v then 'champion' when status = 'champion' then 'retired' else status end where status = 'champion' or version = :v", {"v": version})

    def save_bundled(self, model: DemandModel, version: str, metrics: dict) -> None:
        MODEL_DIR.mkdir(exist_ok=True)
        (MODEL_DIR / "champion.joblib").write_bytes(model.dumps())
        (MODEL_DIR / "champion.json").write_text(json.dumps({"version": version, "meta": model.meta, "metrics": metrics}, default=str), encoding="utf-8")

    # ------------------------------------------------------------------ inference
    def forecast_batch(self, store, snap, horizon: int, adapt: bool = True) -> dict[tuple[str, str], Forecast] | None:
        """Forecasts for every station and fuel that has enough history; the caller falls back for the rest."""
        if self.champion is None:
            return None
        jobs, keys, offs = [], [], []
        for sid, st in snap.stations.items():
            for fuel in snap.fuels:
                if fuel not in st.capacity:
                    continue
                d = store.demand.get((sid, fuel))
                if not d or len(d) < MIN_HISTORY:
                    continue
                last_t = max(d)
                off = max(0, snap.tick - last_t)
                s = series_from_store_one(store, snap, sid, fuel)
                if s is None or s.n < MIN_HISTORY:
                    continue
                need = horizon + off
                fm = np.array([announced_multiplier(snap.events, sid, st.region_id, last_t + h) for h in range(1, need + 1)])
                jobs.append((s, s.n - 1, fm))
                keys.append((sid, fuel))
                offs.append(off)
        if not jobs:
            return {}
        outs = self.champion.forecast_many_var(jobs, horizon, offs)
        result = {}
        for (sid, fuel), (p50, p10, p90, _scale), s in zip(keys, outs, [j[0] for j in jobs], strict=True):
            b = self.bias.get(f"{sid}/{fuel}", 1.0) if adapt else 1.0
            mid, lo, hi = p50 * b, p10 * b, p90 * b
            rel = float(np.mean((hi - lo) / (2 * Z80) / np.maximum(mid, 1e-6)))
            sigma = max(0.05, min(rel, 0.8))
            conf = max(0.0, min(1.0, 1 - 2.0 * sigma)) * min(1.0, s.n / 48)
            over = self.over.get(f"{sid}/{fuel}", 0)
            f = Forecast(sid, fuel, [float(x) for x in mid], sigma, round(conf, 3), float(b), f"learned-{self.version}",
                         anomaly=over >= 3, z=float(over), raw1=float(p50[0]), hi1=float(p90[0]), lo=[float(x) for x in lo], hi=[float(x) for x in hi])
            result[(sid, fuel)] = f
        return result

    def observe(self, sid: str, fuel: str, raw: float, hi: float | None, actual: float, adapt: bool = True) -> None:
        """Compare the model's own one-step forecast with reality: adapt the correction, watch for surges."""
        key = f"{sid}/{fuel}"
        if raw > 1e-6 and adapt:
            ratio = float(np.clip(actual / raw, 0.4, 2.5))
            self.bias[key] = float(np.clip(0.88 * self.bias.get(key, 1.0) + 0.12 * ratio, 0.4, 2.5))
        self.over[key] = self.over.get(key, 0) + 1 if (hi is not None and actual > hi * 1.05) else 0

    # ------------------------------------------------------------------ retraining
    def due(self, tick: int, cfg, drift: bool) -> str | None:
        if self.training or not cfg.auto_retrain:
            return None
        since = tick - self.last_train_tick
        if drift and since >= cfg.retrain_cooldown_ticks:
            return "drift detected"
        if since >= cfg.retrain_every_ticks:
            return "scheduled"
        return None

    async def retrain(self, store, snap, reason: str = "manual", force: bool = False) -> dict:
        if self.training:
            return {"status": "busy"}
        self.training = True
        self.last_train_tick = snap.tick
        t0 = time.time()
        try:
            live = series_from_store(store, snap, "live")
            live = [s for s in live if s.n >= 60]
            if len(live) < 4 and not force:
                res = {"status": "skipped", "reason": f"not enough live history yet ({sum(s.n for s in live)} points)"}
            else:
                res = await asyncio.to_thread(self._retrain_sync, live, reason)
        except Exception as e:  # a failed retrain must never disturb operations
            log.exception("retrain_failed")
            res = {"status": "error", "reason": f"{type(e).__name__}: {str(e)[:120]}"}
        finally:
            self.training = False
        res["seconds"] = round(time.time() - t0, 1)
        res["reason"] = res.get("reason") or reason
        self.last_result = res
        m.RETRAINS.labels(res["status"]).inc()
        if self.audit:
            self.audit("model", f"MODEL RETRAIN ({reason}): {res['status']} - {res.get('message', res.get('reason', ''))}", "info" if res["status"] != "error" else "warn")
        if self.bus:
            self.bus.publish("model", status=res["status"], version=res.get("version"), message=res.get("message"))
        return res

    def _base_corpus(self) -> list[SeriesData]:
        out: list[SeriesData] = []
        for name in ("sim_all", "world_1", "world_2", "world_3", "world_4"):
            if D.exists(name):
                out += D.load(name)
        return out

    def _retrain_sync(self, live: list[SeriesData], reason: str) -> dict:
        base = self._base_corpus() if sum(s.n for s in live) < 400 * max(1, len(live)) else []
        cut = {s.key: int(s.n * 0.75) for s in live}
        challenger = DemandModel.fit(live + base, stride=4, until={**cut}, meta={"source": "online", "reason": reason})
        hold = backtest(challenger, live, start=cut, stride=3)
        chall_score = headline(hold)
        champ_score = None
        if self.champion is not None:
            champ_score = headline(backtest(self.champion, live, start=cut, stride=3))
        promote = champ_score is None or chall_score <= champ_score * PROMOTE_MARGIN
        base_msg = f"challenger error {chall_score:.1%}" + (f" vs champion {champ_score:.1%}" if champ_score is not None else "")
        if not promote:
            return {"status": "rejected", "message": f"{base_msg}: not a clear win, champion kept", "challenger_wape": chall_score, "champion_wape": champ_score}
        final = DemandModel.fit(live + base, stride=4, meta={"source": "online", "reason": reason})
        version = f"gbm-{datetime.now(UTC):%Y%m%d-%H%M%S}"
        final.meta["version"] = version
        metrics = {"holdout": hold, "challenger_wape": chall_score, "champion_wape": champ_score}
        self._persist(version, final, "champion", "online", metrics)
        self._promote_db(version)
        self.registry.insert(0, {"version": version, "status": "champion", "source": "online", "meta": final.meta, "metrics": metrics, "created_at": final.meta["trained_at"]})
        for r in self.registry[1:]:
            if r["status"] == "champion":
                r["status"] = "retired"
        self._set_champion(final, version)
        return {"status": "promoted", "version": version, "message": f"{version} promoted: {base_msg}", "challenger_wape": chall_score, "champion_wape": champ_score}

    async def activate(self, version: str) -> bool:
        """Roll back (or forward) to a registered model."""
        if self.repo is None or not self.repo.up:
            return False
        rows = await self.repo.fetch("select artifact from fg_models where version=:v", {"v": version})
        if not rows:
            return False
        self._set_champion(DemandModel.loads(bytes(rows[0]["artifact"])), version)
        self._promote_db(version)
        for r in self.registry:
            r["status"] = "champion" if r["version"] == version else ("retired" if r["status"] == "champion" else r["status"])
        return True

    def info(self) -> dict:
        return {"active": self.version, "has_model": self.champion is not None, "training": self.training, "last_result": self.last_result,
                "registry": self.registry[:12], "bias": {k: round(v, 3) for k, v in list(self.bias.items())[:40]},
                "meta": self.champion.meta if self.champion else None}


def series_from_store_one(store, snap, sid: str, fuel: str) -> SeriesData | None:
    d = store.demand.get((sid, fuel))
    if not d:
        return None
    st = snap.stations.get(sid)
    ticks = sorted(d)[-600:]  # the model looks back at most a few days; bound the work per cycle
    mult = [announced_multiplier(snap.events, sid, st.region_id if st else "", t) for t in ticks]
    minutes0 = int((d[ticks[0]][3] - datetime(1970, 1, 1)).total_seconds() // 60)
    return dense(ticks, [d[t][0] for t in ticks], mult, minutes0, snap.tick_minutes, f"{sid}/{fuel}", "live")


manager = ModelManager()
