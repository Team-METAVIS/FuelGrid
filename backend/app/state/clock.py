"""Lock-step clock for the simulator: step -> read the world -> plan -> step.

Why it exists: the simulator's own "run" mode ticks at a fixed speed (8 ticks/s by default) whether or not anyone has planned.
A platform that reads the world twice a second then plans only every few ticks, and because each plan can send just one
shipment per road and fuel, it falls behind and stations run dry. In lock-step the platform advances time itself, so every
tick is observed and planned before the next one starts, at whatever speed the operator chooses."""
import asyncio
import time

from app.core.logging import get_logger

log = get_logger("clock")


class LockStepClock:
    def __init__(self, source, sync):
        self.source, self.sync = source, sync
        self.running = False
        self.speed = 2.0
        self.steps = 0
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None

    async def start(self, speed: float) -> None:
        await self.stop()
        self.speed = max(0.2, min(float(speed), 20.0))
        await self.source.admin("POST", "/admin/pause")  # the platform, not the simulator, owns time from now on
        self.running, self.last_error = True, None
        self._task = asyncio.create_task(self._loop())
        log.info("lockstep_clock_started", speed=self.speed)

    async def _loop(self) -> None:
        try:
            while self.running:
                t0 = time.perf_counter()
                try:
                    await self.source.admin("POST", "/admin/step")
                    await self.sync.refresh()  # returns after the snapshot was ingested AND the decision cycle ran
                    self.steps += 1
                    self.last_error = None
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # a failed step must never kill the clock; back off and retry
                    self.last_error = f"{type(e).__name__}: {str(e)[:100]}"
                    log.warning("lockstep_step_failed", error=self.last_error)
                    await asyncio.sleep(1.0)
                await asyncio.sleep(max(0.0, 1 / self.speed - (time.perf_counter() - t0)))
        except asyncio.CancelledError:
            pass

    async def stop(self) -> None:
        self.running = False
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:  # wait for an in-flight step to unwind so it cannot race a reset or source switch
                await task
            except asyncio.CancelledError:
                pass

    def status(self) -> dict:
        return {"running": self.running, "speed": self.speed, "steps": self.steps, "last_error": self.last_error}
