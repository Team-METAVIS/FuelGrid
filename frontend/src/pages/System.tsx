import { Cpu, Database, ExternalLink, GitBranch, Radio, Server, Sigma } from "lucide-react";
import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, PageHeader, Stat, statusTone } from "../components/ui";
import { apiUrl, get } from "../lib/api";
import { pct } from "../lib/format";
import { useLive } from "../lib/live";

const META: Record<string, { label: string; icon: any }> = {
  database: { label: "Database", icon: Database },
  simulator: { label: "Fuel simulator", icon: Server },
  event_stream: { label: "Event stream (SSE)", icon: Radio },
  prediction: { label: "Prediction service", icon: Sigma },
  decision_engine: { label: "Decision engine", icon: GitBranch },
};

export default function System() {
  const { state: s } = useLive();
  const [tel, setTel] = useState<any[]>([]);
  useEffect(() => {
    const load = () => get("/api/telemetry").then((t) => setTel(t.api.map((x: any, i: number) => ({ ...x, i })))).catch(() => undefined);
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);
  if (!s) return null;
  const h = s.health;
  return (
    <>
      <PageHeader title="System health" description="Component status, API performance and runtime behaviour of the platform itself." />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Overall" value={<span className="capitalize">{h.status}</span>} tone={h.status === "healthy" ? "good" : "warn"} hint={`Mode: ${h.mode}`} />
        <Stat label="API latency (avg / p95)" value={`${h.api.avg_ms} / ${h.api.p95_ms} ms`} hint={`${h.api.rps} req/s · 60 s window`} />
        <Stat label="API error rate" value={pct(h.api.error_rate, 1)} tone={h.api.error_rate > 0.02 ? "bad" : "good"} hint={`${h.api.requests} requests`} />
        <Stat label="Decision cycle" value={`${Math.round(h.components.decision_engine.last_cycle_ms ?? 0)} ms`} hint="Forecast → optimize → validate" />
        <Stat label="Process" value={`${h.process.rss_mb} MB`} icon={<Cpu size={15} />} hint={`CPU ${h.process.cpu_pct}% · up ${Math.round(h.process.uptime_s / 60)} min`} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-1" title="Components" pad={false}>
          <ul className="divide-y divide-slate-100">
            {Object.entries(h.components).map(([k, c]) => {
              const M = META[k] ?? { label: k, icon: Server };
              return (
                <li key={k} className="flex items-center gap-3 px-5 py-3.5">
                  <M.icon size={16} className="text-slate-400" />
                  <div className="min-w-0 flex-1"><div className="text-[13px] font-medium text-slate-900">{M.label}</div><div className="truncate text-xs text-slate-500">{c.detail}</div></div>
                  <Badge tone={statusTone(c.status)}>{c.status}</Badge>
                </li>
              );
            })}
          </ul>
        </Card>

        <Card className="xl:col-span-2" title="API throughput & latency" subtitle="Last 3 minutes, 5 s buckets">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="h-52">
              <div className="mb-1 text-xs text-slate-500">Requests / second</div>
              <ResponsiveContainer>
                <AreaChart data={tel} margin={{ left: -20 }}><CartesianGrid vertical={false} stroke="#e2e8f0" /><XAxis dataKey="i" hide /><YAxis tickLine={false} axisLine={false} /><Tooltip /><Area dataKey="rps" stroke="#4f46e5" fill="#6366f1" fillOpacity={0.15} strokeWidth={2} /></AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="h-52">
              <div className="mb-1 text-xs text-slate-500">p95 latency (ms)</div>
              <ResponsiveContainer>
                <AreaChart data={tel} margin={{ left: -20 }}><CartesianGrid vertical={false} stroke="#e2e8f0" /><XAxis dataKey="i" hide /><YAxis tickLine={false} axisLine={false} /><Tooltip /><Area dataKey="p95_ms" stroke="#0ea5e9" fill="#0ea5e9" fillOpacity={0.15} strokeWidth={2} /></AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Resilience behaviour" subtitle="What the platform does when something breaks">
          <table className="w-full text-[13px]">
            <tbody className="divide-y divide-slate-100">
              {[
                ["Simulator slow / unavailable", "Timeout → retry with exponential backoff → circuit breaker → serve cached state (degraded mode)"],
                ["Invalid simulator payload", "Rejected by schema validation; incident raised; last good snapshot retained"],
                ["Stale data flag", "Detected via X-Simulator-Stale; auto-execution suspended"],
                ["Event stream dropped", "Reconnect with backoff; polling keeps state fresh; full re-sync on reconnect"],
                ["Optimizer failure / timeout", "Automatic fallback to rule-based allocation policy"],
                ["Forecaster failure", "Fallback to moving-average forecaster"],
                ["Low forecast confidence", "Recommendation flagged for human review; never auto-executed"],
                ["Database unavailable", "Writes buffered in memory; operations continue; UI reads from buffer"],
              ].map(([a, b]) => <tr key={a}><td className="w-2/5 py-2 pr-4 font-medium text-slate-800">{a}</td><td className="py-2 text-slate-600">{b}</td></tr>)}
            </tbody>
          </table>
        </Card>
        <Card title="Observability endpoints">
          <div className="space-y-2 text-sm">
            {[["/metrics", "Prometheus metrics: system + intelligence (MAPE, confidence, fallbacks, alerts)"], ["/docs", "OpenAPI documentation"], ["/api/health", "Structured component health (JSON)"], ["/healthz", "Liveness probe"]].map(([u, d]) => (
              <a key={u} href={apiUrl(u)} target="_blank" rel="noreferrer" className="flex items-center justify-between rounded-lg border border-slate-200 px-4 py-2.5 hover:bg-slate-50">
                <span><span className="font-mono text-[13px] text-brand-700">{u}</span><span className="ml-3 text-xs text-slate-500">{d}</span></span><ExternalLink size={14} className="text-slate-400" />
              </a>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-500">Version {h.version} · snapshot age {h.snapshot_age_s ?? "—"} s</p>
        </Card>
      </div>
    </>
  );
}
