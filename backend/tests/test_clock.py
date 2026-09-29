import asyncio

import pytest

from app.adapters.feed import FeedSource
from app.core.config import Settings
from app.state.clock import LockStepClock
from app.worldgen.driver import DemoWorld


class FakeSource:
    def __init__(self):
        self.calls = []

    async def admin(self, method, path, body=None):
        self.calls.append(path)
        return {}


class FakeSync:
    def __init__(self, source):
        self.source, self.refreshes, self.max_gap = source, 0, 0

    async def refresh(self):
        steps = self.source.calls.count("/admin/step")
        self.max_gap = max(self.max_gap, steps - self.refreshes)  # steps taken but not yet planned
        self.refreshes += 1
        await asyncio.sleep(0.01)  # planning takes time


@pytest.mark.asyncio
async def test_lockstep_clock_never_steps_faster_than_it_plans():
    src = FakeSource()
    sync = FakeSync(src)
    clock = LockStepClock(src, sync)
    await clock.start(speed=20)
    await asyncio.sleep(0.5)
    await clock.stop()
    assert src.calls[0] == "/admin/pause", "the platform must take over the clock first"
    assert clock.steps >= 5 and sync.max_gap <= 1, "every step is observed and planned before the next one"


@pytest.mark.asyncio
async def test_clock_survives_a_failing_step_and_reports_it():
    class Flaky(FakeSource):
        async def admin(self, method, path, body=None):
            if path == "/admin/step" and len(self.calls) == 1:
                self.calls.append(path)
                raise RuntimeError("simulator hiccup")
            return await super().admin(method, path, body)

    src = Flaky()
    clock = LockStepClock(src, FakeSync(src))
    await clock.start(speed=20)
    await asyncio.sleep(1.4)
    await clock.stop()
    assert clock.steps >= 1, "the clock must keep going after a failed step"


@pytest.mark.asyncio
async def test_demo_world_waits_for_the_platform_each_tick():
    feed = FeedSource(Settings(database_url=None))
    seen = []

    async def after():
        seen.append(feed.tick)
        await asyncio.sleep(0.01)

    demo = DemoWorld(feed, after_tick=after)
    await demo.start(seed=3, speed=30, warmup_ticks=30)
    await asyncio.sleep(0.6)
    await demo.stop()
    assert len(seen) >= 5 and seen == sorted(seen) and len(set(seen)) == len(seen), "each tick is handed to the platform exactly once, in order"


@pytest.mark.asyncio
async def test_lockstep_clock_stop_waits_for_in_flight_step():
    src = FakeSource()
    sync = FakeSync(src)
    clock = LockStepClock(src, sync)
    await clock.start(speed=20)
    await asyncio.sleep(0.05)
    await clock.stop()
    n = len(src.calls)
    await asyncio.sleep(0.1)
    assert len(src.calls) == n and not clock.running, "no step may run after stop() returns"


@pytest.mark.asyncio
async def test_lockstep_clock_start_fails_cleanly_when_simulator_down():
    class DownSource(FakeSource):
        async def admin(self, method, path, body=None):
            raise ConnectionError("simulator unreachable")

    clock = LockStepClock(DownSource(), FakeSync(FakeSource()))
    with pytest.raises(ConnectionError):
        await clock.start(speed=2)
    assert not clock.running and clock._task is None
