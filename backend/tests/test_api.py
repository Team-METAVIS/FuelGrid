import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_snapshot
from tests.test_engine import LOW, FakeClient


@pytest.fixture
def api():
    app = create_app(Settings(database_url=None), start_background=False)
    with TestClient(app) as c:
        rt = app.state.rt
        rt.engine.client = FakeClient()
        rt.store.snapshot = make_snapshot(hour=8, station_inv=LOW)
        c.portal.call(rt.engine.cycle)
        yield c, rt


def test_state_payload_is_complete(api):
    c, _ = api
    s = c.get("/api/state").json()
    assert s["ready"] and len(s["stations"]) == 4 and len(s["depots"]) == 2 and len(s["routes"]) == 6
    assert s["recommendations"] and s["plan"]["policy"] == "optimizer" and "none" in s["plan"]["comparison"]
    assert set(s["health"]["components"]) >= {"database", "data_source", "prediction", "decision_engine"}


def test_state_before_first_snapshot_is_not_ready():
    app = create_app(Settings(database_url=None), start_background=False)
    with TestClient(app) as c:
        assert c.get("/api/state").json()["ready"] is False


def test_approve_removes_recommendation_and_second_approve_is_a_clear_409(api):
    c, _ = api
    rec = c.get("/api/state").json()["recommendations"][0]
    ok = c.post(f"/api/decisions/{rec['id']}/approve")
    assert ok.status_code == 200 and ok.json()["status"] == "EXECUTED"
    assert rec["id"] not in [r["id"] for r in c.get("/api/state").json()["recommendations"]]
    again = c.post(f"/api/decisions/{rec['id']}/approve")
    assert again.status_code == 409 and "Already handled" in again.json()["detail"]
    assert c.post("/api/decisions/999999/approve").status_code == 404


def test_reject_and_approve_all(api):
    c, rt = api
    rt.store.snapshot = make_snapshot(hour=8, station_inv={"station-mirpur": (300, 900, 500), "station-tongi": (400, 500, 300), "station-karnaphuli": (500, 900, 400)})
    c.portal.call(rt.engine.cycle)
    recs = c.get("/api/state").json()["recommendations"]
    assert c.post(f"/api/decisions/{recs[0]['id']}/reject").json()["status"] == "REJECTED"
    done = c.post("/api/decisions/approve-all").json()
    assert done and all(d["status"] in ("EXECUTED", "FAILED") for d in done)
    assert c.get("/api/state").json()["recommendations"] == []
    hist = c.get("/api/decisions?limit=50").json()
    assert {d["status"] for d in hist} >= {"REJECTED"}


def test_settings_validation_and_rollback_restore(api):
    c, rt = api
    assert c.post("/api/settings", json={"policy": "nonsense"}).status_code == 422
    assert c.post("/api/settings", json={"forecaster": "seasonal_v1"}).json()["forecaster"] == "seasonal_v1"
    rt.cfg.policy_rolled_back = True
    rt.cfg.active_policy = "rules"
    out = c.post("/api/settings", json={"policy": "optimizer"}).json()
    assert out["policy"] == "optimizer" and out["rolled_back"] is False


def test_read_endpoints(api):
    c, _ = api
    assert c.get("/healthz").json() == {"status": "ok"}
    assert "fg_degraded" in c.get("/metrics").text
    assert c.get("/api/health").json()["build"]
    b = c.get("/api/briefing").json()
    assert b["headline"] and b["points"]
    f = c.get("/api/forecast?station_id=station-mirpur&fuel=DIESEL").json()
    assert len(f["forecast"]) == 32 and f["forecast"][0]["with_plan"] is not None and f["pending_liters"] > 0
    assert c.get("/api/forecast?station_id=nope&fuel=DIESEL").status_code == 404
    assert {s["name"] for s in c.get("/api/scenarios").json()} >= {"baseline", "combined_crisis"}
    assert c.get("/api/models").json()["forecasters"]
    assert isinstance(c.get("/api/events").json(), list)


def test_assistant_endpoint_and_input_validation(api):
    c, _ = api
    r = c.post("/api/assistant", json={"question": "which stations are at risk?"}).json()
    assert r["mode"] == "grounded" and "Mirpur" in r["answer"] or "mirpur" in r["answer"].lower()
    assert c.post("/api/assistant", json={"question": "x"}).status_code == 422
    assert c.post("/api/assistant", json={"question": "y" * 500}).status_code == 422


def test_write_endpoints_require_key_when_configured():
    app = create_app(Settings(database_url=None, api_key="secret"), start_background=False)
    with TestClient(app) as c:
        rt = app.state.rt
        rt.store.snapshot = make_snapshot(hour=8, station_inv=LOW)
        c.portal.call(rt.engine.cycle)
        assert c.post("/api/settings", json={"paused": True}).status_code == 401
        assert c.post("/api/settings", json={"paused": True}, headers={"X-API-Key": "secret"}).status_code == 200
        assert c.get("/api/state").status_code == 200  # reads stay open
