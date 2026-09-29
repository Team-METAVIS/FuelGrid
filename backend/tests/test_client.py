import httpx
import pytest
import respx

from app.core.config import Settings
from app.simulator import models as M
from app.simulator.client import SimulatorClient
from app.simulator.errors import AllocationRejected, InvalidSimulatorResponse, SimulatorUnavailable

BASE = "http://sim.test"
INST = {"id": 1, "scenario_id": "b", "seed": 1, "sim_time": "2026-01-01T00:00:00+00:00", "tick": 3, "tick_minutes": 15, "status": "PAUSED"}


def client(**kw):
    return SimulatorClient(Settings(sim_base_url=BASE, sim_retries=3, breaker_failures=3, breaker_reset_s=60, database_url=None, **kw))


@respx.mock
async def test_retries_then_succeeds():
    route = respx.get(f"{BASE}/v1/instance").mock(side_effect=[httpx.Response(503), httpx.Response(503), httpx.Response(200, json=INST)])
    inst = await client().instance()
    assert inst.tick == 3 and route.call_count == 3


@respx.mock
async def test_breaker_opens_and_fast_fails():
    respx.get(f"{BASE}/v1/instance").mock(return_value=httpx.Response(503))
    c = client()
    for _ in range(3):
        with pytest.raises(SimulatorUnavailable):
            await c.instance()
    assert c.breaker.open
    calls = respx.calls.call_count
    with pytest.raises(SimulatorUnavailable):
        await c.instance()
    assert respx.calls.call_count == calls  # no network call while open


@respx.mock
async def test_invalid_payload_rejected():
    respx.get(f"{BASE}/v1/instance").mock(return_value=httpx.Response(200, json={"tick": "not-a-number"}))
    with pytest.raises(InvalidSimulatorResponse):
        await client().instance()


@respx.mock
async def test_stale_header_detected():
    respx.get(f"{BASE}/v1/instance").mock(return_value=httpx.Response(200, json=INST, headers={"X-Simulator-Stale": "true"}))
    c = client()
    await c.instance()
    assert c.last_stale


@respx.mock
async def test_allocation_rejection_maps_error_code():
    respx.post(f"{BASE}/v1/allocations").mock(return_value=httpx.Response(409, json={"detail": {"code": "ROUTE_DISRUPTED", "message": "x"}}))
    req = M.AllocationRequest(idempotency_key="k", source_depot_id="d", destination_station_id="s", route_id="r", fuel_type="DIESEL", quantity=10)
    with pytest.raises(AllocationRejected) as e:
        await client().create_allocation(req)
    assert e.value.code == "ROUTE_DISRUPTED"


def test_allocation_request_validates_input():
    with pytest.raises(ValueError):
        M.AllocationRequest(idempotency_key="", source_depot_id="d", destination_station_id="s", route_id="r", fuel_type="DIESEL", quantity=10)
    with pytest.raises(ValueError):
        M.AllocationRequest(idempotency_key="k", source_depot_id="d", destination_station_id="s", route_id="r", fuel_type="COAL", quantity=10)


@respx.mock
async def test_bulkhead_limits_concurrent_simulator_calls():
    import asyncio

    state = {"now": 0, "peak": 0}

    async def handler(request):
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.02)
        state["now"] -= 1
        return httpx.Response(200, json=INST)

    respx.get(f"{BASE}/v1/instance").mock(side_effect=handler)
    c = client()
    await asyncio.gather(*[c.instance() for _ in range(30)])
    assert state["peak"] <= c.s.sim_max_concurrency  # protects the simulator's tiny DB pool


async def test_refresh_is_single_flight():
    import asyncio

    from app.state.store import StateStore
    from app.state.sync import Synchronizer

    calls = 0

    class Fake:
        s = Settings(database_url=None)
        last_stale = False

        async def instance(self):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            raise SimulatorUnavailable("boom")

        def __getattr__(self, name):  # every other endpoint is never reached
            async def nope():
                return []
            return nope

    sync = Synchronizer(Fake(), StateStore())
    await asyncio.gather(*[sync.refresh() for _ in range(10)])
    assert calls == 1, "ten concurrent refreshes must cost one round of simulator calls"
