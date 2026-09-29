import { FastForward, Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, PageHeader, Toggle } from "../components/ui";
import { get } from "../lib/api";
import { title } from "../lib/format";
import { useLive } from "../lib/live";

const EVENTS = [
  { label: "Demand spike (Dhaka ×2)", type: "demand_spike", parameters: { region_ids: ["region-dhaka"], multiplier: 2.0 } },
  { label: "Route disruption (Gazipur→Mirpur)", type: "route_disruption", parameters: { route_ids: ["route-gazipur-mirpur"] } },
  { label: "Station outage (Tongi)", type: "station_outage", parameters: { station_ids: ["station-tongi"] } },
  { label: "Depot constraint (Gazipur)", type: "depot_constraint", parameters: { depot_ids: ["depot-gazipur"] } },
  { label: "Shipment delay (+8 ticks)", type: "shipment_delay", parameters: { delay_ticks: 8 } },
  { label: "Supply shortfall (×0.4)", type: "supply_shortfall", parameters: { factor: 0.4 } },
];
const FAULTS = [
  { label: "API unavailable", type: "unavailable", parameters: {} },
  { label: "High latency (2.5 s)", type: "latency", parameters: { delay_ms: 2500 } },
  { label: "50% error rate", type: "error_rate", parameters: { rate: 0.5 } },
  { label: "Stale data", type: "stale_data", parameters: {} },
  { label: "Event stream drop", type: "stream_disconnect", parameters: {} },
];

export default function Scenarios() {
  const { state: s, act } = useLive();
  const [lib, setLib] = useState<any[]>([]);
  useEffect(() => { get("/api/scenarios").then(setLib).catch(() => undefined); }, []);
  if (!s) return null;
  const running = s.instance.status === "RUNNING";
  if (!s.source.supports_admin) {
    return (
      <>
        <PageHeader title="Scenarios & chaos" description="Crisis and fault injection for the simulator." />
        <Card title="Not available for this data source"><p className="text-sm text-slate-600">The active source ({s.source.label}) has no admin console. Use the Data sources page to change the demo world while it runs, or switch back to the simulator.</p></Card>
      </>
    );
  }
  return (
    <>
      <PageHeader title="Scenarios & chaos" description="Drive the simulator, replay crisis scenarios, and inject software faults to demonstrate detection, fallback and recovery." />

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Simulation clock" subtitle={`Tick ${s.instance.tick} · ${s.instance.status}`}>
          <div className="flex flex-wrap gap-2">
            <Button variant={running ? "secondary" : "primary"} icon={<Play size={14} />} onClick={() => act("/api/sim/run", undefined, "Simulation running")}>Run</Button>
            <Button icon={<Pause size={14} />} onClick={() => act("/api/sim/pause", undefined, "Simulation paused")}>Pause</Button>
            <Button icon={<SkipForward size={14} />} onClick={() => act("/api/sim/step", undefined, "Stepped one tick")}>Step</Button>
            <Button variant="danger" icon={<RotateCcw size={14} />} onClick={() => confirm("Reset the simulation to tick 0?") && act("/api/sim/reset", undefined, "Simulation reset")}>Reset</Button>
          </div>
          <p className="mt-3 text-xs text-slate-500">Pause + Step gives fully deterministic runs for demos and replay.</p>
          <div className="mt-4 border-t border-slate-100 pt-2">
            <Toggle checked={s.settings.auto_execute} onChange={(v) => act("/api/settings", { auto_execute: v }, v ? "Auto-execute enabled" : "Auto-execute disabled")} label="Auto-execute" hint={`Dispatch without approval (cap ${s.settings.max_auto_liters.toLocaleString()} L/cycle; low-confidence still needs review)`} />
            <Toggle checked={s.settings.paused} onChange={(v) => act("/api/settings", { paused: v }, v ? "Decision engine paused" : "Decision engine resumed")} label="Pause decision engine" hint="Kill-switch: stop planning and execution" />
          </div>
        </Card>

        <Card className="xl:col-span-2" title="Inject crisis event" subtitle="Domain events scheduled to start on the next tick (16 ticks = 4 h)">
          <div className="grid gap-2 sm:grid-cols-2">
            {EVENTS.map((e) => (
              <Button key={e.type} variant="warn" className="justify-start" icon={<FastForward size={14} />} onClick={() => act("/api/sim/inject/event", { type: e.type, duration_ticks: 16, parameters: e.parameters }, `${e.label} injected`)}>{e.label}</Button>
            ))}
          </div>
        </Card>
      </div>

      <Card className="mt-4" title="Inject software fault (30 s)" subtitle="Faults hit the simulator API, exercising retries, the circuit breaker, cached state and degraded mode">
        <div className="flex flex-wrap gap-2">
          {FAULTS.map((f) => <Button key={f.type} variant="danger" onClick={() => act("/api/sim/inject/fault", { type: f.type, duration_seconds: 30, parameters: f.parameters }, `${f.label} injected for 30 s`)}>{f.label}</Button>)}
          <Button variant="ghost" onClick={() => act("/api/sim/faults/clear", undefined, "Faults cleared")}>Clear all faults</Button>
        </div>
      </Card>

      <Card className="mt-4" title="Scenario library" subtitle="Scripted crisis scenarios (also used by the benchmark runner)">
        <div className="grid gap-3 lg:grid-cols-2">
          {lib.map((sc) => (
            <div key={sc.name} className="rounded-lg border border-slate-200 p-4">
              <div className="flex items-start justify-between gap-3">
                <div><div className="text-sm font-semibold text-slate-900">{sc.title}</div><p className="mt-0.5 text-xs text-slate-500">{sc.description}</p></div>
                <Button size="sm" variant="primary" onClick={() => act(`/api/scenarios/${sc.name}/apply`, undefined, `Scenario "${sc.title}" applied`)}>Apply</Button>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">{sc.events.length === 0 ? <Badge>no events</Badge> : sc.events.map((e: any, i: number) => <Badge key={i} tone="amber">{title(e.type)}</Badge>)}</div>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
