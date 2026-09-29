from app.core.events import EventBus
from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from tests.conftest import make_snapshot
from tests.test_engine import LOW, FakeClient


def test_bus_publish_subscribe_and_replay():
    bus = EventBus()
    q = bus.subscribe()
    e1 = bus.publish("decision", id=1, status="PROPOSED")
    bus.publish("audit", kind="alert", message="x")
    assert q.get_nowait()["id"] == e1["id"] and q.qsize() == 1
    assert [e["type"] for e in bus.since(e1["id"])] == ["audit"]  # a reconnecting client replays what it missed
    bus.unsubscribe(q)
    assert bus.subscribers == 0


def test_slow_subscriber_loses_oldest_but_never_blocks_publisher():
    bus = EventBus()
    q = bus.subscribe(maxsize=3)
    for i in range(10):
        bus.publish("snapshot", tick=i)  # must not raise or block
    assert q.qsize() == 3
    assert [q.get_nowait()["data"]["tick"] for _ in range(3)] == [7, 8, 9]


async def test_engine_and_audit_emit_events(cfg, store):
    store.snapshot = make_snapshot(hour=8, station_inv=LOW)
    repo = Repo(None)
    repo.bus = EventBus()
    eng = DecisionEngine(cfg, store, FakeClient(), repo, "t")
    await eng.cycle()
    did = next(d.id for d in eng.decisions.values() if d.status == "PROPOSED")
    await eng.approve(did)
    types = [(e["type"], e["data"].get("status")) for e in repo.bus.recent]
    assert ("decision", "PROPOSED") in types and ("decision", "EXECUTED") in types
    assert any(e["type"] == "audit" and e["data"]["kind"] == "operator" for e in repo.bus.recent)
