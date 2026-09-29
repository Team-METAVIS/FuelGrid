import asyncio

from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from app.intelligence.memory import IncidentMemory, signature
from tests.conftest import make_snapshot
from tests.test_engine import FakeClient


def test_signature_groups_by_incident_type():
    a = signature("route_disruption", 9, 0.97, 0.1)
    b = signature("route_disruption", 14, 0.90, 0.2)
    c = signature("demand_spike", 9, 0.97, 0.1)
    cos = lambda x, y: sum(p * q for p, q in zip(x, y, strict=True)) / (sum(p * p for p in x) ** 0.5 * sum(q * q for q in y) ** 0.5)  # noqa: E731
    assert cos(a, b) > 0.85 and cos(a, b) > cos(a, c) + 0.1


async def test_similarity_search_works_without_a_database():
    mem = IncidentMemory(Repo(None), "t")
    mem.remember("route_disruption", signature("route_disruption", 8, 0.98, 0.0), 10, 40, "road closed; rerouted", {"liters_shipped": 9000})
    mem.remember("demand_spike", signature("demand_spike", 8, 0.98, 0.0), 10, 30, "spike", {})
    hits = await mem.similar(signature("route_disruption", 9, 0.95, 0.1))
    assert hits and hits[0]["type"] == "route_disruption" and hits[0]["outcome"]["liters_shipped"] == 9000
    assert await mem.similar(signature("model_drift", 9, 0.95, 0.1)) == []  # nothing similar enough => no noise


async def test_incident_lifecycle_is_remembered_and_recalled(cfg, store):
    eng = DecisionEngine(cfg, store, FakeClient(), Repo(None), "t")
    closed = {"route-gazipur-mirpur": "DISRUPTED"}
    store.snapshot = make_snapshot(tick=10, hour=8, route_status=closed)
    await eng.cycle()
    assert any(i["type"] == "route_disruption" for i in eng.incidents.values())
    store.snapshot = make_snapshot(tick=30, hour=10)  # road reopened
    await eng.cycle()
    assert not eng.incidents and eng.memory.local, "a resolved incident must be stored with its outcome"
    assert eng.memory.local[0]["outcome"]["duration_ticks"] == 20
    store.snapshot = make_snapshot(tick=50, hour=9, route_status=closed)  # same kind of trouble again
    await eng.cycle()
    await asyncio.sleep(0.05)  # similarity lookup runs as a background task
    inc = next(i for i in eng.incidents.values() if i["type"] == "route_disruption")
    assert inc["similar"] and inc["similar"][0]["outcome"]["duration_ticks"] == 20
