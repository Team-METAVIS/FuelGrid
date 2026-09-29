"""Plain-language situation briefing generated from live data.

Deterministic on purpose: it works with no outside AI service and can never invent numbers. A language model can be
layered on later to reword it, but it would only ever explain, never decide."""

def build(rt) -> dict:
    snap = rt.store.snapshot
    if snap is None:
        return {"headline": "Waiting for the simulator", "tone": "warn", "points": []}
    eng, plan = rt.engine, rt.engine.plan
    pts: list[dict] = []
    risks = plan.risks if plan else []
    crit = [r for r in risks if r.severity == "CRITICAL"]
    warn = [r for r in risks if r.severity == "WARNING"]
    tone = "bad" if crit else "warn" if warn or eng.incidents else "good"

    if crit:
        r = crit[0]
        st = snap.stations[r.station_id]
        left = f"about {r.hours_to_stockout:.1f} hours left" if r.hours_to_stockout is not None else "no stockout expected"
        pts.append({"kind": "risk", "text": f"{st.name} is close to running out of {r.fuel.lower()}: {r.inventory:,.0f} L on hand, {left}."})
        if len(crit) > 1:
            pts.append({"kind": "risk", "text": f"{len(crit) - 1} more fuel and station combination(s) are also critical."})
    elif warn:
        r = warn[0]
        st = snap.stations[r.station_id]
        pts.append({"kind": "risk", "text": f"{st.name} may run short of {r.fuel.lower()} within 8 hours "
                    f"(chance of running out {r.stockout_prob:.0%})."})
    else:
        pts.append({"kind": "ok", "text": "Every station has enough fuel for the next 8 hours."})

    for inc in list(eng.incidents.values())[:3]:
        pts.append({"kind": "incident", "text": inc["message"] + "."})

    props = [d for d in eng.decisions.values() if d.status == "PROPOSED"]
    if props:
        total = sum(d.rec.quantity for d in props)
        top = max(props, key=lambda d: d.rec.quantity)
        saved = sum(max(0.0, d.rec.unmet_before - d.rec.unmet_after) for d in props)
        pts.append({"kind": "action", "text": f"{len(props)} shipment(s) are waiting for your approval, {total:,.0f} L in total "
                    f"(largest: {top.rec.quantity:,.0f} L of {top.rec.fuel.lower()} to {snap.stations[top.rec.station_id].name}). "
                    f"Approving them avoids about {saved:,.0f} L of unmet demand."})
    else:
        pts.append({"kind": "ok", "text": "No shipments need approval right now."})

    cmp_ = plan.comparison if plan else {}
    if cmp_ and "none" in cmp_ and plan:
        none, mine = cmp_["none"], cmp_.get(plan.policy, 0)
        other = "rules" if plan.policy == "optimizer" else "optimizer"
        line = f"If we did nothing, about {none:,.0f} L of demand would go unserved over the next 8 hours; with this plan, about {mine:,.0f} L."
        if other in cmp_:
            line += f" The {'simple rule-based' if other == 'rules' else 'optimizing'} alternative would leave about {cmp_[other]:,.0f} L."
        pts.append({"kind": "compare", "text": line})

    h = rt.client
    if snap.stale or snap.age_s() > rt.cfg.stale_after_s or h.breaker.open:
        pts.append({"kind": "system", "text": "The simulator link is degraded. FuelGrid is showing the last good data and automatic dispatch is paused."})
    if rt.cfg.policy_rolled_back:
        pts.append({"kind": "system", "text": "The optimizer failed repeatedly, so the simpler rule-based planner has been switched on automatically."})
    elif plan and plan.fallback_used:
        pts.append({"kind": "system", "text": "The optimizer had a problem this cycle; a backup planner produced these recommendations."})

    sl = snap.metrics.service_level
    headline = (f"{len(crit)} critical shortage risk(s) — action needed" if crit else
                f"{len(warn)} station(s) at risk — review recommendations" if warn else
                "Network is stable" if not eng.incidents else "Network stable, incidents being monitored")
    pts.append({"kind": "metric", "text": f"Service level so far: {sl:.1%} ({snap.metrics.unmet_demand_liters:,.0f} L unmet, "
                f"{snap.metrics.served_demand_liters:,.0f} L served)."})
    return {"headline": headline, "tone": tone, "points": pts, "tick": snap.tick}
