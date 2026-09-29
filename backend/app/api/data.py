"""Versioned data API: the brief's core resource endpoints over FuelGrid's canonical model.

    GET  /api/v1/instance  /stations  /stations/{id}  /depots  /depots/{id}  /routes  /supply-arrivals
         /demand-history  /events  /allocations  /metrics  /regions
    POST /api/v1/allocations                 manual dispatch (same precheck, idempotency and audit as recommendations)
    POST /api/v1/allocations/{id}/cancel

These return what FuelGrid currently knows, from whichever data source is active (simulator or live feed), in one
consistent shape. They are read-only views of the platform's state; writes go through the decision engine."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.feed import guard, rt

router = APIRouter(prefix="/api/v1", tags=["data"])


def snap_of(r):
    snap = r.store.snapshot
    if snap is None:
        raise HTTPException(503, "no data received from the data source yet")
    return snap


@router.get("/instance")
async def instance(r=Depends(rt)):
    """The world instance: scenario, current tick, tick length, the active data source and how old the snapshot is."""
    s = snap_of(r)
    return {**s.instance.model_dump(mode="json"), "source": r.client.kind, "snapshot_age_s": round(s.age_s(), 2), "stale": s.stale}


@router.get("/regions")
async def regions(r=Depends(rt)):
    """Regions and their demand factors."""
    return [{"id": k, "demand_factor": v} for k, v in r.store.regions.items()]


@router.get("/stations")
async def stations(region_id: str | None = None, r=Depends(rt)):
    """All stations with capacity and current inventory per fuel; filter by region_id."""
    return [s.model_dump(mode="json") for s in snap_of(r).stations.values() if region_id in (None, s.region_id)]


@router.get("/stations/{sid}")
async def station(sid: str, r=Depends(rt)):
    """One station."""
    s = snap_of(r).stations.get(sid)
    if s is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": f"unknown station {sid}"})
    return s.model_dump(mode="json")


@router.get("/depots")
async def depots(r=Depends(rt)):
    """All depots with dispatch capacity and current stock per fuel."""
    return [d.model_dump(mode="json") for d in snap_of(r).depots.values()]


@router.get("/depots/{did}")
async def depot(did: str, r=Depends(rt)):
    """One depot."""
    d = snap_of(r).depots.get(did)
    if d is None:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": f"unknown depot {did}"})
    return d.model_dump(mode="json")


@router.get("/routes")
async def routes(r=Depends(rt)):
    """All roads between depots and stations: transit time, maximum shipment, status."""
    return [x.model_dump(mode="json") for x in snap_of(r).routes.values()]


@router.get("/supply-arrivals")
async def supply_arrivals(status: str | None = None, r=Depends(rt)):
    """Supply deliveries into depots (planned and actual tick, status); filter by status."""
    return [a.model_dump(mode="json") for a in sorted(snap_of(r).arrivals, key=lambda a: a.planned_tick) if status in (None, a.status)]


@router.get("/events")
async def world_events(status: str | None = None, r=Depends(rt)):
    """Crisis and disruption events of the world (not FuelGrid's own activity feed, which is /api/events)."""
    return [e.model_dump(mode="json") for e in snap_of(r).events if status in (None, e.status)]


@router.get("/demand-history")
async def demand_history(station_id: str | None = None, fuel: str | None = None, limit: int = Query(200, ge=1, le=2000), r=Depends(rt)):
    """Most recent demand observations (newest first), optionally for one station and/or fuel. limit is clamped to 1..2000."""
    s = snap_of(r)
    rows = []
    for (sid, f), series in r.store.demand.items():
        if station_id not in (None, sid) or fuel not in (None, f):
            continue
        for tick, (demand, served, unmet, t) in series.items():
            rows.append({"station_id": sid, "fuel_type": f, "tick": tick, "sim_time": t.isoformat(), "demand_liters": round(demand, 3),
                         "served_liters": round(served, 3), "unmet_liters": round(unmet, 3)})
    if station_id and station_id not in s.stations:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": f"unknown station {station_id}"})
    rows.sort(key=lambda x: (x["tick"], x["station_id"], x["fuel_type"]), reverse=True)
    return rows[:limit]


@router.get("/allocations")
async def allocations(status: str | None = None, limit: int = Query(200, ge=1, le=2000), r=Depends(rt)):
    """Allocations (shipments), newest first; filter by status."""
    return [a.model_dump(mode="json") for a in sorted(snap_of(r).allocations, key=lambda a: -a.id) if status in (None, a.status)][:limit]


@router.get("/metrics")
async def metrics(r=Depends(rt)):
    """Network service metrics: served and unmet demand, service level, allocated liters, failures."""
    s = snap_of(r)
    return {**s.metrics.model_dump(), "tick": s.tick, "fuels": s.fuels}


class AllocationIn(BaseModel):
    source_depot_id: str
    destination_station_id: str
    route_id: str
    fuel_type: str = Field(min_length=1, max_length=40)
    quantity: float = Field(gt=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=150)


@router.post("/allocations", status_code=201, dependencies=[Depends(guard)])
async def create_allocation(body: AllocationIn, request: Request, r=Depends(rt)):
    """Manual dispatch. Validated against the source's rules before sending; the same key with the same body returns the same result."""
    try:
        d = await r.engine.manual(body.model_dump(), actor="operator-api")
    except ValueError as e:
        raise HTTPException(409, {"code": "REJECTED", "message": str(e)}) from None
    if d.status == "FAILED":
        raise HTTPException(409, {"code": d.result or "FAILED", "message": "the allocation was refused; nothing was sent", "decision_id": d.id})
    if d.status != "EXECUTED":
        raise HTTPException(503, {"code": "SOURCE_UNAVAILABLE", "message": "the data source did not accept the allocation yet; it will be retried", "decision_id": d.id})
    a = next((x for x in r.store.snapshot.allocations if x.id == d.sim_allocation_id), None)
    return {"decision_id": d.id, "allocation": a.model_dump(mode="json") if a else {"id": d.sim_allocation_id, "status": d.result}}


@router.post("/allocations/{alloc_id}/cancel", dependencies=[Depends(guard)])
async def cancel_allocation(alloc_id: int, r=Depends(rt)):
    """Cancel an allocation FuelGrid created, if it has not departed yet."""
    d = next((x for x in r.engine.decisions.values() if x.sim_allocation_id == alloc_id), None)
    if d is None:
        raise HTTPException(404, {"code": "ALLOCATION_NOT_FOUND", "message": "no FuelGrid decision created this allocation"})
    try:
        return (await r.engine.cancel(d.id, actor="operator-api")).to_dict()
    except ValueError as e:
        raise HTTPException(409, {"code": "CANNOT_CANCEL", "message": str(e)}) from None
