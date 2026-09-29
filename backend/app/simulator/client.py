"""Resilient simulator client: timeouts, retry+backoff (tenacity), circuit breaker, stale-flag, validation."""
import asyncio
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from app.core import metrics as m
from app.core.config import Settings
from app.core.logging import get_logger
from app.simulator import models as M
from app.simulator.errors import AllocationRejected, InvalidSimulatorResponse, SimulatorUnavailable

log = get_logger("sim.client")
T = TypeVar("T", bound=BaseModel)


class CircuitBreaker:
    def __init__(self, failures: int, reset_s: float):
        self.threshold, self.reset_s = failures, reset_s
        self.fails, self.opened_at = 0, 0.0

    @property
    def open(self) -> bool:
        if self.fails < self.threshold:
            return False
        if time.monotonic() - self.opened_at >= self.reset_s:  # half-open: allow one probe
            return False
        return True

    def ok(self):
        self.fails = 0
        m.BREAKER_STATE.set(0)

    def fail(self):
        self.fails += 1
        if self.fails >= self.threshold:
            self.opened_at = time.monotonic()
            m.BREAKER_STATE.set(1)


class _Transient(Exception):
    pass


class SimulatorClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings
        self.http = httpx.AsyncClient(
            base_url=settings.sim_base_url, timeout=settings.sim_timeout_s, transport=transport
        )
        self._sem = asyncio.Semaphore(settings.sim_max_concurrency)  # bulkhead: bounded concurrent calls
        self.breaker = CircuitBreaker(settings.breaker_failures, settings.breaker_reset_s)
        self.last_stale = False  # last GET carried X-Simulator-Stale
        self.last_error: str | None = None
        self.last_ok_at: float | None = None

    async def aclose(self):
        await self.http.aclose()

    async def _request(self, method: str, path: str, *, name: str, retries: int | None = None, **kw) -> httpx.Response:
        if self.breaker.open:
            m.SIM_REQUESTS.labels(name, "breaker_open").inc()
            raise SimulatorUnavailable("circuit breaker open")
        attempts = retries if retries is not None else self.s.sim_retries
        t0 = time.perf_counter()
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential_jitter(initial=0.2, max=2.0),
                retry=retry_if_exception_type(_Transient),
                reraise=True,
            ):
                with attempt:
                    try:
                        async with self._sem:
                            r = await self.http.request(method, path, **kw)
                    except httpx.HTTPError as e:
                        raise _Transient(f"{type(e).__name__}: {e}") from e
                    if r.status_code >= 500:
                        raise _Transient(f"HTTP {r.status_code}")
        except _Transient as e:
            self.breaker.fail()
            self.last_error = str(e)
            m.SIM_REQUESTS.labels(name, "error").inc()
            log.warning("sim_call_failed", endpoint=name, error=str(e), breaker_open=self.breaker.open)
            raise SimulatorUnavailable(str(e)) from e
        finally:
            m.SIM_LATENCY.labels(name).observe(time.perf_counter() - t0)
        self.breaker.ok()
        self.last_ok_at = time.time()
        self.last_error = None
        m.SIM_REQUESTS.labels(name, "ok").inc()
        return r

    async def _get(self, path: str, model: type[T] | None, *, name: str, many: bool = True, **kw) -> Any:
        r = await self._request("GET", path, name=name, **kw)
        self.last_stale = r.headers.get("x-simulator-stale", "").lower() == "true"
        if self.last_stale:
            m.STALE_DATA.inc()
        try:
            data = r.json()
            if model is None:
                return data
            return TypeAdapter(list[model]).validate_python(data) if many else model.model_validate(data)
        except (ValidationError, ValueError) as e:
            m.SIM_REQUESTS.labels(name, "invalid").inc()
            log.error("invalid_simulator_response", endpoint=name, error=str(e)[:300])
            raise InvalidSimulatorResponse(f"{name}: {str(e)[:200]}") from e

    # ---- reads ----
    async def health(self) -> dict:
        r = await self._request("GET", "/v1/health", name="health", retries=1)
        return r.json()

    async def instance(self) -> M.Instance:
        return await self._get("/v1/instance", M.Instance, name="instance", many=False)

    async def depots(self) -> list[M.Depot]:
        return await self._get("/v1/depots", M.Depot, name="depots")

    async def stations(self) -> list[M.Station]:
        return await self._get("/v1/stations", M.Station, name="stations")

    async def routes(self) -> list[M.Route]:
        return await self._get("/v1/routes", M.Route, name="routes")

    async def supply_arrivals(self) -> list[M.SupplyArrival]:
        return await self._get("/v1/supply-arrivals", M.SupplyArrival, name="supply_arrivals")

    async def events(self) -> list[M.SimEvent]:
        return await self._get("/v1/events", M.SimEvent, name="events")

    async def allocations(self) -> list[M.Allocation]:
        return await self._get("/v1/allocations", M.Allocation, name="allocations")

    async def demand_history(self, station_id: str | None = None, limit: int = 2000) -> list[M.DemandRow]:
        params: dict = {"limit": limit}
        if station_id:
            params["station_id"] = station_id
        return await self._get("/v1/demand-history", M.DemandRow, name="demand_history", params=params)

    async def metrics(self) -> M.Metrics:
        return await self._get("/v1/metrics", M.Metrics, name="metrics", many=False)

    # ---- the only domain write ----
    async def create_allocation(self, req: M.AllocationRequest) -> M.Allocation:
        """Idempotent (same key + body => replay), so retrying on transient failure is safe."""
        try:
            r = await self._request("POST", "/v1/allocations", name="create_allocation", json=req.model_dump(mode="json"))
        except SimulatorUnavailable:
            m.ALLOCATIONS.labels("unavailable").inc()
            raise
        if r.status_code in (200, 201):
            m.ALLOCATIONS.labels("accepted").inc()
            return M.Allocation.model_validate(r.json())
        detail = {}
        try:
            detail = r.json().get("detail", {}) or {}
        except ValueError:
            pass
        code = detail.get("code", f"HTTP_{r.status_code}") if isinstance(detail, dict) else "VALIDATION"
        m.ALLOCATIONS.labels("rejected").inc()
        raise AllocationRejected(r.status_code, code, str(detail))

    async def cancel_allocation(self, allocation_id: int) -> dict:
        r = await self._request("POST", f"/v1/allocations/{allocation_id}/cancel", name="cancel_allocation")
        return r.json()

    # ---- admin (scenario / chaos console; self-test only) ----
    async def admin(self, method: str, path: str, json: dict | None = None) -> Any:
        r = await self.http.request(method, path, json=json)
        r.raise_for_status()
        return r.json() if r.content else {}
