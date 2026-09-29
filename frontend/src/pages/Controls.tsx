import { KeyRound, OctagonAlert, Pause, Play, RefreshCw, RotateCcw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, PageHeader, Toggle } from "../components/ui";
import { apiKey, get, post } from "../lib/api";
import { useLive } from "../lib/live";

interface Ctl { key: string; label: string; kind: "bool" | "number" | "select"; value: any; default: any; help: string; min?: number; max?: number; step?: number; options?: string[] }
interface Group { name: string; controls: Ctl[] }

function NumberControl({ c, onCommit }: { c: Ctl; onCommit: (v: number) => void }) {
  const [v, setV] = useState<number>(c.value);
  useEffect(() => setV(c.value), [c.value]);
  return (
    <div className="flex items-center gap-3">
      <input type="range" min={c.min} max={c.max} step={c.step} value={v} onChange={(e) => setV(+e.target.value)} onMouseUp={() => onCommit(v)} onTouchEnd={() => onCommit(v)} onKeyUp={() => onCommit(v)} className="h-1.5 w-full min-w-24 flex-1 accent-indigo-600" />
      <input type="number" min={c.min} max={c.max} step={c.step} value={v} onChange={(e) => setV(+e.target.value)} onBlur={() => v !== c.value && onCommit(v)} className="tabular w-24 rounded-md border border-slate-300 px-2 py-1 text-right text-sm outline-none focus:border-brand-500" />
    </div>
  );
}

