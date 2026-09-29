import { Pause, Play, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Bar, Button, Card, Empty, PageHeader, SevBadge, statusTone } from "../components/ui";
import { get } from "../lib/api";
import { liters, n0, pct, shortId } from "../lib/format";
import { useLive } from "../lib/live";

export default function Replay() {
  const { state: s } = useLive();
  const [runs, setRuns] = useState<any[]>([]);
  const [run, setRun] = useState<string>("");
  const [data, setData] = useState<any>(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [err, setErr] = useState("");
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    get("/api/replay/runs").then((r) => { setRuns(r.runs); const best = r.runs.find((x: any) => x.points >= 20) ?? r.runs[0]; if (best) setRun(best.run_id); else setErr(r.note ?? "No recorded runs yet."); }).catch((e) => setErr(String(e.message)));
  }, []);
  useEffect(() => {
    if (!run) return;
    setData(null); setErr(""); setIdx(0); setPlaying(false);
    get(`/api/replay/${run}`).then((d) => { setData(d); setIdx(0); }).catch((e) => setErr(String(e.message)));
  }, [run]);
  useEffect(() => {
    if (!playing || !data) return;
    timer.current = window.setInterval(() => setIdx((i) => { if (i >= data.ticks.length - 1) { setPlaying(false); return i; } return i + 1; }), 220);
    return () => clearInterval(timer.current);
  }, [playing, data]);

  const cur = data?.ticks[idx];
  const tick: number = cur?.tick ?? 0;
  const series = useMemo(() => (data?.ticks ?? []).map((t: any) => ({ tick: t.tick, sl: +(t.service_level * 100).toFixed(2), unmet: Math.round(t.unmet_liters) })), [data]);
  const decisions = useMemo(() => (data?.decisions ?? []).filter((d: any) => d.tick <= tick).sort((a: any, b: any) => b.tick - a.tick).slice(0, 8), [data, tick]);
  const events = useMemo(() => (data?.audit ?? []).filter((a: any) => a.tick <= tick && ["alert", "recovery", "fallback"].includes(a.kind)).slice(-6).reverse(), [data, tick]);
  if (!s) return null;

  return (
    <>
      <PageHeader title="Simulation replay" description="Scrub through a recorded run: fuel levels, decisions and incidents as they happened." />
      {err && !data && <Card><Empty title="Nothing to replay yet" text={err} /></Card>}
      {!err && !data && <Card><Empty title="Loading recorded run…" text="Fetching fuel levels, decisions and incidents from the database." /></Card>}
      {data && (
        <>
          <Card
            title={`Run ${run}`}
            subtitle={`${data.ticks.length} recorded points · tick ${data.ticks[0].tick} → ${data.ticks[data.ticks.length - 1].tick}`}
            action={<select className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs" value={run} onChange={(e) => setRun(e.target.value)}>{runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id} · {r.points} pts</option>)}</select>}
          >
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" size="sm" icon={playing ? <Pause size={14} /> : <Play size={14} />} onClick={() => setPlaying(!playing)}>{playing ? "Pause" : "Play"}</Button>
              <Button size="sm" icon={<RotateCcw size={14} />} onClick={() => { setIdx(0); setPlaying(false); }}>Restart</Button>
              <input type="range" min={0} max={data.ticks.length - 1} value={idx} onChange={(e) => { setIdx(+e.target.value); setPlaying(false); }} className="min-w-48 flex-1 accent-indigo-600" />
              <span className="tabular text-sm text-slate-600">Tick <b>{tick}</b></span>
              <Badge tone="indigo">service {pct(cur.service_level, 1)}</Badge>
              <Badge tone={cur.unmet_liters > 0 ? "amber" : "green"}>unmet {liters(cur.unmet_liters)}</Badge>
            </div>
            <div className="mt-4 h-40">
              <ResponsiveContainer>
                <LineChart data={series} margin={{ left: -10, right: 8 }}>
                  <CartesianGrid vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="tick" tickLine={false} axisLine={false} />
                  <YAxis domain={[(min: number) => Math.max(0, Math.floor(min - 2)), 100]} unit="%" tickLine={false} axisLine={false} />
                  <Tooltip />
                  <ReferenceLine x={tick} stroke="#4f46e5" strokeWidth={2} />
                  <Line dataKey="sl" name="Service level %" stroke="#10b981" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2" title="Station fuel levels at this moment" subtitle="% of tank capacity">
              <div className="grid gap-4 sm:grid-cols-2">
                {s.stations.map((st) => {
                  const inv = cur.payload?.stations?.[st.id] ?? {};
                  return (
                    <div key={st.id} className="rounded-lg border border-slate-200 p-3">
                      <div className="mb-2 text-[13px] font-semibold text-slate-900">{st.name}</div>
                      {["DIESEL", "PETROL", "OCTANE"].map((f) => {
                        const v = inv[f] ?? 0, cap = st.fuels[f].capacity, ratio = v / cap;
                        return (
                          <div key={f} className="mb-1.5 grid grid-cols-[56px_1fr_56px] items-center gap-2 text-xs">
                            <span className="text-slate-500">{f[0] + f.slice(1).toLowerCase()}</span>
                            <Bar value={ratio} sev={ratio < 0.08 ? "CRITICAL" : ratio < 0.2 ? "WARNING" : "OK"} />
                            <span className="tabular text-right text-slate-700">{n0(v)}</span>
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </Card>

            <div className="space-y-4">
              <Card title="Decisions so far" pad={false}>
                {decisions.length === 0 ? <Empty title="No decisions yet" /> : (
                  <ul className="divide-y divide-slate-100">
                    {decisions.map((d: any) => (
                      <li key={d.id} className="flex items-center justify-between gap-2 px-5 py-2.5 text-xs">
                        <span><b className="text-slate-800">{n0(d.quantity)} L</b> {d.fuel.toLowerCase()} → {shortId(d.station_id)}<span className="ml-1 text-slate-400">t{d.tick}</span></span>
                        <span className="flex items-center gap-1"><SevBadge sev={d.severity} /><Badge tone={statusTone(d.status)}>{d.status}</Badge></span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title="Incidents and alerts" pad={false}>
                {events.length === 0 ? <Empty title="Quiet so far" /> : (
                  <ul className="divide-y divide-slate-100">{events.map((a: any, i: number) => <li key={i} className="px-5 py-2.5 text-xs text-slate-700"><span className="mr-2 text-slate-400">t{a.tick}</span>{a.message}</li>)}</ul>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}
