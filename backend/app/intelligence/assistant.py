"""Operations assistant: plain-language answers about the live situation.

Design rules (they are the point of the feature):
  * Grounded. Every answer is assembled from live FuelGrid data; nothing is invented.
  * Explains, never decides. It cannot approve, reject, or change anything.
  * Works with no outside AI service. If an API key is configured a language model may *reword* the answer, and its
    output is rejected (falling back to the grounded text) if it contains a number that is not in the facts."""
import json
import re

from app.core.logging import get_logger
from app.intelligence import briefing

log = get_logger("assistant")
NUM = re.compile(r"\d[\d,]*\.?\d*")


def _n(x: float) -> str:
    return f"{x:,.0f}"


def facts(rt) -> dict:
    snap, eng = rt.store.snapshot, rt.engine
    plan = eng.plan
    risks = [r for r in (plan.risks if plan else []) if r.severity != "OK"][:8]
    return {
        "tick": snap.tick if snap else None, "sim_time": str(snap.instance.sim_time) if snap else None,
        "service_level": round(snap.metrics.service_level, 4) if snap else None,
        "unmet_liters": round(snap.metrics.unmet_demand_liters) if snap else None,
        "risks": [{"station": r.station_id, "fuel": r.fuel, "severity": r.severity, "inventory": round(r.inventory),
                   "hours_to_stockout": None if r.hours_to_stockout is None else round(r.hours_to_stockout, 1),
                   "stockout_probability": round(r.stockout_prob, 2)} for r in risks],
        "pending": [{"id": d.id, "station": d.rec.station_id, "fuel": d.rec.fuel, "depot": d.rec.depot_id, "liters": round(d.rec.quantity),
                     "risk_before": round(d.rec.risk_before, 2), "risk_after": round(d.rec.risk_after, 2),
                     "confidence": round(d.rec.confidence, 2), "needs_review": d.rec.requires_review}
                    for d in eng.decisions.values() if d.status == "PROPOSED"][:12],
        "incidents": [{"type": i["type"], "message": i["message"], "since_tick": i.get("since_tick")} for i in eng.incidents.values()],
        "comparison_unmet_liters": plan.comparison if plan else {},
        "policy": plan.policy if plan else None, "fallback_active": bool(plan and plan.fallback_used),
        "rolled_back": rt.cfg.policy_rolled_back, "forecast_mape": eng.mape(),
    }


def _find(snap, text: str):
    sid = next((s for s in snap.stations if s.replace("station-", "") in text), None) if snap else None
    fuel = next((f for f in ("diesel", "petrol", "octane") if f in text), None)
    return sid, fuel.upper() if fuel else None


