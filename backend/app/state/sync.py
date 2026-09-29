"""State synchronizer: REST is truth; SSE only triggers a re-sync. Polling is the fallback."""
import asyncio
import json
import time
from collections.abc import Awaitable, Callable

import httpx
from httpx_sse import aconnect_sse

from app.core import metrics as m
from app.core.logging import get_logger
from app.simulator.client import SimulatorClient
from app.simulator.errors import SimulatorError
from app.state.store import Snapshot, StateStore

log = get_logger("state.sync")


class Synchronizer:
    def __init__(self, client: SimulatorClient, store: StateStore):
        self.client, self.store = client, store
        self.sse_connected = False
        self.trigger = asyncio.Event()
        self.last_error: str | None = None
        self.consecutive_failures = 0
        self.on_snapshot: list[Callable[[Snapshot], Awaitable[None]]] = []
        self.on_reset: list[Callable[[], None]] = []
        self._tasks: list[asyncio.Task] = []
        self.warm = False
        self.last_tick = -1
        self._inflight: asyncio.Task | None = None

    async def refresh(self) -> Snapshot | None:
        """Single-flight: concurrent callers share one refresh, so we never multiply load on the simulator."""
        task = self._inflight
        if task is None or task.done():
            task = self._inflight = asyncio.create_task(self._refresh())
        return await asyncio.shield(task)

    async def _refresh(self) -> Snapshot | None:
        c = self.client
        try:
            inst, depots, stations, routes, arrivals, events, allocs, metr = await asyncio.gather(
                c.instance(), c.depots(), c.stations(), c.routes(), c.supply_arrivals(), c.events(),
                c.allocations(), c.metrics(),
            )
            if self.warm and inst.tick < self.last_tick:  # tick went backwards => simulator was reset
                log.warning("simulator_reset_detected", from_tick=self.last_tick, to_tick=inst.tick)
                self.store.clear()
                self.warm = False
                for cb in self.on_reset:
                    cb()
            # one call for all stations: 12 rows/tick; fetch just the gap since the last seen tick
            gap = inst.tick - self.last_tick if self.warm else 10_000
            limit = min(2000, max(48, 12 * (gap + 2)))
            self.store.ingest_demand(await c.demand_history(None, limit))
            self.last_tick = inst.tick
            self.warm = True
        except SimulatorError as e:
            self.consecutive_failures += 1
            self.last_error = str(e)
            m.DEGRADED.set(1)
            if self.store.snapshot:
                self.store.snapshot.stale = True
            log.warning("sync_failed", error=str(e), failures=self.consecutive_failures)
            return None
        snap = Snapshot(
            instance=inst, depots={d.id: d for d in depots}, stations={s.id: s for s in stations},
            routes={r.id: r for r in routes}, arrivals=arrivals, events=events, allocations=allocs,
            metrics=metr, stale=c.last_stale,
        )
        self.store.snapshot = snap
        if self.consecutive_failures:
            log.info("sync_recovered", after_failures=self.consecutive_failures)
        self.consecutive_failures, self.last_error = 0, None
        m.DEGRADED.set(1 if snap.stale else 0)
        m.TICK.set(snap.tick)
        m.SERVICE_LEVEL.set(snap.metrics.service_level)
        for cb in self.on_snapshot:
            try:
                await cb(snap)
            except Exception:  # never let a consumer kill the sync loop
                log.exception("snapshot_consumer_failed")
        return snap

    async def _sse_loop(self):
        backoff = 1.0
        while True:
            try:
                async with httpx.AsyncClient(base_url=self.client.s.sim_base_url, timeout=None) as h:
                    async with aconnect_sse(h, "GET", "/v1/stream") as es:
                        es.response.raise_for_status()
                        self.sse_connected = True
                        m.SSE_CONNECTED.set(1)
                        backoff = 1.0
                        self.trigger.set()  # always re-GET after (re)connect
                        async for ev in es.aiter_sse():
                            if ev.event in ("simulation.tick", "allocation.status_changed", "inventory.updated", "simulator.notice"):
                                self.trigger.set()
            except (httpx.HTTPError, json.JSONDecodeError, OSError) as e:
                log.warning("sse_disconnected", error=str(e)[:120])
            self.sse_connected = False
            m.SSE_CONNECTED.set(0)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15.0)

    async def _refresh_loop(self):
        poll = self.client.s.poll_interval_s
        while True:
            try:
                await asyncio.wait_for(self.trigger.wait(), timeout=poll)  # SSE hint OR poll fallback
            except TimeoutError:
                pass
            self.trigger.clear()
            t0 = time.perf_counter()
            await self.refresh()
            # coalesce bursts (sim can tick 8x/s): don't sync faster than ~2/s
            await asyncio.sleep(max(0.0, 0.5 - (time.perf_counter() - t0)))

    def start(self):
        self._tasks = [asyncio.create_task(self._sse_loop()), asyncio.create_task(self._refresh_loop())]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
