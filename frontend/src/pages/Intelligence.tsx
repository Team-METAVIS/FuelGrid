import { useEffect, useState } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, Empty, PageHeader, Stat, Td, Th } from "../components/ui";
import { get } from "../lib/api";
import { liters, n0, pct, shortId, title } from "../lib/format";
import { useLive } from "../lib/live";

const POLICY_COLOR: Record<string, string> = { none: "#cbd5e1", rules: "#0ea5e9", optimizer: "#4f46e5" };

export default function Intelligence() {
  const { state: s } = useLive();
  const [sid, setSid] = useState("station-mirpur");
  const [fuel, setFuel] = useState("DIESEL");
  const [fc, setFc] = useState<any>(null);
  const [bench, setBench] = useState<any>(null);
  const [scn, setScn] = useState("combined_crisis");
  const tick = s?.instance.tick;

  useEffect(() => { get("/api/benchmarks").then(setBench).catch(() => undefined); }, []);
  useEffect(() => { get(`/api/forecast?station_id=${sid}&fuel=${fuel}`).then(setFc).catch(() => setFc(null)); }, [sid, fuel, tick]);
  if (!s) return null;

  const chart = fc ? [
    ...fc.history.map((h: any) => ({ tick: h.tick, observed: h.demand })),
    ...fc.forecast.map((f: any) => ({ tick: f.tick, forecast: f.demand, band: [f.lo, f.hi], inventory: f.inventory })),
  ] : [];
  const invChart = fc ? fc.forecast.map((f: any) => ({ tick: f.tick, inventory: f.inventory, with_plan: f.with_plan })) : [];

  const results: any[] = bench?.results ?? [];
  const scenarios = [...new Set(results.map((r) => r.scenario))];
  const benchRows = scenarios.map((sc) => Object.fromEntries([["scenario", title(sc)], ...results.filter((r) => r.scenario === sc).map((r) => [r.policy, +(r.service_level * 100).toFixed(2)])]));
  const sel = results.filter((r) => r.scenario === scn);

  return (
    <>
      <PageHeader title="Forecast & models" description="Demand forecasting with uncertainty, projected inventory, and measured decision quality." />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Forecaster" value={<span className="text-lg">{s.plan?.forecast_model ?? "—"}</span>} hint="Hour-of-day prior × online-calibrated level" />
        <Stat label="Forecast error (MAPE)" value={pct(s.health.components.prediction.mape ?? null, 1)} hint="One-step-ahead, rolling window" tone="good" />
        <Stat label="Decision policy" value={<span className="text-lg">{s.plan?.policy ?? "—"}</span>} hint={`Solver ${s.plan?.solver_status ?? "—"} · ${s.plan ? Math.round(s.plan.runtime_ms) : 0} ms`} />
        <Stat label="Fallback" value={s.plan?.fallback_used ? "ACTIVE" : "Standby"} tone={s.plan?.fallback_used ? "warn" : "good"} hint="Rule-based policy if the optimizer fails" />
      </div>

      <Card className="mt-4" title="Demand forecast & inventory projection" subtitle="Observed demand (solid), forecast with 80% band, and projected inventory including in-flight supply"
        action={
          <div className="flex gap-2 text-xs">
            <select className="rounded-md border border-slate-300 bg-white px-2 py-1" value={sid} onChange={(e) => setSid(e.target.value)}>{s.stations.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
            <select className="rounded-md border border-slate-300 bg-white px-2 py-1" value={fuel} onChange={(e) => setFuel(e.target.value)}>{["DIESEL", "PETROL", "OCTANE"].map((f) => <option key={f}>{f}</option>)}</select>
          </div>
        }>
        {!fc ? <Empty title="Loading forecast…" /> : (
          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <div className="mb-2 flex items-center gap-2 text-xs text-slate-500">Demand per tick (L) <Badge tone="indigo">confidence {pct(fc.confidence)}</Badge><Badge tone={fc.level > 1.3 ? "amber" : "slate"}>level ×{fc.level.toFixed(2)}</Badge></div>
              <div className="h-60">
                <ResponsiveContainer>
                  <ComposedChart data={chart} margin={{ left: -12, right: 6 }}>
                    <CartesianGrid vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="tick" tickLine={false} axisLine={false} />
                    <YAxis tickLine={false} axisLine={false} />
                    <Tooltip />
                    <ReferenceLine x={fc.tick} stroke="#94a3b8" strokeDasharray="3 3" label={{ value: "now", fontSize: 10, fill: "#64748b" }} />
                    <Area dataKey="band" name="80% band" stroke="none" fill="#6366f1" fillOpacity={0.12} />
                    <Line dataKey="observed" name="Observed" stroke="#0f172a" strokeWidth={1.8} dot={false} connectNulls />
                    <Line dataKey="forecast" name="Forecast" stroke="#4f46e5" strokeWidth={2} strokeDasharray="5 3" dot={false} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div>
              <div className="mb-2 flex items-center gap-2 text-xs text-slate-500">Projected inventory (L) {fc.ticks_to_stockout != null ? <Badge tone="red">stockout in {(fc.ticks_to_stockout * s.instance.tick_minutes / 60).toFixed(1)} h</Badge> : <Badge tone="green">no stockout in horizon</Badge>}</div>
              <div className="h-60">
                <ResponsiveContainer>
                  <ComposedChart data={invChart} margin={{ left: -12, right: 6 }}>
                    <CartesianGrid vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="tick" tickLine={false} axisLine={false} />
                    <YAxis domain={[0, fc.capacity]} tickLine={false} axisLine={false} />
                    <Tooltip formatter={(v: number) => liters(v)} />
                    <ReferenceLine y={0} stroke="#f43f5e" />
                    <Area dataKey="inventory" name="Current course" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.1} strokeWidth={2} />
                    {fc.pending_liters > 0 && <Area dataKey="with_plan" name="If pending shipments are approved" stroke="#10b981" fill="#10b981" fillOpacity={0.15} strokeWidth={2} />}
                    <Legend iconType="circle" iconSize={8} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Decision quality benchmark" subtitle={bench?.generated ? `Service level by policy on identical deterministic worlds · ${bench.ticks} ticks per run` : "Run the benchmark CLI to populate"}>
          {benchRows.length === 0 ? <Empty title="No benchmark results yet" text="python -m app.scenarios.cli --scenarios all" /> : (
            <div className="h-72">
              <ResponsiveContainer>
                <BarChart data={benchRows} margin={{ left: -6, right: 4 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="scenario" tickLine={false} axisLine={false} interval={0} />
                  <YAxis domain={[50, 100]} unit="%" tickLine={false} axisLine={false} />
                  <Tooltip formatter={(v: number) => `${v}%`} />
                  <Legend iconType="circle" iconSize={8} />
                  {["none", "rules", "optimizer"].map((p) => <Bar key={p} dataKey={p} name={p === "none" ? "No action" : p === "rules" ? "Rule-based" : "OR-Tools optimizer"} fill={POLICY_COLOR[p]} radius={[4, 4, 0, 0]} maxBarSize={30} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card title="Scenario detail" action={<select className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs" value={scn} onChange={(e) => setScn(e.target.value)}>{scenarios.map((x) => <option key={x} value={x}>{title(x)}</option>)}</select>} pad={false}>
          {sel.length === 0 ? <Empty title="No data" /> : (
            <table className="w-full"><thead><tr><Th>Policy</Th><Th right>Service</Th><Th right>Unmet L</Th><Th right>Cycle ms</Th></tr></thead>
              <tbody>{sel.map((r) => <tr key={r.policy}><Td>{r.policy}</Td><Td right className="font-medium">{pct(r.service_level, 2)}</Td><Td right>{n0(r.unmet_l)}</Td><Td right>{r.cycle_ms_avg}</Td></tr>)}</tbody></table>
          )}
        </Card>
      </div>

      <Card className="mt-4" title="Shortage risk by station and fuel" subtitle="Stockout probability over the next 8 hours, with the signals that drove each score" pad={false}>
        <div className="overflow-x-auto">
          <table className="w-full"><thead><tr><Th>Station</Th><Th>Fuel</Th><Th right>Inventory</Th><Th right>Incoming</Th><Th right>Expected demand</Th><Th right>P(stockout)</Th><Th right>Confidence</Th><Th>Signals</Th></tr></thead>
            <tbody>{s.risks.map((r) => (
              <tr key={r.station_id + r.fuel} className="hover:bg-slate-50">
                <Td>{shortId(r.station_id)}</Td><Td>{r.fuel}</Td><Td right>{n0(r.inventory)}</Td><Td right>{n0(r.incoming)}</Td><Td right>{n0(r.demand_horizon)}</Td>
                <Td right className={r.stockout_prob > 0.5 ? "font-semibold text-rose-600" : ""}>{pct(r.stockout_prob)}</Td><Td right>{pct(r.confidence)}</Td><Td className="max-w-md truncate text-xs text-slate-500">{r.signals.join(" · ")}</Td>
              </tr>))}</tbody></table>
        </div>
      </Card>
    </>
  );
}
