"""Runs the independent world against a FeedSource inside the FuelGrid process (one click from the console)."""
import asyncio
import time

from app.adapters.feed import FeedSource, TelemetryIn, TopologyIn
from app.core.logging import get_logger
from app.worldgen.world import World

log = get_logger("demo")


def orders_for_world(feed: FeedSource) -> list[dict]:
    return [{"id": o.id, "depot": o.source_depot_id, "station": o.destination_station_id, "route": o.route_id, "fuel": o.fuel_type, "qty": o.quantity}
            for o in feed.pending_orders("PENDING")]


def push_tick(feed: FeedSource, world: World, orders: list[dict]) -> dict:
    tel = world.step(orders)
    if world.topology_dirty:  # the network changed (e.g. a new station): tell the platform
        feed.set_topology(TopologyIn(**world.topology()))
    return feed.ingest(TelemetryIn(**tel))


class DemoWorld:
    def __init__(self, feed: FeedSource, after_tick=None):
        self.feed = feed
        self.after_tick = after_tick  # awaited after every tick: lock-step, so the platform plans each tick before the next
        self.world = World()
        self.speed = 4.0
        self.running = False
        self._task: asyncio.Task | None = None

    async def start(self, seed: int = 7, speed: float = 4.0, warmup_ticks: int = 240) -> None:
        await self.stop()
        keep = self.feed.on_change
        self.feed.__init__(self.feed.s)  # forget everything: a fresh live network
        self.feed.on_change = keep
        self.world, self.speed = World(seed), max(0.2, min(speed, 60.0))
        self.feed.set_topology(TopologyIn(**self.world.topology()))
        for _ in range(warmup_ticks):  # a few days of history, produced by the old min/max dispatcher
            push_tick(self.feed, self.world, [])
        self.world.legacy = False
        self.running = True
        self._task = asyncio.create_task(self._loop())
        log.info("demo_world_started", seed=seed, speed=self.speed, warmup=warmup_ticks)

    async def _loop(self) -> None:
        try:
            while self.running:
                t0 = time.perf_counter()
                push_tick(self.feed, self.world, orders_for_world(self.feed))
                if self.after_tick is not None:
                    try:
                        await self.after_tick()
                    except Exception as e:  # never let the platform's trouble stop the world
                        log.warning("demo_after_tick_failed", error=str(e)[:100])
                await asyncio.sleep(max(0.0, 1 / self.speed - (time.perf_counter() - t0)))
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self.running = False
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:  # wait for an in-flight tick so it cannot write into the fresh network start() builds next
                await task
            except asyncio.CancelledError:
                pass

    def status(self) -> dict:
        w = self.world
        return {"running": self.running, "tick": w.tick, "speed": self.speed, "service_level": round(w.service_level, 4),
                "stations": len(w.stations), "level": round(w.level, 2), "peak_shift_h": w.peak_shift_h, "changes": w.log[-8:],
                "truth_unmet_l": round(w.unmet), "truth_served_l": round(w.served)}