def grounded_answer(rt, question: str) -> str:
    q = question.lower()
    snap, eng = rt.store.snapshot, rt.engine
    if snap is None:
        return "I do not have any data yet."
    plan = eng.plan
    sid, fuel = _find(snap, q)
    m = re.search(r"#?\b(\d{1,5})\b", q)

    if any(w in q for w in ("why", "reason", "explain")) and (m or sid):
        cands = [d for d in eng.decisions.values() if d.status == "PROPOSED"]
        d = next((x for x in eng.decisions.values() if m and x.id == int(m.group(1))), None)
        if d is None and sid:
            d = next((x for x in cands if x.rec.station_id == sid and (fuel is None or x.rec.fuel == fuel)), None)
        if d:
            r = d.rec
            alts = [a for a in r.alternatives if a["feasible"]]
            txt = (f"Recommendation #{d.id}: send {_n(r.quantity)} L of {r.fuel.lower()} from {r.depot_id.replace('depot-', '')} to "
                   f"{snap.stations[r.station_id].name}. " + " ".join(x.rstrip(".") + "." for x in r.reasons[:4]))
            txt += f" It cuts the chance of running out from {r.risk_before:.0%} to {r.risk_after:.0%}."
            if alts:
                txt += " Other routes considered: " + "; ".join(f"{a['route_id'].replace('route-', '')} ({a['transit_ticks']} ticks)" for a in alts) + "."
            return txt
    if sid and any(w in q for w in ("risk", "stock", "fuel", "run out", "level", "status", "how")) and plan:
        rows = [r for r in plan.risks if r.station_id == sid and (fuel is None or r.fuel == fuel)]
        if rows:
            st = snap.stations[sid]
            return f"{st.name}: " + "; ".join(
                f"{r.fuel.lower()} {_n(r.inventory)} L, {r.severity.lower()}"
                + (f", about {r.hours_to_stockout:.1f} h left" if r.hours_to_stockout is not None else "")
                + f" (chance of running out {r.stockout_prob:.0%})" for r in rows) + "."
    if plan and any(w in q for w in ("risk", "shortage", "danger", "critical", "worst", "running out", "run out", "lowest", "at risk")):
        rows = [r for r in plan.risks if r.severity != "OK"][:5]
        if not rows:
            return "No station is at risk: every station has enough fuel for the next 8 hours."
        return f"{len(rows)} station and fuel combination(s) need attention: " + "; ".join(
            f"{snap.stations[r.station_id].name} {r.fuel.lower()} ({r.severity.lower()}, {_n(r.inventory)} L"
            + (f", about {r.hours_to_stockout:.1f} h left" if r.hours_to_stockout is not None else "")
            + f", {r.stockout_prob:.0%} chance of running out)" for r in rows) + "."
    if any(w in q for w in ("incident", "problem", "wrong", "happening", "crisis", "disrupt")):
        if not eng.incidents:
            return "There are no active incidents."
        out = [f"{len(eng.incidents)} active incident(s): " + "; ".join(i["message"] for i in eng.incidents.values()) + "."]
        for i in eng.incidents.values():
            if i.get("similar"):
                s0 = i["similar"][0]
                out.append(f"A similar past case: {s0['summary']}")
                break
        return " ".join(out)
    if any(w in q for w in ("compare", "better", "optimizer", "baseline", "do nothing", "benefit", "worth")) and plan and plan.comparison:
        c = plan.comparison
        parts = [f"doing nothing: {_n(c['none'])} L unmet"]
        for k, label in (("rules", "simple rules"), ("optimizer", "the optimizer")):
            if k in c:
                parts.append(f"{label}: {_n(c[k])} L")
        return "Expected unmet demand over the next 8 hours if we choose - " + ", ".join(parts) + "."
    if any(w in q for w in ("health", "system", "degraded", "working", "simulator", "database", "fallback")):
        bits = [f"Data source link: {'degraded (using cached data)' if rt.client.breaker_open or snap.stale else 'healthy'}",
                f"database: {'up' if rt.repo.up else 'buffering in memory'}",
                f"policy in use: {plan.policy if plan else 'none yet'}"]
        if rt.cfg.policy_rolled_back:
            bits.append("the optimizer was rolled back after repeated failures")
        elif plan and plan.fallback_used:
            bits.append("a backup planner is covering this cycle")
        return "; ".join(bits) + "."
    if any(w in q for w in ("recommend", "approve", "should", "next", "action", "send")):
        pend = [d for d in eng.decisions.values() if d.status == "PROPOSED"]
        if not pend:
            return "Nothing needs approval right now."
        top = sorted(pend, key=lambda d: -d.rec.quantity)[:4]
        return (f"{len(pend)} shipment(s) await approval, {_n(sum(d.rec.quantity for d in pend))} L in total. Largest: "
                + "; ".join(f"#{d.id} {_n(d.rec.quantity)} L {d.rec.fuel.lower()} to {snap.stations[d.rec.station_id].name}" for d in top) + ".")
    b = briefing.build(rt)
    return b["headline"] + ". " + " ".join(p["text"] for p in b["points"][:4])


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUM.findall(text)}


def numbers_are_grounded(candidate: str, sources: list[str]) -> bool:
    allowed = set().union(*[_numbers(s) for s in sources])
    return _numbers(candidate) <= allowed


async def ask(rt, question: str) -> dict:
    draft = grounded_answer(rt, question)
    f = facts(rt)
    router = rt.llm
    if not router.configured:
        return {"answer": draft, "mode": "grounded", "facts_used": len(f["risks"]) + len(f["pending"]) + len(f["incidents"])}
    facts_json = json.dumps(f, default=str)
    prompt = (
        "You are the FuelGrid operations assistant. Reword the DRAFT ANSWER so it is clear and friendly for a control-room "
        "operator. Use only information from FACTS and the DRAFT. Never add or change a number. You cannot take any "
        "action. Keep it under 90 words, plain language, no jargon.\n\n"
        f"QUESTION: {question}\nDRAFT ANSWER: {draft}\nFACTS: {facts_json}"
    )
    res = await router.complete(prompt, validate=lambda t: numbers_are_grounded(t, [draft, facts_json, question]))
    if res:
        return {"answer": res.text, "mode": "llm", "provider": res.provider, "model": res.model, "draft": draft}
    log.warning("assistant_llm_unavailable")
    return {"answer": draft, "mode": "grounded", "note": "language models unavailable or rejected; showing the built-in answer"}
