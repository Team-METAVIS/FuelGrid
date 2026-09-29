import { Check, ChevronDown, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import type { Decision } from "../lib/api";
import { hours, liters, pct, shortId } from "../lib/format";
import { useLive } from "../lib/live";
import { Button, SevBadge } from "./ui";

export default function RecommendationCard({ d, compact }: { d: Decision; compact?: boolean }) {
  const { decide, state } = useLive();
  const [open, setOpen] = useState(false);
  const st = state?.stations.find((s) => s.id === d.station_id);
  const reduction = d.risk_before > 0 ? Math.max(0, (d.risk_before - d.risk_after) / d.risk_before) : 0;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-slate-900">{st?.name ?? shortId(d.station_id)}</span>
            <span className="text-xs text-slate-500">· {d.fuel}</span>
            <SevBadge sev={d.severity} />
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <span className="tabular text-xl font-semibold text-slate-900">{liters(d.quantity)}</span>
            <span className="text-xs text-slate-500">from {shortId(d.depot_id)} via {shortId(d.route_id)}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[11px] text-slate-500">Stockout risk</div>
          <div className="tabular text-sm font-semibold text-slate-900">{pct(d.risk_before)} <span className="text-slate-400">→</span> <span className="text-emerald-600">{pct(d.risk_after)}</span></div>
          {reduction > 0.01 && <div className="text-[11px] font-medium text-emerald-600">−{Math.round(reduction * 100)}% risk</div>}
        </div>
      </div>

      <dl className="tabular mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-4">
        <div><dt className="text-slate-500">Stockout in</dt><dd className="font-medium text-slate-800">{hours(d.hours_to_stockout)}</dd></div>
        <div><dt className="text-slate-500">On hand</dt><dd className="font-medium text-slate-800">{liters(d.inventory)}</dd></div>
        <div><dt className="text-slate-500">Expected demand</dt><dd className="font-medium text-slate-800">{liters(d.demand_horizon)}</dd></div>
        <div><dt className="text-slate-500">Unmet avoided</dt><dd className="font-medium text-slate-800">{liters(Math.max(0, d.unmet_before - d.unmet_after))}</dd></div>
      </dl>

      {d.requires_review && (
        <div className="mt-3 flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-inset ring-amber-200">
          <ShieldAlert size={14} /> Human review required — {d.review_reason} ({pct(d.confidence)} confidence)
        </div>
      )}

      {!compact && (
        <>
          <button onClick={() => setOpen(!open)} className="mt-3 flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">
            <ChevronDown size={14} className={open ? "rotate-180 transition" : "transition"} /> Why this recommendation &amp; alternatives
          </button>
          {open && (
            <div className="mt-2 space-y-3 rounded-md bg-slate-50 p-3 text-xs">
              <ul className="list-disc space-y-1 pl-4 text-slate-700">{d.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
              <div>
                <div className="mb-1 font-medium text-slate-600">Alternatives considered</div>
                {d.alternatives.length === 0 && <div className="text-slate-500">No other routes serve this station.</div>}
                {d.alternatives.map((a: any) => (
                  <div key={a.route_id} className={a.feasible ? "text-slate-700" : "text-slate-400"}>
                    {shortId(a.route_id)} · {a.transit_ticks} ticks · depot stock {liters(a.depot_stock)} {a.feasible ? "" : `— unavailable (${a.why_not})`}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Button variant="primary" size="sm" icon={<Check size={14} />} onClick={() => decide(d.id, "approve", `Dispatch approved: ${liters(d.quantity)} ${d.fuel} to ${shortId(d.station_id)}`)}>Approve &amp; dispatch</Button>
        <Button variant="ghost" size="sm" icon={<X size={14} />} onClick={() => decide(d.id, "reject", "Recommendation rejected")}>Reject</Button>
        <span className="ml-auto text-[11px] text-slate-400">#{d.id} · {d.policy} · tick {d.tick}</span>
      </div>
    </div>
  );
}
