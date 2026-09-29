import { Database, FastForward, Pause, Play, PlugZap, RadioTower, RotateCcw, SkipForward, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Bar, Button, Card, PageHeader, Td, Th } from "../components/ui";
import { get } from "../lib/api";
import { n0, pct, title } from "../lib/format";
import { useLive } from "../lib/live";

const CHANGES = [
  { kind: "demand_shift", label: "Demand jumps +40%", magnitude: 1.4, hint: "permanent regime change" },
  { kind: "seasonality_shift", label: "Daily peaks move +3 h", magnitude: 1, hint: "concept drift" },
  { kind: "demand_shock", label: "Unannounced surge", magnitude: 1.8, hint: "one station, 24 ticks" },
  { kind: "sensor_dropout", label: "3 sensors go silent", magnitude: 1, hint: "missing data" },
  { kind: "road_closure", label: "A road closes", magnitude: 1, hint: "topology status" },
  { kind: "new_station", label: "A new station opens", magnitude: 1, hint: "network grows" },
  { kind: "capacity_change", label: "Depot loses capacity", magnitude: 0.5, hint: "supply constraint" },
];

const CURL = `# 1. describe your network (send again whenever it changes)
curl -X POST $HOST/api/feed/topology -H 'content-type: application/json' -d '{
  "tick_minutes": 30,
  "depots":   [{"id":"D1","name":"Main depot","dispatch_capacity_per_tick":12000,"capacity":{"DIESEL":80000},"inventory":{"DIESEL":60000}}],
  "stations": [{"id":"S1","name":"Station 1","capacity":{"DIESEL":15000},"inventory":{"DIESEL":9000}}],
  "routes":   [{"id":"R1","source_depot_id":"D1","destination_station_id":"S1","transit_ticks":2,"max_shipment":7000}]}'

# 2. push readings every interval
curl -X POST $HOST/api/feed/telemetry -H 'content-type: application/json' -d '{
  "time":"2026-03-02T08:30:00",
  "inventory":[{"entity_id":"S1","fuel":"DIESEL","liters":8650},{"entity_id":"D1","fuel":"DIESEL","liters":59000}],
  "demand":[{"station_id":"S1","fuel":"DIESEL","liters":350}]}'

# 3. pull approved dispatch orders, then report progress
curl $HOST/api/feed/orders?status=PENDING
curl -X POST $HOST/api/feed/orders/1/ack -H 'content-type: application/json' -d '{"order_id":1,"status":"IN_TRANSIT"}'`;

