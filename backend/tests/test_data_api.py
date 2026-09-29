from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_snapshot
from tests.test_engine import FakeClient


def boot():
    app = create_app(Settings(database_url=None, forecaster="seasonal"), start_background=False)
    return app, TestClient(app)


def test_resource_endpoints_return_the_canonical_world():
    app, c = boot()
    with c:
        rt = app.state.rt
        assert c.get("/api/v1/stations").status_code == 503  # nothing received yet
        assert c.get("/readyz").status_code == 503
        rt.store.snapshot = make_snapshot(hour=8)
        assert c.get("/readyz").json()["ready"] is True
        assert {s["id"] for s in c.get("/api/v1/stations").json()} >= {"station-mirpur"}
        assert c.get("/api/v1/stations/station-mirpur").json()["id"] == "station-mirpur"
        assert c.get("/api/v1/stations/nope").status_code == 404
        assert c.get("/api/v1/depots").json() and c.get("/api/v1/depots/depot-gazipur").status_code == 200
        assert c.get("/api/v1/depots/nope").status_code == 404
        assert c.get("/api/v1/routes").json()
        assert isinstance(c.get("/api/v1/supply-arrivals").json(), list) and isinstance(c.get("/api/v1/events").json(), list)
        assert "service_level" in c.get("/api/v1/metrics").json() and "tick" in c.get("/api/v1/instance").json()
        assert c.get("/api/v1/allocations").json() == []
        assert c.get("/api/v1/demand-history?limit=0").status_code == 422


def test_demand_history_filters_and_orders_newest_first():
    app, c = boot()
    with c:
        rt = app.state.rt
        rt.store.snapshot = make_snapshot(hour=8)
        t = rt.store.snapshot.instance.sim_time
        for tick in range(1, 6):
            rt.store.demand[("station-mirpur", "DIESEL")][tick] = (10.0 * tick, 10.0 * tick, 0.0, t)
        rows = c.get("/api/v1/demand-history?station_id=station-mirpur&fuel=DIESEL&limit=3").json()
        assert [r["tick"] for r in rows] == [5, 4, 3] and rows[0]["demand_liters"] == 50.0
        assert c.get("/api/v1/demand-history?station_id=nope").status_code == 404


def test_manual_allocation_is_prechecked_idempotent_and_cancellable():
    app, c = boot()
    with c:
        rt = app.state.rt
        rt.engine.client = FakeClient()
        rt.store.snapshot = make_snapshot(hour=8)
        body = {"source_depot_id": "depot-gazipur", "destination_station_id": "station-mirpur", "route_id": "route-gazipur-mirpur",
                "fuel_type": "DIESEL", "quantity": 2000, "idempotency_key": "manual-1"}
        first = c.post("/api/v1/allocations", json=body)
        assert first.status_code == 201, first.text
        again = c.post("/api/v1/allocations", json=body)
        assert again.status_code == 201 and again.json()["decision_id"] == first.json()["decision_id"], "same key + same body = same result"
        assert c.post("/api/v1/allocations", json={**body, "quantity": 5}).status_code == 409, "same key, different body is refused"
        bad = c.post("/api/v1/allocations", json={**body, "idempotency_key": "m2", "quantity": 10_000_000})
        assert bad.status_code == 409 and bad.json()["detail"]["code"].startswith("PRECHECK"), "refused before anything is sent"
        assert c.post("/api/v1/allocations", json={**body, "idempotency_key": "m3", "route_id": "nope"}).status_code == 409
        assert c.post("/api/v1/allocations", json={**body, "quantity": -1}).status_code == 422
        assert c.post("/api/v1/allocations/424242/cancel").status_code == 404


def test_write_endpoints_require_the_api_key_when_one_is_set():
    app = create_app(Settings(database_url=None, forecaster="seasonal", api_key="s3cret"), start_background=False)
    with TestClient(app) as c:
        app.state.rt.store.snapshot = make_snapshot(hour=8)
        body = {"source_depot_id": "depot-gazipur", "destination_station_id": "station-mirpur", "route_id": "route-gazipur-mirpur", "fuel_type": "DIESEL", "quantity": 100}
        assert c.post("/api/v1/allocations", json=body).status_code == 401
        assert c.get("/api/v1/stations").status_code == 200


def test_cors_only_for_configured_origins_and_assistant_is_rate_limited():
    app = create_app(Settings(database_url=None, forecaster="seasonal", cors_origins="https://fuelgrid.example", assistant_per_minute=2), start_background=False)
    with TestClient(app) as c:
        ok = c.options("/api/state", headers={"Origin": "https://fuelgrid.example", "Access-Control-Request-Method": "GET"})
        assert ok.headers.get("access-control-allow-origin") == "https://fuelgrid.example"
        other = c.options("/api/state", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in other.headers
        app.state.rt.store.snapshot = make_snapshot(hour=8)
        codes = [c.post("/api/assistant", json={"question": "how are we doing"}).status_code for _ in range(3)]
        assert codes[-1] == 429 and codes[0] == 200
