import pytest

from app.db.repo import Repo
from app.decision.engine import DecisionEngine
from app.simulator import models as M
from app.simulator.errors import SimulatorUnavailable
from tests.conftest import make_snapshot

LOW = {"station-mirpur": (300, 9000, 5000)}


class FakeClient:
    def __init__(self):
        self.calls, self.fail = [], False
        self.breaker = type("B", (), {"open": False})()

    async def create_allocation(self, req: M.AllocationRequest):
        if self.fail:
            raise SimulatorUnavailable("down")
        self.calls.append(req)
        return M.Allocation(id=len(self.calls), idempotency_key=req.idempotency_key, source_depot_id=req.source_depot_id,
                            destination_station_id=req.destination_station_id, route_id=req.route_id, fuel_type=req.fuel_type.value,
                            quantity=req.quantity, created_tick=0, status="PENDING")


@pytest.fixture
def eng(cfg, store):
    store.snapshot = make_snapshot(hour=8, station_inv=LOW)
    return DecisionEngine(cfg, store, FakeClient(), Repo(None), "t")


def pending(e):
    return {d.id: d for d in e.decisions.values() if d.status == "PROPOSED"}


async def test_proposal_ids_are_stable_across_cycles(eng):
    await eng.cycle()
    first = {i: (d.rec.station_id, d.rec.fuel, d.rec.route_id) for i, d in pending(eng).items()}
    assert first
    for _ in range(3):
        await eng.cycle()
    again = {i: (d.rec.station_id, d.rec.fuel, d.rec.route_id) for i, d in pending(eng).items()}
    assert again == first, "same recommendation must keep the same id (no churn under the operator)"
    assert not [d for d in eng.decisions.values() if d.status == "EXPIRED"]


async def test_approve_executes_and_removes_from_pending(eng):
    await eng.cycle()
    did = next(iter(pending(eng)))
    d = await eng.approve(did)
    assert d.status == "EXECUTED" and d.sim_allocation_id
    assert did not in pending(eng)
    assert len(eng.client.calls) == 1
    with pytest.raises(ValueError):
        await eng.approve(did)  # cannot be approved twice


async def test_approved_shipment_is_not_reproposed_and_stock_not_double_spent(eng):
    await eng.cycle()
    for did in list(pending(eng)):
        await eng.approve(did)
    executed = {(d.rec.station_id, d.rec.fuel) for d in eng.decisions.values() if d.status == "EXECUTED"}
    await eng.cycle()
    reproposed = {(d.rec.station_id, d.rec.fuel) for d in pending(eng).values()}
    assert not (executed & reproposed), "in-flight shipment must count immediately"


async def test_reject_removes_and_logs(eng):
    await eng.cycle()
    did = next(iter(pending(eng)))
    assert eng.reject(did).status == "REJECTED"
    assert did not in pending(eng)


async def test_transient_failure_keeps_decision_for_idempotent_retry(eng):
    await eng.cycle()
    did = next(iter(pending(eng)))
    eng.client.fail = True
    d = await eng.approve(did)
    assert d.status == "APPROVED"  # not lost
    key = d.key
    eng.client.fail = False
    await eng._retry_approved(eng.store.snapshot)
    assert d.status == "EXECUTED" and d.key == key  # same idempotency key => safe retry


async def test_auto_execute_respects_review_and_cap(eng):
    eng.cfg.auto_execute = True
    eng.cfg.max_auto_liters = 1000
    await eng.cycle()
    executed = [d for d in eng.decisions.values() if d.status == "EXECUTED"]
    assert sum(d.rec.quantity for d in executed) <= 1000
    assert all(not d.rec.requires_review for d in executed)


async def test_automatic_policy_rollback_after_repeated_failures(eng, monkeypatch):
    from app.intelligence import planner

    def boom(*a, **k):
        raise RuntimeError("solver crashed")

    monkeypatch.setitem(planner.POLICIES, "optimizer", boom)
    for _ in range(eng.cfg.rollback_after):
        await eng.cycle()
    assert eng.cfg.active_policy == "rules" and eng.cfg.policy_rolled_back
    assert any("ROLLBACK" in a["message"] for a in eng.repo.mem_audit)


async def test_plan_reports_counterfactual_comparison(eng):
    plan = await eng.cycle()
    c = plan.comparison
    assert c["none"] >= c["optimizer"], "acting must not be worse than doing nothing"
    assert "rules" in c


async def test_briefing_is_plain_language(eng):
    from types import SimpleNamespace

    from app.intelligence import briefing

    await eng.cycle()
    rt = SimpleNamespace(store=eng.store, engine=eng, cfg=eng.cfg, client=eng.client)
    b = briefing.build(rt)
    assert b["headline"] and b["points"]
    assert any("waiting for your approval" in p["text"] for p in b["points"])
