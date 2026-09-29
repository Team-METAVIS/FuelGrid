import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { get } from "../lib/api";
import { useLive } from "../lib/live";
import { n0, pct, title } from "../lib/format";
import { Badge, Button, Card, Empty } from "./ui";

const COLORS: Record<string, string> = { model: "#4f46e5", naive: "#94a3b8", yesterday: "#0ea5e9", average: "#f59e0b", "expert profile": "#10b981" };
const LABEL: Record<string, string> = { model: "Trained model", naive: "Same as now", yesterday: "Same as yesterday", average: "Moving average", "expert profile": "Hand-set expert profile" };
const APPROACH_COLORS = ["#f59e0b", "#94a3b8", "#0ea5e9", "#10b981", "#4f46e5"];

export default function ModelCard() {
  const { act, state: s } = useLive();
  const [m, setM] = useState<any>(null);
  const [ad, setAd] = useState<any>(null);
  const [ex, setEx] = useState(1);
  useEffect(() => { get("/api/models/learned").then(setM).catch(() => undefined); }, [s?.settings.forecaster, m?.training]);
  useEffect(() => { get("/api/adaptation").then(setAd).catch(() => undefined); }, []);
  const rep = m?.report;
  const exp = rep?.experiments?.[ex];
  const wape = exp ? exp.horizons.map((h: number) => Object.fromEntries([["h", `${h * 0 + h} ahead`], ...Object.keys(exp.wape).map((k) => [k, +(exp.wape[k][String(h)] * 100).toFixed(1)])])) : [];
  const names = exp ? Object.keys(exp.wape) : [];
  const champ = rep?.champion;

  return (
    <>
      <Card className="mt-4" title="Trained demand model" subtitle="Learned from data. It never reads the simulator's published demand pattern."
        action={m && <div className="flex items-center gap-2">{m.training && <Badge tone="amber">retraining…</Badge>}<Button size="sm" disabled={m.training} onClick={() => act("/api/models/retrain", undefined, "Retraining finished").then(() => get("/api/models/learned").then(setM))}>Retrain now</Button></div>}>
        {!m || !m.has_model ? <Empty title="No trained model loaded" text="Run: python -m app.ml.train — the platform falls back to a moving average meanwhile." /> : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[["Active version", m.active], ["Algorithm", "Gradient boosting × 3 quantiles"], ["Trained on", champ ? `${n0(champ.rows)} rows · ${champ.series} series` : m.meta ? `${n0(m.meta.rows)} rows` : "—"], ["Data from", (m.meta?.origins ?? champ?.origins ?? []).slice(0, 3).join(", ") + ((m.meta?.origins?.length ?? 0) > 3 ? "…" : "")]].map(([k, v]) => (
                <div key={k as string} className="rounded-lg border border-slate-200 p-3"><div className="text-[11px] text-slate-500">{k}</div><div className="mt-0.5 truncate text-[13px] font-semibold text-slate-900" title={String(v)}>{v}</div></div>
              ))}
            </div>
            {m.last_result && <p className="mt-3 text-xs text-slate-600">Last retrain: <b>{m.last_result.status}</b> — {m.last_result.message ?? m.last_result.reason}</p>}

            {rep?.experiments && (
              <div className="mt-5 grid gap-6 xl:grid-cols-2">
                <div>
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="text-xs font-medium text-slate-700">Forecast error by horizon (lower is better)</div>
                    <select value={ex} onChange={(e) => setEx(+e.target.value)} className="max-w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs">
                      {rep.experiments.map((e: any, i: number) => <option key={i} value={i}>{e.name}</option>)}
                    </select>
                  </div>
                  <div className="h-64">
                    <ResponsiveContainer>
                      <BarChart data={wape} margin={{ left: -14, right: 4 }}>
                        <CartesianGrid vertical={false} stroke="#e2e8f0" />
                        <XAxis dataKey="h" tickLine={false} axisLine={false} />
                        <YAxis unit="%" tickLine={false} axisLine={false} />
                        <Tooltip formatter={(v: number) => `${v}%`} />
                        <Legend iconType="circle" iconSize={8} formatter={(v) => LABEL[v] ?? v} />
                        {names.map((k) => <Bar key={k} dataKey={k} fill={COLORS[k] ?? "#64748b"} radius={[3, 3, 0, 0]} maxBarSize={18} />)}
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500">Walk-forward test on data the model did not train on ({exp.test_series} series). Ticks ahead on the axis. 80% band contains {pct(exp.coverage_80["8"])} of outcomes (ideal 80%).</p>
                </div>
                <div>
                  <div className="mb-2 text-xs font-medium text-slate-700">What the model relies on</div>
                  <div className="space-y-1.5">
                    {(rep.importance ?? []).map((f: any, i: number, a: any[]) => (
                      <div key={f.feature} className="grid grid-cols-[110px_1fr_48px] items-center gap-2 text-xs">
                        <span className="truncate text-slate-600">{title(f.feature)}</span>
                        <div className="h-2 rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500" style={{ width: `${(f.importance / a[0].importance) * 100}%` }} /></div>
                        <span className="tabular text-right text-slate-500">{f.importance.toFixed(3)}</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-[11px] text-slate-500">Permutation importance: how much error grows when a signal is scrambled. The value at the same time yesterday dominates, followed by the day before, last week and the latest observation.</p>
                </div>
              </div>
            )}
          </>
        )}
      </Card>

      {ad?.results && (
        <Card className="mt-4" title="How it copes when the world changes" subtitle="Same unseen network, same five surprises, five ways of forecasting, one optimizer (closed loop)">
          <div className="grid gap-6 xl:grid-cols-2">
            {[["mape", "1-step forecast error (24-tick windows)", "%"], ["service_level", "Service level (24-tick windows)", "%"]].map(([key, label]) => {
              const data = ad.results[0].series.map((_: any, i: number) => ({ tick: ad.results[0].series[i].tick, ...Object.fromEntries(ad.results.map((r: any, j: number) => [`a${j}`, r.series[i][key] == null ? null : +(r.series[i][key] * 100).toFixed(1)])) }));
              return (
                <div key={key}>
                  <div className="mb-2 text-xs font-medium text-slate-700">{label}</div>
                  <div className="h-64">
                    <ResponsiveContainer>
                      <LineChart data={data} margin={{ left: -10, right: 8 }}>
                        <CartesianGrid vertical={false} stroke="#e2e8f0" />
                        <XAxis dataKey="tick" tickLine={false} axisLine={false} />
                        <YAxis unit="%" tickLine={false} axisLine={false} domain={key === "service_level" ? [60, 100] : [0, "auto"]} />
                        <Tooltip />
                        {Object.entries(ad.schedule).map(([t, k]) => <ReferenceLine key={t} x={+t} stroke="#f43f5e" strokeDasharray="3 3" label={{ value: title(String(k)).split(" ")[0], fontSize: 9, fill: "#e11d48", position: "insideTop" }} />)}
                        {ad.results.map((r: any, j: number) => <Line key={j} dataKey={`a${j}`} name={r.name} stroke={APPROACH_COLORS[j]} strokeWidth={j >= 3 ? 2.4 : 1.4} dot={false} connectNulls />)}
                        <Legend iconType="plainline" wrapperStyle={{ fontSize: 11 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-4 overflow-x-auto"><table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th className="py-1.5 pr-3 font-medium">Approach</th><th className="px-3 text-right font-medium">Service level</th><th className="px-3 text-right font-medium">Unmet demand</th><th className="px-3 text-right font-medium">Mean forecast error</th></tr></thead>
            <tbody>{ad.results.map((r: any, j: number) => (
              <tr key={j} className="border-t border-slate-100"><td className="py-1.5 pr-3"><span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: APPROACH_COLORS[j] }} />{r.name}</td><td className="tabular px-3 text-right font-medium">{pct(r.final_service_level, 2)}</td><td className="tabular px-3 text-right">{n0(r.unmet_liters)} L</td><td className="tabular px-3 text-right">{pct(r.mean_mape, 1)}</td></tr>
            ))}</tbody></table></div>
        </Card>
      )}

      {m?.registry?.length > 0 && (
        <Card className="mt-4" title="Model versions" subtitle="Every trained model is stored; roll back with one click" pad={false}>
          <ul className="divide-y divide-slate-100">
            {m.registry.map((r: any) => (
              <li key={r.version} className="flex flex-wrap items-center gap-3 px-5 py-3 text-xs">
                <span className="font-mono text-[12px] text-slate-800">{r.version}</span>
                <Badge tone={r.status === "champion" ? "green" : "slate"}>{r.status}</Badge>
                <span className="text-slate-500">{r.source} · {String(r.created_at).slice(0, 16).replace("T", " ")}</span>
                {r.status !== "champion" && <Button size="sm" className="ml-auto" onClick={() => act("/api/models/activate", { version: r.version }, `Rolled back to ${r.version}`)}>Activate</Button>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