export default function Sources() {
  const { state: s, act } = useLive();
  const [src, setSrc] = useState<any>(null);
  const [feed, setFeed] = useState<any>(null);
  const [seed, setSeed] = useState(7);
  const [speed, setSpeed] = useState(2);
  const [clock, setClock] = useState<any>(null);
  const [cspeed, setCspeed] = useState(2);

  useEffect(() => {
    const load = () => { get("/api/source").then(setSrc).catch(() => undefined); get("/api/feed/status").then(setFeed).catch(() => undefined); get("/api/sim/clock").then(setClock).catch(() => undefined); };
    load();
    const id = setInterval(load, 2500);
    return () => clearInterval(id);
  }, []);
  if (!s) return null;
  const active = src?.active ?? s.source.kind;
  const demo = src?.demo;
  const q = feed?.quality;

  return (
    <>
      <PageHeader title="Data sources" description="FuelGrid is not tied to one simulator. Any system that speaks the feed API drives it; the organizer's simulator is just one adapter." />

      <div className="grid gap-4 lg:grid-cols-2">
        {(src?.sources ?? []).map((x: any) => (
          <Card key={x.kind} className={x.active ? "border-brand-500 ring-1 ring-brand-500/30" : ""}
            title={<span className="flex items-center gap-2">{x.kind === "simulator" ? <Database size={15} className="text-slate-400" /> : <RadioTower size={15} className="text-slate-400" />}{x.label}{x.active && <Badge tone="indigo">active</Badge>}</span>}
            subtitle={x.detail}
            action={!x.active && <Button size="sm" variant="primary" onClick={() => act("/api/source", { kind: x.kind }, `Switched to ${x.label}`)}>Use this source</Button>}>
            <p className="text-xs text-slate-600">
              {x.kind === "simulator"
                ? "REST for state, server-sent events as change hints, one write endpoint. Has an admin console for injecting events and faults."
                : "Topology and telemetry pushed over HTTP by any system; approved dispatch orders pulled back (or sent to a webhook). Validated, quality-scored, and dynamic: stations and roads can appear or disappear at any time."}
            </p>
          </Card>
        ))}
      </div>

      {active === "simulator" && (
        <Card className="mt-4" title="Simulator clock" subtitle={`Tick ${s.instance.tick} · ${s.instance.status}`}>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={<Play size={14} />} onClick={() => act("/api/sim/run", undefined, "Simulation running")}>Run</Button>
            <Button icon={<Pause size={14} />} onClick={() => act("/api/sim/pause", undefined, "Simulation paused")}>Pause</Button>
            <Button icon={<SkipForward size={14} />} onClick={() => act("/api/sim/step", undefined, "Stepped one tick")}>Step</Button>
            <Button variant="danger" icon={<RotateCcw size={14} />} onClick={() => confirm("Reset the simulation to tick 0?") && act("/api/sim/reset", undefined, "Simulation reset")}>Reset</Button>
          </div>
          <div className="mt-4 rounded-lg border border-slate-200 p-3">
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-sm font-medium text-slate-800">Lock-step clock <span className="font-normal text-slate-500">(recommended)</span></div>
              {clock?.running ? <Badge tone="green">running · {clock.speed} ticks/s · {clock.steps} steps</Badge> : <Badge>stopped</Badge>}
              <label className="ml-auto text-xs text-slate-600">{cspeed} ticks/s<input type="range" min={1} max={12} value={cspeed} onChange={(e) => setCspeed(+e.target.value)} className="ml-2 w-28 align-middle accent-indigo-600" /></label>
              {!clock?.running
                ? <Button size="sm" variant="primary" icon={<Play size={13} />} onClick={() => act("/api/sim/clock/start", { speed: cspeed }, "Lock-step clock started")}>Start</Button>
                : <Button size="sm" variant="danger" icon={<Square size={12} />} onClick={() => act("/api/sim/clock/stop", undefined, "Lock-step clock stopped")}>Stop</Button>}
            </div>
            <p className="mt-2 text-xs text-slate-500">FuelGrid advances the simulator itself: step, read, plan, repeat. Every tick is planned before the next one starts, so the platform can never fall behind. The simulator's own Run mode ticks at a fixed speed regardless of planning.</p>
            {clock?.last_error && <p className="mt-1 text-xs text-amber-700">Last issue: {clock.last_error}</p>}
          </div>
          <p className="mt-2 text-xs text-slate-500">Crisis and fault injection live on the Scenarios &amp; Chaos page.</p>
        </Card>
      )}

      <Card className="mt-4" title="Independent demo world" subtitle="A network the platform has never seen: 3 depots, 8 stations, 4 fuels incl. LPG, 30-minute ticks, weekly seasonality, noisy sensors"
        action={demo?.running ? <Badge tone="green">running · tick {demo.tick}</Badge> : <Badge>stopped</Badge>}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-600">Seed<input type="number" value={seed} onChange={(e) => setSeed(+e.target.value)} className="tabular ml-2 w-20 rounded-md border border-slate-300 px-2 py-1 text-sm" /></label>
          <label className="text-xs text-slate-600">Speed {speed} ticks/s<input type="range" min={1} max={30} value={speed} onChange={(e) => setSpeed(+e.target.value)} className="ml-2 w-32 align-middle accent-indigo-600" /></label>
          <Button size="sm" variant="secondary" onClick={() => act("/api/controls", { values: { auto_execute: !s.settings.auto_execute } }, s.settings.auto_execute ? "Auto-approve off" : "Auto-approve on")}>{s.settings.auto_execute ? "Auto-approve: ON" : "Auto-approve: off"}</Button>
          {!demo?.running
            ? <Button variant="primary" icon={<PlugZap size={14} />} onClick={() => act("/api/feed/demo/start", { seed, speed }, "Demo world started; switched to the live feed")}>Start demo world</Button>
            : <Button variant="danger" icon={<Square size={13} />} onClick={() => act("/api/feed/demo/stop", undefined, "Demo world stopped")}>Stop</Button>}
        </div>
        {demo?.running && (
          <>
            {!s.settings.auto_execute && s.recommendations.length > 0 && <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">Nothing is being dispatched: recommendations wait for approval. Approve them on the Decisions page or switch auto-approve on here to watch the loop run by itself.</p>}
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[["World service level", pct(demo.service_level, 1)], ["Unmet (truth)", `${n0(demo.truth_unmet_l)} L`], ["Demand level", `×${demo.level}`], ["Stations", demo.stations]].map(([k, v]) => (
                <div key={k as string} className="rounded-lg border border-slate-200 p-3"><div className="text-[11px] text-slate-500">{k}</div><div className="tabular text-lg font-semibold text-slate-900">{v}</div></div>
              ))}
            </div>
            <div className="mt-4">
              <div className="mb-2 text-xs font-medium text-slate-600">Change the world while it runs, and watch FuelGrid adapt:</div>
              <div className="flex flex-wrap gap-2">
                {CHANGES.map((c) => <Button key={c.kind} size="sm" variant="warn" icon={<FastForward size={13} />} onClick={() => act("/api/feed/demo/change", { kind: c.kind, magnitude: c.magnitude, duration_ticks: 24 }, c.label)}>{c.label}</Button>)}
              </div>
              {demo.changes?.length > 0 && <ul className="mt-3 space-y-1 text-xs text-slate-600">{demo.changes.slice().reverse().map((m: string, i: number) => <li key={i}>• {m}</li>)}</ul>}
            </div>
          </>
        )}
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Live-feed data quality" subtitle={q ? `${q.batches} batches received · ${q.seconds_since_last_batch ?? "—"} s since the last one` : "No feed data yet"}>
          {!q || q.batches === 0 ? <p className="text-sm text-slate-500">Nothing received yet. Start the demo world or push telemetry.</p> : (
            <>
              <div className="flex items-center gap-3"><div className="tabular text-3xl font-semibold text-slate-900">{pct(q.score, 1)}</div><div className="flex-1"><Bar value={q.score} sev={q.score > 0.95 ? "OK" : q.score > 0.85 ? "WATCH" : "WARNING"} /><div className="mt-1 text-xs text-slate-500">{n0(q.accepted)} accepted · {n0(q.flagged)} flagged · {n0(q.rejected)} rejected</div></div></div>
              <div className="mt-3 flex flex-wrap gap-1.5">{Object.entries(q.reasons ?? {}).map(([k, v]) => <Badge key={k} tone={["invalid_value", "unknown_entity", "out_of_order"].includes(k) ? "red" : "amber"}>{title(k)} · {String(v)}</Badge>)}</div>
              {Object.keys(q.stale_series ?? {}).length > 0 && <p className="mt-3 text-xs text-amber-700">Silent sensors (last value kept): {Object.entries(q.stale_series).map(([k, v]) => `${k} (${v} ticks)`).join(", ")}</p>}
            </>
          )}
        </Card>
        <Card title="Recent data issues" subtitle="Bad values are rejected, suspicious ones flagged; nothing ever crashes ingestion" pad={false}>
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full"><thead><tr><Th>Tick</Th><Th>Result</Th><Th>What</Th></tr></thead>
              <tbody>{(q?.recent ?? []).length === 0 && <tr><Td className="text-slate-400">No issues</Td><Td /><Td /></tr>}
                {(q?.recent ?? []).map((r: any, i: number) => <tr key={i}><Td>{r.tick}</Td><Td><Badge tone={r.level === "rejected" ? "red" : "amber"}>{r.reason}</Badge></Td><Td className="max-w-md truncate text-xs">{r.detail}</Td></tr>)}</tbody></table>
          </div>
        </Card>
      </div>

      <Card className="mt-4" title="Connect a real system" subtitle="Everything below works today; no simulator involved">
        <pre className="overflow-x-auto rounded-lg bg-slate-900 p-4 text-[12px] leading-relaxed text-slate-100">{CURL}</pre>
        {feed && <p className="mt-2 text-xs text-slate-500">Feed currently holds {feed.stations} stations, {feed.depots} depots, {feed.routes} routes, fuels: {feed.fuels.join(", ") || "—"}; orders: {Object.entries(feed.orders).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(", ")}.</p>}
      </Card>
    </>
  );
}
