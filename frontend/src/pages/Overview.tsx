import { CheckCircle2, Droplets, Gauge, ShieldAlert, Sparkles, Truck, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { get } from "../lib/api";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import RecommendationCard from "../components/RecommendationCard";
import { Badge, Card, Empty, PageHeader, SevBadge, Stat } from "../components/ui";
import { fuelColor, hours, liters, n0, pct, shortId, title } from "../lib/format";
import { useLive } from "../lib/live";

export default function Overview() {
  const { state: s, timeline, approveAll } = useLive();
  const [brief, setBrief] = useState<any>(null);
  const tick = s?.instance.tick;
  const pend = s?.recommendations.length;
  useEffect(() => { get("/api/briefing").then(setBrief).catch(() => undefined); }, [tick, pend]);
  if (!s) return null;
  const cmp = s.plan?.comparison ?? {};
  const cmpRows = [
    { key: "none", label: "Do nothing", color: "bg-slate-300" },
    { key: "rules", label: "Rule-based baseline", color: "bg-sky-400" },
    { key: "optimizer", label: "FuelGrid optimizer", color: "bg-brand-600" },
  ].filter((r) => cmp[r.key] != null);
  const cmpMax = Math.max(1, ...cmpRows.map((r) => cmp[r.key]));
  const crit = s.risks.filter((r) => r.severity === "CRITICAL").length;
  const warn = s.risks.filter((r) => r.severity === "WARNING").length;
  const attention = s.risks.filter((r) => r.severity !== "OK").slice(0, 6);
  const inv = s.stations.map((st) => ({
    name: shortId(st.id),
    ...Object.fromEntries(Object.entries(st.fuels).map(([f, v]) => [f, Math.round((v.inventory / v.capacity) * 100)])),
  }));
  const tl = timeline.map((t) => ({ tick: t.tick, sl: +(t.service_level * 100).toFixed(2), unmet: Math.round(t.unmet) }));
  const sl = s.metrics.service_level;

  return (
    <>
      <PageHeader title="Operations overview" description="Live view of the simulated national fuel network — observe, predict, decide." />

      {brief && (
        <Card className="mb-4" title={<span className="flex items-center gap-2"><Sparkles size={14} className="text-brand-600" />Situation briefing</span>} subtitle="Written automatically from live data � nothing here is invented">
          <div className={`mb-2 text-base font-semibold ${brief.tone === "bad" ? "text-rose-600" : brief.tone === "warn" ? "text-amber-600" : "text-emerald-600"}`}>{brief.headline}</div>
          <ul className="space-y-1.5 text-[13px] text-slate-700">
            {brief.points.map((p: any, i: number) => <li key={i} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300" />{p.text}</li>)}
          </ul>
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Service level" value={pct(sl, 1)} tone={sl > 0.98 ? "good" : sl > 0.93 ? "warn" : "bad"} icon={<Gauge size={15} />} hint={`${liters(s.metrics.unmet_demand_liters)} unmet so far`} />
        <Stat label="Critical / warning" value={<><span className={crit ? "text-rose-600" : ""}>{crit}</span><span className="text-slate-300"> / </span><span className={warn ? "text-amber-600" : ""}>{warn}</span></>} icon={<ShieldAlert size={15} />} hint="station × fuel at risk (8 h horizon)" />
        <Stat label="Pending decisions" value={s.recommendations.length} icon={<Zap size={15} />} hint={s.settings.auto_execute ? "Auto-execute is ON" : "Awaiting operator review"} />
        <Stat label="In transit" value={liters(s.in_transit.reduce((a, x) => a + x.quantity, 0))} icon={<Truck size={15} />} hint={`${s.in_transit.length} shipments`} />
        <Stat label="Fuel served" value={liters(s.metrics.served_demand_liters)} icon={<Droplets size={15} />} hint={`${liters(s.metrics.allocation_liters)} dispatched`} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Station inventory" subtitle="Fill level by fuel, % of tank capacity">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={inv} barGap={4} margin={{ left: -18, right: 4 }}>
                <CartesianGrid vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" tickLine={false} axisLine={false} />
                <YAxis domain={[0, 100]} unit="%" tickLine={false} axisLine={false} />
                <Tooltip cursor={{ fill: "#f1f5f9" }} formatter={(v: number) => `${v}%`} />
                <Legend iconType="circle" iconSize={8} />
                {["DIESEL", "PETROL", "OCTANE"].map((f) => <Bar key={f} dataKey={f} fill={fuelColor[f]} radius={[4, 4, 0, 0]} maxBarSize={28} />)}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Needs attention" subtitle="Highest projected shortage risk" action={<Link to="/network" className="text-xs font-medium text-brand-600">Network →</Link>} pad={false}>
          {attention.length === 0 ? (
            <Empty icon={<CheckCircle2 size={28} />} title="All stations within safe cover" text="No stockout is projected inside the 8-hour horizon." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {attention.map((r) => (
                <li key={r.station_id + r.fuel} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div>
                    <div className="text-[13px] font-medium text-slate-900">{shortId(r.station_id)} · {title(r.fuel.toLowerCase())}</div>
                    <div className="text-xs text-slate-500">{liters(r.inventory)} on hand · P(stockout) {pct(r.stockout_prob)}</div>
                  </div>
                  <div className="text-right"><SevBadge sev={r.severity} /><div className="tabular mt-1 text-xs text-slate-500">{r.hours_to_stockout != null ? hours(r.hours_to_stockout) : "no stockout"}</div></div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Service level & unmet demand" subtitle="Cumulative, from simulator ground truth">
          <div className="h-56">
            {tl.length < 2 ? <Empty title="Collecting data…" text="Advance the simulation to see the trend." /> : (
              <ResponsiveContainer>
                <LineChart data={tl} margin={{ left: -10, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="tick" tickLine={false} axisLine={false} />
                  <YAxis yAxisId="l" domain={[80, 100]} unit="%" tickLine={false} axisLine={false} />
                  <YAxis yAxisId="r" orientation="right" tickLine={false} axisLine={false} />
                  <Tooltip />
                  <Legend iconType="circle" iconSize={8} />
                  <Line yAxisId="l" type="monotone" dataKey="sl" name="Service level %" stroke="#10b981" strokeWidth={2} dot={false} />
                  <Line yAxisId="r" type="monotone" dataKey="unmet" name="Unmet (L)" stroke="#f43f5e" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <Card title="Live plan comparison" subtitle="Expected unmet demand over the next 8 h, same state, three choices">
          {cmpRows.length === 0 ? <Empty title="Waiting for the first plan" /> : (
            <div className="space-y-3">
              {cmpRows.map((r) => (
                <div key={r.key}>
                  <div className="mb-1 flex justify-between text-xs"><span className="font-medium text-slate-700">{r.label}</span><span className="tabular text-slate-500">{liters(cmp[r.key])}</span></div>
                  <div className="h-2.5 rounded-full bg-slate-100"><div className={`h-full rounded-full ${r.color} transition-all duration-500`} style={{ width: `${Math.max(1.5, (cmp[r.key] / cmpMax) * 100)}%` }} /></div>
                </div>
              ))}
              <p className="pt-1 text-[11px] text-slate-400">Counterfactual roll-forward of each choice; the active policy is {s.plan?.policy}.</p>
            </div>
          )}
        </Card>

        <Card title="Active incidents" subtitle="Detected from simulator state" pad={false}>
          {s.incidents.length === 0 ? <Empty icon={<CheckCircle2 size={28} />} title="No active incidents" /> : (
            <ul className="divide-y divide-slate-100">
              {s.incidents.slice(0, 6).map((i) => (
                <li key={i.key} className="px-5 py-3">
                  <div className="flex items-center gap-2"><Badge tone={i.severity === "high" ? "red" : "amber"}>{title(i.type)}</Badge><span className="text-[11px] text-slate-400">since tick {i.since_tick}</span></div>
                  <div className="mt-1 text-xs text-slate-600">{i.message}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card
        className="mt-4"
        title="Recommended allocations"
        subtitle="Optimizer output awaiting operator approval"
        action={s.recommendations.length > 1 ? <button className="text-xs font-medium text-brand-600" onClick={approveAll}>Approve all ({s.recommendations.length})</button> : <Link to="/recommendations" className="text-xs font-medium text-brand-600">History →</Link>}
      >
        {s.recommendations.length === 0 ? (
          <Empty icon={<CheckCircle2 size={28} />} title="No action needed" text={`Network is within safe cover (${n0(s.metrics.allocation_liters)} L dispatched to date).`} />
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">{s.recommendations.slice(0, 4).map((d) => <RecommendationCard key={d.id} d={d} />)}</div>
        )}
      </Card>
    </>
  );
}
