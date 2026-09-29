import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_snapshot
from tests.test_engine import LOW, FakeClient


@pytest.fixture
def api():
    app = create_app(Settings(database_url=None, forecaster="seasonal"), start_background=False)
    with TestClient(app) as c:
        rt = app.state.rt
        rt.engine.client = FakeClient()
        rt.store.snapshot = make_snapshot(hour=8, station_inv=LOW)
        c.portal.call(rt.engine.cycle)
        yield c, rt


def test_controls_describe_themselves(api):
    c, _ = api
    d = c.get("/api/controls").json()
    names = [g["name"] for g in d["groups"]]
    assert names == ["Engine", "Approvals", "Planning", "Model", "Resilience"]
    every = {x["key"]: x for g in d["groups"] for x in g["controls"]}
    assert every["auto_execute"]["kind"] == "bool" and every["auto_execute"]["value"] is False
    assert every["safety_z"]["min"] == 0 and every["safety_z"]["max"] == 3 and every["safety_z"]["help"]
    assert every["forecaster"]["options"][0] == "learned"


def test_valid_changes_apply_and_are_audited(api):
    c, rt = api
    out = c.post("/api/controls", json={"values": {"safety_z": 1.5, "auto_execute": True, "active_policy": "rules", "paused": True}}).json()
    assert out["changed"] == {"safety_z": 1.5, "auto_execute": True, "active_policy": "rules", "paused": True}
    assert rt.cfg.safety_z == 1.5 and rt.cfg.auto_execute and rt.engine.paused and rt.cfg.active_policy == "rules"
    assert any("Control changed: Auto-approve" in a["message"] for a in rt.repo.mem_audit)


def test_bad_values_are_refused_server_side(api):
    c, rt = api
    before = rt.cfg.safety_z
    for bad in ({"safety_z": 99}, {"safety_z": "high"}, {"auto_execute": "yes"}, {"active_policy": "magic"}, {"nonsense": 1}):
        assert c.post("/api/controls", json={"values": bad}).status_code == 422, bad
    assert rt.cfg.safety_z == before
    mixed = c.post("/api/controls", json={"values": {"safety_z": 1.0, "depot_reserve_frac": 9}}).json()
    assert mixed["changed"] == {"safety_z": 1.0} and "depot_reserve_frac" in mixed["errors"]


def test_emergency_stop_halts_everything_and_resume_only_restarts_planning(api):
    c, rt = api
    c.post("/api/controls", json={"values": {"auto_execute": True}})
    assert any(d.status == "PROPOSED" for d in rt.engine.decisions.values())
    out = c.post("/api/controls/emergency-stop").json()
    assert out["withdrawn"] >= 1 and rt.engine.paused and rt.cfg.auto_execute is False
    assert not any(d.status == "PROPOSED" for d in rt.engine.decisions.values())
    assert any("EMERGENCY STOP" in a["message"] for a in rt.repo.mem_audit)
    c.post("/api/controls/resume")
    assert rt.engine.paused is False and rt.cfg.auto_execute is False, "resume must not re-enable auto-approve"


def test_reset_restores_defaults_but_never_touches_the_safety_switches(api):
    c, rt = api
    c.post("/api/controls", json={"values": {"safety_z": 0.5, "auto_execute": True}})
    c.post("/api/controls/reset")
    assert rt.cfg.safety_z == 2.0 and rt.cfg.auto_execute is True


@pytest.mark.asyncio
async def test_auto_rules_cap_single_shipments_and_respect_minimum_severity(cfg, store):
    from app.db.repo import Repo
    from app.decision.engine import DecisionEngine

    store.snapshot = make_snapshot(hour=8, station_inv={"station-mirpur": (300, 900, 500), "station-tongi": (400, 500, 300)})
    eng = DecisionEngine(cfg, store, FakeClient(), Repo(None), "t")
    cfg.auto_execute, cfg.max_auto_liters, cfg.auto_max_single_l = True, 10**6, 1200
    await eng.cycle()
    sent = [d for d in eng.decisions.values() if d.status == "EXECUTED"]
    waiting = [d for d in eng.decisions.values() if d.status == "PROPOSED"]
    assert all(d.rec.quantity <= 1200 for d in sent) and any(d.rec.quantity > 1200 for d in waiting), "large shipments must wait for a person"
    eng2 = DecisionEngine(cfg, store, FakeClient(), Repo(None), "t2")
    cfg.auto_max_single_l, cfg.auto_min_severity = 10**6, "CRITICAL"
    await eng2.cycle()
    assert all(d.rec.severity == "CRITICAL" for d in eng2.decisions.values() if d.status == "EXECUTED")
    assert any(d.status == "PROPOSED" and d.rec.severity != "CRITICAL" for d in eng2.decisions.values()) or all(d.rec.severity == "CRITICAL" for d in eng2.decisions.values())


def test_reject_all_and_auth_status():
    app = create_app(Settings(database_url=None, api_key="k1", forecaster="seasonal"), start_background=False)
    with TestClient(app) as c:
        rt = app.state.rt
        rt.engine.client = FakeClient()
        rt.store.snapshot = make_snapshot(hour=8, station_inv=LOW)
        c.portal.call(rt.engine.cycle)
        assert c.get("/api/auth/status").json() == {"required": True, "valid": False}
        assert c.get("/api/auth/status", headers={"x-api-key": "k1"}).json()["valid"] is True
        assert c.post("/api/decisions/reject-all").status_code == 401
        out = c.post("/api/decisions/reject-all", headers={"x-api-key": "k1"}).json()
        assert out["rejected"] and not any(d.status == "PROPOSED" for d in rt.engine.decisions.values())
        assert c.post("/api/controls/emergency-stop").status_code == 401
