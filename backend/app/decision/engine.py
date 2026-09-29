"""Decision engine: sync-triggered cycle  plan -> review gate -> execute -> audit  (Observe..Recover loop)."""
import asyncio
import dataclasses
import time
from collections import deque

from app.core import metrics as m
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.repo import Repo
from app.intelligence import planner
from app.intelligence.memory import IncidentMemory, signature
from app.intelligence.policies.common import precheck
from app.intelligence.types import Plan, Recommendation
from app.simulator import models as M
from app.simulator.client import SimulatorClient
from app.simulator.errors import AllocationRejected, SimulatorError, SimulatorUnavailable
from app.state.store import Snapshot, StateStore

log = get_logger("decision")


@dataclasses.dataclass
class Decision:
    id: int
    rec: Recommendation
    status: str = "PROPOSED"  # PROPOSED APPROVED REJECTED EXECUTED FAILED EXPIRED
    actor: str = "system"
    key: str | None = None
    sim_allocation_id: int | None = None
    result: str | None = None
    attempts: int = 0
    created_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self.rec)
        d.update(id=self.id, status=self.status, actor=self.actor, key=self.key,
                 sim_allocation_id=self.sim_allocation_id, result=self.result, created_at=self.created_at)
        return d


class DecisionEngine:
    def __init__(self, cfg: Settings, store: StateStore, client: SimulatorClient, repo: Repo, run_id: str):
        self.cfg, self.store, self.client, self.repo, self.run_id = cfg, store, client, repo, run_id
        self.decisions: dict[int, Decision] = {}
        self.history: deque[int] = deque(maxlen=1000)
        self.plan: Plan | None = None
        self.incidents: dict[str, dict] = {}
        self.last_cycle_tick = -999
        self.cycle_lock = asyncio.Lock()
        self._seq = 0
        self.pred: dict[tuple[str, str, int], float] = {}
        self.ape: deque[float] = deque(maxlen=300)
        self.last_cycle_ms = 0.0
        self.timeline: deque[dict] = deque(maxlen=600)
        self.fallbacks_in_row = 0
        self.memory = IncidentMemory(repo, run_id)
        self._tasks: set[asyncio.Task] = set()
        self.refresh = None  # set by the runtime: async callable returning a fresh Snapshot
        self._inflight: asyncio.Task | None = None
        self.version = 0  # bumped on every decision change; the UI stream watches it
        self.bench = False  # benchmark runner drives cycles itself
        self.paused = False  # operator kill-switch for automatic execution + planning

    def reset(self):
        """Forget world-specific state (called when the simulator is reset)."""
        self.decisions.clear()
        self.history.clear()
        self.pred.clear()
        self.ape.clear()
        self.timeline.clear()
        self.incidents = {}
        self.plan = None
        self.last_cycle_tick = -999
        self.repo.audit(self.run_id, "scenario", "Simulator reset detected; cached state cleared", "warn")

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    # ------------------------------------------------------------------ entry point
    async def on_snapshot(self, snap: Snapshot):
        self._score_forecasts()
        self._record_timeline(snap)
        self._emit("snapshot", tick=snap.tick, stale=snap.stale)
        if self.bench:
            return
        if self.paused or snap.tick - self.last_cycle_tick < self.cfg.decision_every_ticks and snap.tick >= self.last_cycle_tick:
            await self._retry_approved(snap)
            return
        await self.cycle(snap)

    async def cycle_coalesced(self) -> Plan | None:
        """Run a cycle, or join the one already running. A stampede of 'decide now' requests costs one cycle."""
        task = self._inflight
        if task is None or task.done():
            task = self._inflight = asyncio.create_task(self.cycle())
        return await asyncio.shield(task)

    async def cycle(self, snap: Snapshot | None = None, force_policy: str | None = None) -> Plan | None:
        snap = snap or self.store.snapshot
        if snap is None:
            return None
        async with self.cycle_lock:
            t0 = time.perf_counter()
            try:
                plan = await asyncio.to_thread(planner.plan, self.store, snap, self.cfg, force_policy or None)
            except Exception:
                m.CYCLES.labels(self.cfg.active_policy, "error").inc()
                log.exception("cycle_failed")
                self.repo.audit(self.run_id, "alert", "Decision cycle failed", "error", snap.tick)
                return None
            self.last_cycle_tick = snap.tick
            self.plan = plan
            self._policy_guard(plan, snap)
            self._track_predictions(snap, plan)
            self._detect_incidents(snap, plan)
            if plan.fallback_used:
                self.repo.audit(self.run_id, "fallback", f"Fallback policy activated: {plan.fallback_reason}", "warn", snap.tick)
            new = self._reconcile(plan, snap)
            degraded = snap.stale or snap.age_s() > self.cfg.stale_after_s
            if self.cfg.auto_execute and not degraded:
                budget = self.cfg.max_auto_liters
                for d in new:
                    if d.rec.requires_review or d.rec.quantity > budget:
                        continue
                    budget -= d.rec.quantity
                    d.actor = "auto"
                    await self._execute(d, snap)
            elif self.cfg.auto_execute and degraded:
                self.repo.audit(self.run_id, "alert", "Auto-execution suspended: stale/degraded simulator data", "warn", snap.tick)
            self.last_cycle_ms = (time.perf_counter() - t0) * 1000
            m.CYCLE_LATENCY.observe(self.last_cycle_ms / 1000)
            m.CYCLES.labels(plan.policy, "fallback" if plan.fallback_used else "ok").inc()
            self._update_gauges(plan)
            self.repo.tick_row(self.run_id, snap.tick, snap.metrics.service_level, snap.metrics.unmet_demand_liters,
                               {"stations": {s.id: s.inventory for s in snap.stations.values()},
                                "depots": {d.id: d.inventory for d in snap.depots.values()},
                                "recs": len(plan.recommendations), "policy": plan.policy})
            return plan

    def _policy_guard(self, plan: Plan, snap: Snapshot):
        """Automatic rollback: repeated optimizer failures switch the active policy to the rule-based one."""
        self.fallbacks_in_row = self.fallbacks_in_row + 1 if plan.fallback_used else 0
        if self.fallbacks_in_row >= self.cfg.rollback_after and self.cfg.active_policy == "optimizer":
            self.cfg.active_policy, self.cfg.policy_rolled_back = "rules", True
            m.FALLBACK.labels("policy", "auto_rollback").inc()
            self.repo.audit(self.run_id, "fallback", f"POLICY ROLLBACK: optimizer failed {self.fallbacks_in_row} cycles in a row; "
                            "rule-based policy is now active until an operator restores the optimizer", "error", snap.tick)

    def _reconcile(self, plan: Plan, snap: Snapshot) -> list[Decision]:
        """Keep pending proposals *stable* across cycles: same (station, fuel, route) => same decision id.
        Only proposals the planner no longer wants are expired, so the operator's list never churns underneath them."""
        pending = {(d.rec.station_id, d.rec.fuel, d.rec.route_id): d for d in self.decisions.values() if d.status == "PROPOSED"}
        current: list[Decision] = []
        for rec in plan.recommendations:
            key = (rec.station_id, rec.fuel, rec.route_id)
            d = pending.pop(key, None)
            if d is None:
                d = Decision(self._next(), rec)
                self.decisions[d.id] = d
                self.history.append(d.id)
                self._persist(d, snap)
            else:
                prev = d.rec.quantity
                # ignore small wobble so the number the operator is looking at does not keep moving
                d.rec = rec if abs(rec.quantity - prev) > 0.1 * prev else dataclasses.replace(rec, quantity=prev)
            current.append(d)
        for d in pending.values():  # no longer recommended
            d.status, d.result = "EXPIRED", "no longer needed"
            self._persist(d, snap)
        live = set(self.history)
        for did in [i for i in self.decisions if i not in live]:  # bound memory
            del self.decisions[did]
        return current

    # ------------------------------------------------------------------ operator actions
    async def approve(self, did: int, actor: str = "operator") -> Decision:
        d = self.decisions[did]
        if d.status != "PROPOSED":
            raise ValueError(f"decision is {d.status}")
        d.status, d.actor = "APPROVED", actor
        self.repo.audit(self.run_id, "operator", f"Decision #{did} approved by {actor}", "info", d.rec.tick)
        await self._execute(d, self.store.snapshot)
        return d

    def reject(self, did: int, actor: str = "operator") -> Decision:
        d = self.decisions[did]
        if d.status != "PROPOSED":
            raise ValueError(f"decision is {d.status}")
        d.status, d.actor = "REJECTED", actor
        self.repo.audit(self.run_id, "operator", f"Decision #{did} rejected by {actor}", "info", d.rec.tick)
        self._persist(d, self.store.snapshot)
        return d

    # ------------------------------------------------------------------ execution
    def _key(self, d: Decision) -> str:
        if not d.key:
            r = d.rec
            d.key = f"fp-{self.run_id}-t{r.tick}-{r.route_id}-{r.fuel}-d{d.id}"
        return d.key

    async def _execute(self, d: Decision, snap: Snapshot | None):
        r = d.rec
        req = M.AllocationRequest(idempotency_key=self._key(d), source_depot_id=r.depot_id, destination_station_id=r.station_id,
                                  route_id=r.route_id, fuel_type=r.fuel, quantity=r.quantity)
        d.attempts += 1
        if snap is not None:
            bad = precheck(snap, r.depot_id, r.station_id, r.route_id, r.fuel, r.quantity)
            if bad and self.refresh is not None and snap.age_s() > 1.0:
                snap = await self.refresh() or snap  # the cached view may just be stale: re-read once before refusing
                bad = precheck(snap, r.depot_id, r.station_id, r.route_id, r.fuel, r.quantity)
            if bad:
                d.status, d.result = "FAILED", f"PRECHECK_{bad[0]}"
                self.repo.audit(self.run_id, "integration", f"Shipment #{d.id} blocked before sending: {bad[0]} ({bad[1]}); replanning", "warn", r.tick)
                self._persist(d, snap)
                self.last_cycle_tick = -999  # replan on the next snapshot
                return
        try:
            a = await self.client.create_allocation(req)
            d.status, d.sim_allocation_id, d.result = "EXECUTED", a.id, a.status
            self._apply_locally(a)
            log.info("allocation_executed", decision=d.id, alloc=a.id, qty=r.quantity, route=r.route_id, fuel=r.fuel)
        except AllocationRejected as e:
            d.status, d.result = "FAILED", e.code
            self.repo.audit(self.run_id, "integration", f"Allocation #{d.id} rejected by simulator: {e.code}", "warn", r.tick)
        except SimulatorUnavailable as e:
            d.status, d.result = "APPROVED", f"retrying: {e}"  # kept; retried on next snapshot (idempotent key)
            if d.attempts >= 5:
                d.status = "FAILED"
                self.repo.audit(self.run_id, "integration", f"Allocation #{d.id} gave up: simulator unavailable", "error", r.tick)
        except SimulatorError as e:
            d.status, d.result = "FAILED", str(e)[:120]
        self._persist(d, snap)

    def _apply_locally(self, a: M.Allocation):
        """Reflect an accepted shipment in the cached snapshot right away (the next sync confirms it), so a
        planning cycle in the same tick never re-proposes it or double-spends depot stock."""
        snap = self.store.snapshot
        if not snap or any(x.id == a.id for x in snap.allocations):
            return
        snap.allocations.insert(0, a)
        depot = snap.depots.get(a.source_depot_id)
        if depot and a.fuel_type in depot.inventory:
            depot.inventory[a.fuel_type] = max(0.0, depot.inventory[a.fuel_type] - a.quantity)

    async def _retry_approved(self, snap: Snapshot):
        for d in list(self.decisions.values()):
            if d.status == "APPROVED" and d.attempts < 5:
                await self._execute(d, snap)

    def _emit(self, type_: str, **data):
        if self.repo.bus is not None:
            self.repo.bus.publish(type_, **data)

    def _persist(self, d: Decision, snap: Snapshot | None):
        self.version += 1
        self._emit("decision", id=d.id, status=d.status, station=d.rec.station_id, fuel=d.rec.fuel, quantity=d.rec.quantity)
        r = d.rec
        self.repo.decision({
            "run_id": self.run_id, "tick": r.tick, "station_id": r.station_id, "fuel": r.fuel, "depot_id": r.depot_id,
            "route_id": r.route_id, "quantity": r.quantity, "severity": r.severity, "policy": r.policy,
            "status": d.status, "actor": d.actor, "idempotency_key": d.key, "sim_allocation_id": d.sim_allocation_id,
            "result": d.result, "payload": d.to_dict(),
        })

    # ------------------------------------------------------------------ monitoring
    def _track_predictions(self, snap: Snapshot, plan: Plan):
        for (sid, fuel), yhat in plan.pred1.items():
            self.pred[(sid, fuel, snap.tick + 1)] = yhat

    def _score_forecasts(self):
        snap = self.store.snapshot
        if not snap:
            return
        for (sid, fuel, t), yhat in list(self.pred.items()):
            actual = self.store.demand.get((sid, fuel), {}).get(t)
            if actual is not None:
                if actual[0] > 1:
                    self.ape.append(abs(actual[0] - yhat) / actual[0])
                del self.pred[(sid, fuel, t)]
            elif t < snap.tick - 5:
                del self.pred[(sid, fuel, t)]
        if self.ape:
            m.FORECAST_MAPE.set(sum(self.ape) / len(self.ape))

    def _record_timeline(self, snap: Snapshot):
        if self.timeline and self.timeline[-1]["tick"] == snap.tick:
            return
        at_risk = sum(1 for r in (self.plan.risks if self.plan else []) if r.severity in ("CRITICAL", "WARNING"))
        self.timeline.append({"tick": snap.tick, "sim_time": snap.instance.sim_time.isoformat(),
                              "service_level": snap.metrics.service_level, "unmet": snap.metrics.unmet_demand_liters,
                              "at_risk": at_risk, "in_transit": sum(a.quantity for a in snap.in_transit())})

    def mape_recent(self, n: int = 30) -> float | None:
        recent = list(self.ape)[-n:]
        return sum(recent) / len(recent) if len(recent) >= n else None

    def mape(self) -> float | None:
        return sum(self.ape) / len(self.ape) if self.ape else None

    @staticmethod
    def _until(snap: Snapshot, key: str, ident: str) -> str:
        ends = [e.end_tick for e in snap.events if e.status == "ACTIVE" and (ident in (e.parameters.get(key) or []))]
        return f" (until tick {max(ends)})" if ends else ""

    def _spawn(self, coro):
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _attach_similar(self, key: str, vec: list[float]):
        similar = await self.memory.similar(vec)
        if key in self.incidents:
            self.incidents[key]["similar"] = similar
            self.version += 1

    def _remember(self, inc: dict, snap: Snapshot):
        start = inc.get("since_tick", snap.tick)
        mine = [d for d in self.decisions.values() if d.status == "EXECUTED" and start <= d.rec.tick <= snap.tick]
        outcome = {
            "duration_ticks": snap.tick - start,
            "unmet_liters_during": round(max(0.0, snap.metrics.unmet_demand_liters - inc.get("_start_unmet", 0.0))),
            "service_level_start": round(inc.get("_start_sl", 1.0), 4), "service_level_end": round(snap.metrics.service_level, 4),
            "shipments": len(mine), "liters_shipped": round(sum(d.rec.quantity for d in mine)), "policy": self.cfg.active_policy,
        }
        summary = (f"{inc['message']}. Lasted {outcome['duration_ticks']} ticks; {outcome['shipments']} shipment(s) "
                   f"({outcome['liters_shipped']:,} L) were dispatched; {outcome['unmet_liters_during']:,} L of demand went unmet meanwhile.")
        if inc.get("_vec"):
            self.memory.remember(inc["type"], inc["_vec"], start, snap.tick, summary, outcome)

    def _detect_incidents(self, snap: Snapshot, plan: Plan):
        now: dict[str, dict] = {}
        for e in snap.events:
            if e.status == "ACTIVE" and e.type not in ("route_disruption", "station_outage", "depot_constraint"):  # those come from live status below
                now[f"event-{e.id}"] = {"type": e.type, "severity": "high", "message": f"Active {e.type} until tick {e.end_tick}", "params": e.parameters}
        for r in snap.routes.values():
            if r.status != "AVAILABLE":
                now[f"route-{r.id}"] = {"type": "route_disruption", "severity": "high", "message": f"Route {r.id} {r.status}{self._until(snap, 'route_ids', r.id)}"}
        for s in snap.stations.values():
            if s.status != "OPEN":
                now[f"station-{s.id}"] = {"type": "station_outage", "severity": "high", "message": f"Station {s.name} {s.status}{self._until(snap, 'station_ids', s.id)}"}
        for d in snap.depots.values():
            if d.status != "OPEN":
                now[f"depot-{d.id}"] = {"type": "depot_constraint", "severity": "medium", "message": f"Depot {d.name} {d.status}{self._until(snap, 'depot_ids', d.id)}"}
        delayed = [a for a in snap.arrivals if a.status == "DELAYED"]
        if delayed:
            depots = sorted({a.depot_id.replace("depot-", "") for a in delayed})
            now["supply-delay"] = {"type": "shipment_delay", "severity": "medium",
                                   "message": f"{len(delayed)} supply deliveries delayed ({', '.join(depots)}); "
                                              f"next now due tick {min(a.planned_tick for a in delayed)}"}
        mp = self.mape_recent()
        if mp is not None and mp > self.cfg.drift_mape:
            now["model-drift"] = {"type": "model_drift", "severity": "medium",
                                  "message": f"Forecast error {mp:.0%} is above the {self.cfg.drift_mape:.0%} limit; demand pattern may have shifted"}
        for sid, fuel, z, level in plan.anomalies:
            now[f"anomaly-{sid}-{fuel}"] = {"type": "demand_anomaly", "severity": "medium",
                                            "message": f"Demand anomaly at {sid} {fuel}: x{level:.2f} of baseline (z={z:.1f})"}
        sl = snap.metrics.service_level
        crit = sum(1 for r in plan.risks if r.severity == "CRITICAL") / 12
        for k, v in now.items():
            prev = self.incidents.get(k)
            if prev is None:
                vec = signature(v["type"], snap.instance.sim_time.hour, sl, crit)
                v.update(since_tick=snap.tick, _vec=vec, _start_unmet=snap.metrics.unmet_demand_liters, _start_sl=sl, similar=[])
                self.repo.audit(self.run_id, "alert", f"INCIDENT DETECTED: {v['message']}", "warn", snap.tick, {k2: v2 for k2, v2 in v.items() if not k2.startswith("_")})
                self._spawn(self._attach_similar(k, vec))
            else:
                for f in ("since_tick", "_vec", "_start_unmet", "_start_sl", "similar"):
                    v[f] = prev.get(f)
        for k, v in self.incidents.items():
            if k not in now:
                self.repo.audit(self.run_id, "recovery", f"RECOVERED: {v['message']}", "info", snap.tick)
                self._remember(v, snap)
        self.incidents = now

    def _update_gauges(self, plan: Plan):
        cnt = {"CRITICAL": 0, "WARNING": 0, "WATCH": 0}
        for r in plan.risks:
            if r.severity in cnt:
                cnt[r.severity] += 1
        for k, v in cnt.items():
            m.ALERTS.labels(k).set(v)
        if plan.risks:
            m.CONFIDENCE.set(sum(r.confidence for r in plan.risks) / len(plan.risks))
