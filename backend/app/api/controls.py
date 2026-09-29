"""Operator controls: every knob an operator needs to run the platform for real, validated, audited and persisted.

Design rules:
  * Declarative: each control has a type, range, default, group and help text, so the console renders itself from
    `/api/controls` and bad values are refused server-side (never trust the browser).
  * Every change is written to the audit log with old and new value, and saved to Supabase so it survives a restart.
  * Safety first: after a restart, automatic dispatch is deliberately left OFF (and the audit log says so) until a person
    switches it on again.
  * A single emergency stop halts planning and auto-dispatch and withdraws pending recommendations."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.feed import guard, key_ok, rt

router = APIRouter(prefix="/api")

SEVERITIES = ["OK", "WATCH", "WARNING", "CRITICAL"]

# key, label, group, kind, extra, help ------------------------------------------------------------------------------
CONTROLS: list[dict] = [
    # -- engine
    {"key": "paused", "label": "Pause the decision engine", "group": "Engine", "kind": "bool", "target": "engine",
     "help": "Stops planning and dispatch. The console keeps showing live data."},
    {"key": "decision_every_ticks", "label": "Re-plan every N ticks", "group": "Engine", "kind": "number", "min": 1, "max": 24, "step": 1,
     "help": "How often a new plan is computed. Lower reacts faster; higher is calmer."},
    {"key": "horizon_ticks", "label": "Forecast horizon (ticks)", "group": "Engine", "kind": "number", "min": 8, "max": 64, "step": 4,
     "help": "How far ahead demand and shortage risk are projected."},
    # -- approvals
    {"key": "auto_execute", "label": "Auto-approve and dispatch", "group": "Approvals", "kind": "bool",
     "help": "OFF: every shipment waits for a person. ON: shipments inside the rules below are sent automatically."},
    {"key": "max_auto_liters", "label": "Auto-approve budget per cycle (L)", "group": "Approvals", "kind": "number", "min": 0, "max": 200000, "step": 1000,
     "help": "Total liters that may be auto-dispatched in one planning cycle."},
    {"key": "auto_max_single_l", "label": "Largest auto-approved shipment (L)", "group": "Approvals", "kind": "number", "min": 0, "max": 50000, "step": 500,
     "help": "A single shipment above this always needs a human decision."},
    {"key": "min_confidence", "label": "Minimum forecast confidence for auto", "group": "Approvals", "kind": "number", "min": 0, "max": 1, "step": 0.05,
     "help": "Recommendations based on shakier forecasts are always sent to a person."},
    {"key": "auto_min_severity", "label": "Auto-approve only from severity", "group": "Approvals", "kind": "select", "options": SEVERITIES,
     "help": "OK = everything; CRITICAL = only emergencies are automatic, the rest wait for a person."},
    # -- planning
    {"key": "active_policy", "label": "Decision policy", "group": "Planning", "kind": "select", "options": ["optimizer", "rules"],
     "help": "optimizer = OR-Tools plan under all limits; rules = simple greedy baseline (also the automatic fallback)."},
    {"key": "target_cover_ticks", "label": "Fuel cover target (ticks)", "group": "Planning", "kind": "number", "min": 8, "max": 64, "step": 4,
     "help": "How many ticks of demand each station should be stocked for after a delivery."},
    {"key": "safety_z", "label": "Safety buffer (std-devs)", "group": "Planning", "kind": "number", "min": 0, "max": 3, "step": 0.25,
     "help": "Extra stock held against forecast error. Higher = fewer stock-outs, more fuel in transit."},
    {"key": "depot_reserve_frac", "label": "Depot reserve", "group": "Planning", "kind": "number", "min": 0, "max": 0.5, "step": 0.05,
     "help": "Share of each depot's tank held back unless a station is about to run out."},
    # -- model
    {"key": "forecaster", "label": "Demand model", "group": "Model", "kind": "select", "options": ["learned", "seasonal", "seasonal_v1", "moving_avg"],
     "help": "learned = the trained model (default). seasonal = hand-set expert profile (simulator-specific). moving_avg = last-resort."},
    {"key": "online_adaptation", "label": "Online adaptation", "group": "Model", "kind": "bool",
     "help": "Correct the forecast within a few ticks when demand shifts, before any retraining."},
    {"key": "auto_retrain", "label": "Automatic retraining", "group": "Model", "kind": "bool",
     "help": "Periodically train a challenger on collected data; it replaces the champion only if clearly better."},
    {"key": "retrain_every_ticks", "label": "Retrain every N ticks", "group": "Model", "kind": "number", "min": 96, "max": 5000, "step": 48,
     "help": "Schedule for challenger training. Drift also triggers it."},
    # -- resilience
    {"key": "stale_after_s", "label": "Treat data as stale after (s)", "group": "Resilience", "kind": "number", "min": 3, "max": 600, "step": 1,
     "help": "Snapshots older than this suspend auto-dispatch and show a degraded banner."},
    {"key": "rollback_after", "label": "Roll back optimizer after N failed cycles", "group": "Resilience", "kind": "number", "min": 1, "max": 10, "step": 1,
     "help": "Consecutive optimizer failures before the rule-based policy takes over."},
]
BY_KEY = {c["key"]: c for c in CONTROLS}
DEFAULTS: dict = {}


def _current(r, c):
    return r.engine.paused if c["key"] == "paused" else getattr(r.cfg, c["key"])


def snapshot_defaults(r) -> None:
    if not DEFAULTS:
        for c in CONTROLS:
            DEFAULTS[c["key"]] = _current(r, c)


def _apply(r, key: str, value) -> None:
    if key == "paused":
        r.engine.paused = bool(value)
    else:
        setattr(r.cfg, key, value)


def _coerce(c: dict, v):
    if c["kind"] == "bool":
        if not isinstance(v, bool):
            raise ValueError("must be true or false")
        return v
    if c["kind"] == "number":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("must be a number")
        if not (c["min"] <= v <= c["max"]):
            raise ValueError(f"must be between {c['min']} and {c['max']}")
        return int(v) if float(c.get("step", 1)).is_integer() and float(v).is_integer() else float(v)
    if v not in c["options"]:
        raise ValueError(f"must be one of {c['options']}")
    return v


def describe(r) -> dict:
    snapshot_defaults(r)
    groups: dict[str, list] = {}
    for c in CONTROLS:
        item = {k: v for k, v in c.items() if k != "target"}
        item["value"], item["default"] = _current(r, c), DEFAULTS[c["key"]]
        groups.setdefault(c["group"], []).append(item)
    return {"groups": [{"name": n, "controls": v} for n, v in groups.items()], "auth_required": bool(r.cfg.api_key),
            "engine": {"paused": r.engine.paused, "pending": sum(1 for d in r.engine.decisions.values() if d.status == "PROPOSED"),
                       "last_cycle_ms": round(r.engine.last_cycle_ms, 1)}}


async def persist(r, key: str, value) -> None:
    if r.repo.url:
        r.repo.enqueue("insert into fg_settings (key, value) values (:k, cast(:v as jsonb)) on conflict (key) do update set value = excluded.value, updated_at = now()",
                       {"k": key, "v": json.dumps(value)})


async def restore(r) -> int:
    """Load persisted settings at startup. Auto-dispatch is never re-enabled automatically."""
    if not r.repo.up:
        return 0
    snapshot_defaults(r)
    rows = await r.repo.fetch("select key, value from fg_settings")
    n, was_auto = 0, False
    for row in rows:
        c = BY_KEY.get(row["key"])
        if not c:
            continue
        v = row["value"]
        try:
            v = _coerce(c, v)
        except ValueError:
            continue
        if c["key"] == "auto_execute" and v:
            was_auto = True
            continue
        _apply(r, c["key"], v)
        n += 1
    if was_auto:
        r.repo.audit(r.run_id, "operator", "Auto-approve was ON before the restart; it was left OFF for safety. Switch it on again if intended.", "warn")
    return n


class Change(BaseModel):
    values: dict


@router.get("/controls")
async def get_controls(r=Depends(rt)):
    return describe(r)


@router.post("/controls", dependencies=[Depends(guard)])
async def set_controls(body: Change, r=Depends(rt)):
    snapshot_defaults(r)
    errors, changed = {}, {}
    for k, v in body.values.items():
        c = BY_KEY.get(k)
        if not c:
            errors[k] = "unknown control"
            continue
        try:
            nv = _coerce(c, v)
        except ValueError as e:
            errors[k] = str(e)
            continue
        old = _current(r, c)
        if nv != old:
            _apply(r, k, nv)
            changed[k] = (old, nv)
            await persist(r, k, nv)
    if errors and not changed:
        raise HTTPException(422, "; ".join(f"{k}: {m}" for k, m in errors.items()))
    for k, (old, nv) in changed.items():
        r.repo.audit(r.run_id, "operator", f"Control changed: {BY_KEY[k]['label']}: {old} -> {nv}", "warn" if k in ("auto_execute", "paused") else "info")
    if changed:
        r.engine.version += 1
        r.bus.publish("controls", changed={k: v[1] for k, v in changed.items()})
    return {"changed": {k: v[1] for k, v in changed.items()}, "errors": errors, **describe(r)}


@router.post("/controls/reset", dependencies=[Depends(guard)])
async def reset_controls(r=Depends(rt)):
    snapshot_defaults(r)
    for c in CONTROLS:
        if c["key"] in ("paused", "auto_execute"):
            continue  # never silently change the two safety switches
        _apply(r, c["key"], DEFAULTS[c["key"]])
        await persist(r, c["key"], DEFAULTS[c["key"]])
    r.repo.audit(r.run_id, "operator", "All tuning controls reset to defaults", "info")
    r.engine.version += 1
    return describe(r)


@router.post("/controls/emergency-stop", dependencies=[Depends(guard)])
async def emergency_stop(r=Depends(rt)):
    """One button: stop planning, stop auto-dispatch, withdraw pending recommendations."""
    r.engine.paused = True
    r.cfg.auto_execute = False
    withdrawn = 0
    for d in r.engine.decisions.values():
        if d.status == "PROPOSED":
            d.status, d.result = "EXPIRED", "emergency stop"
            withdrawn += 1
    await persist(r, "paused", True)
    await persist(r, "auto_execute", False)
    r.repo.audit(r.run_id, "operator", f"EMERGENCY STOP: engine paused, auto-approve off, {withdrawn} pending recommendation(s) withdrawn", "error")
    r.engine.version += 1
    r.bus.publish("controls", changed={"paused": True, "auto_execute": False})
    return {"ok": True, "withdrawn": withdrawn, **describe(r)}


@router.post("/controls/resume", dependencies=[Depends(guard)])
async def resume(r=Depends(rt)):
    r.engine.paused = False
    await persist(r, "paused", False)
    r.engine.last_cycle_tick = -999  # plan immediately on the next snapshot
    r.repo.audit(r.run_id, "operator", "Decision engine resumed (auto-approve remains as configured)", "info")
    r.engine.version += 1
    return describe(r)


@router.post("/decisions/reject-all", dependencies=[Depends(guard)])
async def reject_all(r=Depends(rt)):
    out = []
    for d in list(r.engine.decisions.values()):
        if d.status == "PROPOSED":
            out.append(r.engine.reject(d.id).id)
    return {"rejected": out}


@router.get("/auth/status")
async def auth_status(request: Request, r=Depends(rt)):
    """Lets the console know whether write actions need an API key and whether the key it holds works."""
    key = request.headers.get("x-api-key")
    return {"required": bool(r.cfg.api_key), "valid": key_ok(r.cfg.api_key, key)}