export default function Controls() {
  const { state: s, act, toasts } = useLive();
  const [groups, setGroups] = useState<Group[]>([]);
  const [meta, setMeta] = useState<any>(null);
  const [model, setModel] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(apiKey.get());
  const [auth, setAuth] = useState<any>(null);

  const load = useCallback(async () => {
    const d = await get("/api/controls");
    setGroups(d.groups); setMeta(d);
    setAuth(await get("/api/auth/status"));
    get("/api/models/learned").then(setModel).catch(() => undefined);
  }, []);
  useEffect(() => { load().catch(() => undefined); }, [load, s?.settings.auto_execute, s?.settings.paused, toasts.length]);

  const set = async (values: Record<string, unknown>, ok = "Saved") => { const r = await act("/api/controls", { values }, ok); if (r) { setGroups(r.groups); setMeta(r); } };
  if (!s) return null;
  const paused = meta?.engine.paused ?? s.settings.paused;
  const pending = s.recommendations.length;

  return (
    <>
      <PageHeader title="Controls" description="Run the platform: start and pause, approval rules, planning and model settings. Every change is validated, audited and saved." />

      {auth?.required && !auth.valid && (
        <Card className="mb-4 border-amber-300 bg-amber-50/60" title={<span className="flex items-center gap-2 text-amber-800"><KeyRound size={14} />Operator API key required</span>} subtitle="This server protects write actions. Reading works without a key.">
          <div className="flex gap-2">
            <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Paste the operator API key" className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500" />
            <Button variant="primary" onClick={() => { apiKey.set(key); load(); }}>Unlock</Button>
          </div>
        </Card>
      )}

      <Card className="mb-4" title="Platform state" subtitle="The decision engine plans and, if allowed, dispatches every few ticks">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={paused ? "amber" : "green"}>{paused ? "Engine paused" : "Engine running"}</Badge>
          <Badge tone={s.settings.auto_execute ? "indigo" : "slate"}>{s.settings.auto_execute ? "Auto-approve ON" : "Manual approval"}</Badge>
          <Badge tone={pending ? "blue" : "slate"}>{pending} awaiting approval</Badge>
          <span className="text-xs text-slate-500">last plan {meta ? `${meta.engine.last_cycle_ms} ms` : "—"} · policy {s.plan?.policy ?? "—"} · source {s.source.label}</span>
          <div className="ml-auto flex flex-wrap gap-2">
            {paused
              ? <Button variant="primary" icon={<Play size={14} />} onClick={() => act("/api/controls/resume", undefined, "Engine resumed").then(load)}>Start engine</Button>
              : <Button icon={<Pause size={14} />} onClick={() => set({ paused: true }, "Engine paused")}>Pause engine</Button>}
            <Button icon={<RefreshCw size={14} />} onClick={() => act("/api/cycle", undefined, "New plan computed")}>Replan now</Button>
            <Button variant="danger" icon={<OctagonAlert size={14} />} onClick={() => confirm("Emergency stop: pause the engine, switch auto-approve off and withdraw all pending recommendations?") && act("/api/controls/emergency-stop", undefined, "EMERGENCY STOP executed").then(load)}>Emergency stop</Button>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          <Button size="sm" variant="primary" disabled={!pending} onClick={() => act("/api/decisions/approve-all", undefined, `${pending} shipment(s) approved`)}>Approve all pending ({pending})</Button>
          <Button size="sm" variant="secondary" disabled={!pending} onClick={() => act("/api/decisions/reject-all", undefined, "All pending recommendations rejected")}>Reject all pending</Button>
          <Button size="sm" variant="ghost" icon={<RotateCcw size={13} />} onClick={() => confirm("Reset all tuning controls to their defaults? (Pause and auto-approve are not changed.)") && act("/api/controls/reset", undefined, "Defaults restored").then(load)}>Reset tuning to defaults</Button>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        {groups.map((g) => (
          <Card key={g.name} title={g.name} subtitle={g.name === "Approvals" ? "Rules for what may be dispatched without a person" : g.name === "Model" ? "Demand model behaviour and continuous learning" : undefined}>
            <div className="divide-y divide-slate-100">
              {g.controls.filter((c) => c.key !== "paused").map((c) => (
                <div key={c.key} className="py-3 first:pt-0 last:pb-0">
                  {c.kind === "bool" ? (
                    <Toggle checked={!!c.value} onChange={(v) => set({ [c.key]: v }, `${c.label}: ${v ? "on" : "off"}`)} label={c.label} hint={c.help} />
                  ) : (
                    <>
                      <div className="mb-1.5 flex items-baseline justify-between gap-3">
                        <div className="text-sm font-medium text-slate-800">{c.label}</div>
                        {c.value !== c.default && <button onClick={() => set({ [c.key]: c.default }, "Default restored")} className="text-[11px] text-brand-600 hover:underline">default: {String(c.default)}</button>}
                      </div>
                      {c.kind === "number" ? <NumberControl c={c} onCommit={(v) => set({ [c.key]: v }, `${c.label} updated`)} /> : (
                        <select value={c.value} onChange={(e) => set({ [c.key]: e.target.value }, `${c.label} updated`)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500">
                          {c.options!.map((o) => <option key={o} value={o}>{o}</option>)}
                        </select>
                      )}
                      <p className="mt-1 text-xs text-slate-500">{c.help}</p>
                    </>
                  )}
                </div>
              ))}
            </div>
            {g.name === "Model" && model && (
              <div className="mt-4 rounded-lg bg-slate-50 p-3 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <ShieldCheck size={13} className="text-emerald-600" /><b className="text-slate-800">{model.active ?? "no trained model"}</b>
                  {model.training && <Badge tone="amber">retraining…</Badge>}
                  <Button size="sm" className="ml-auto" disabled={model.training} onClick={() => act("/api/models/retrain", undefined, "Retraining finished").then(load)}>Retrain now</Button>
                </div>
                {model.last_result && <div className="mt-2 text-slate-600">Last retrain: <b>{model.last_result.status}</b> — {model.last_result.message ?? model.last_result.reason} ({model.last_result.seconds}s)</div>}
              </div>
            )}
          </Card>
        ))}
      </div>
      {auth?.required && auth.valid && <p className="mt-4 flex items-center gap-1.5 text-xs text-slate-500"><KeyRound size={12} /> Operator key active. <button className="text-brand-600 hover:underline" onClick={() => { apiKey.set(""); load(); }}>Forget it</button></p>}
    </>
  );
}
