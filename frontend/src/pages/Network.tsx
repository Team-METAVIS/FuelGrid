import { Card, PageHeader, Badge, Bar, SevBadge, Th, Td, statusTone } from "../components/ui";
import { liters, n0, pct, shortId } from "../lib/format";
import { useLive } from "../lib/live";
import type { Depot, Station } from "../lib/api";

const FUELS = ["DIESEL", "PETROL", "OCTANE"];
const ROUTE_COLOR = (s: string) => (s === "AVAILABLE" ? "#94a3b8" : "#f43f5e");

function Topology() {
  const { state: s } = useLive();
  if (!s) return null;
  const W = 760, H = 300;
  const dy = (i: number) => 70 + i * 160;
  const sy = (i: number) => 40 + i * 74;
  const dpos = Object.fromEntries(s.depots.map((d, i) => [d.id, { x: 90, y: dy(i) }]));
  const spos = Object.fromEntries(s.stations.map((st, i) => [st.id, { x: 620, y: sy(i) }]));
  const flow: Record<string, number> = {};
  s.in_transit.forEach((a) => { flow[a.route_id] = (flow[a.route_id] ?? 0) + a.quantity; });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full">
      {s.routes.map((r) => {
        const a = dpos[r.source_depot_id], b = spos[r.destination_station_id];
        if (!a || !b) return null;
        const ok = r.status === "AVAILABLE";
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        return (
          <g key={r.id}>
            <line x1={a.x + 50} y1={a.y} x2={b.x - 60} y2={b.y} stroke={ROUTE_COLOR(r.status)} strokeWidth={flow[r.id] ? 3 : 1.5} strokeDasharray={ok ? (flow[r.id] ? "0" : "5 4") : "2 4"} opacity={ok ? 0.9 : 1} />
            <rect x={mx - 34} y={my - 9} width={68} height={18} rx={9} fill="#fff" stroke="#e2e8f0" />
            <text x={mx} y={my + 4} textAnchor="middle" fontSize={10} fill={ok ? "#475569" : "#e11d48"}>{ok ? `${r.transit_ticks} ticks${flow[r.id] ? ` · ${Math.round(flow[r.id] / 1000)}k L` : ""}` : "DISRUPTED"}</text>
          </g>
        );
      })}
      {s.depots.map((d) => (
        <g key={d.id}>
          <rect x={dpos[d.id].x - 60} y={dpos[d.id].y - 26} width={110} height={52} rx={10} fill="#eef2ff" stroke="#c7d2fe" />
          <text x={dpos[d.id].x - 5} y={dpos[d.id].y - 4} textAnchor="middle" fontSize={12} fontWeight={600} fill="#3730a3">{d.name.replace(" Depot", "")}</text>
          <text x={dpos[d.id].x - 5} y={dpos[d.id].y + 12} textAnchor="middle" fontSize={10} fill={d.status === "OPEN" ? "#6366f1" : "#d97706"}>Depot · {d.status}</text>
        </g>
      ))}
      {s.stations.map((st) => {
        const worst = s.risks.filter((r) => r.station_id === st.id).sort((a, b) => ["OK", "WATCH", "WARNING", "CRITICAL"].indexOf(b.severity) - ["OK", "WATCH", "WARNING", "CRITICAL"].indexOf(a.severity))[0];
        const col = st.status !== "OPEN" ? "#f43f5e" : worst?.severity === "CRITICAL" ? "#f43f5e" : worst?.severity === "WARNING" ? "#f59e0b" : worst?.severity === "WATCH" ? "#0ea5e9" : "#10b981";
        return (
          <g key={st.id}>
            <rect x={spos[st.id].x - 60} y={spos[st.id].y - 24} width={150} height={48} rx={10} fill="#fff" stroke={col} strokeWidth={1.5} />
            <circle cx={spos[st.id].x - 44} cy={spos[st.id].y} r={5} fill={col} />
            <text x={spos[st.id].x - 32} y={spos[st.id].y - 3} fontSize={12} fontWeight={600} fill="#0f172a">{st.name.split(" ")[0]}</text>
            <text x={spos[st.id].x - 32} y={spos[st.id].y + 12} fontSize={10} fill="#64748b">{st.status === "OPEN" ? st.profile : st.status}</text>
          </g>
        );
      })}
    </svg>
  );
}

function FuelRows({ item, risks }: { item: Station | Depot; risks?: any[] }) {
  return (
    <div className="space-y-2.5">
      {FUELS.map((f) => {
        const v = item.fuels[f];
        const r = risks?.find((x) => x.station_id === item.id && x.fuel === f);
        return (
          <div key={f} className="grid grid-cols-[64px_1fr_auto_auto] items-center gap-3 text-xs">
            <span className="text-slate-500">{f[0] + f.slice(1).toLowerCase()}</span>
            <Bar value={v.inventory / v.capacity} sev={r?.severity ?? "OK"} />
            <span className="tabular w-16 text-right font-medium text-slate-700">{n0(v.inventory)}</span>
            {r ? <span className="w-20 text-right"><SevBadge sev={r.severity}>{r.severity === "OK" ? "OK" : r.hours_to_stockout != null ? `${r.hours_to_stockout.toFixed(1)} h` : pct(r.stockout_prob)}</SevBadge></span> : <span className="w-20 text-right text-slate-400">{pct(v.inventory / v.capacity)}</span>}
          </div>
        );
      })}
    </div>
  );
}

export default function Network() {
  const { state: s } = useLive();
  if (!s) return null;
  return (
    <>
      <PageHeader title="Network" description="Depots, stations, routes and shipments in flight." />
      <Card title="Supply topology" subtitle="Lines show routes · thick = shipment in transit · red = disrupted">
        <Topology />
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {s.stations.map((st) => (
          <Card key={st.id} title={<span className="flex items-center gap-2">{st.name}<Badge tone={statusTone(st.status)}>{st.status}</Badge>{st.demand_multiplier > 1.05 && <Badge tone="amber">demand ×{st.demand_multiplier.toFixed(2)}</Badge>}</span>} subtitle={`${st.profile.replace("_", " ")} · ${shortId(st.region_id)}`}>
            <FuelRows item={st} risks={s.risks} />
          </Card>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        {s.depots.map((d) => (
          <Card key={d.id} title={<span className="flex items-center gap-2">{d.name}<Badge tone={statusTone(d.status)}>{d.status}</Badge></span>} subtitle={`Dispatch capacity ${n0(d.dispatch_capacity)} L / tick · ${shortId(d.region_id)}`}>
            <FuelRows item={d} />
          </Card>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Shipments in transit" subtitle="Estimated arrival adds the delay each road has actually shown" pad={false}>
          <table className="w-full"><thead><tr><Th>Road</Th><Th>Fuel</Th><Th right>Liters</Th><Th right>Expected</Th><Th right>Estimated arrival</Th><Th>Risk</Th></tr></thead>
            <tbody>
              {s.eta.shipments.length === 0 && <tr><Td className="text-slate-400">No shipments in transit</Td><Td /><Td /><Td /><Td /><Td /></tr>}
              {s.eta.shipments.map((a: any) => <tr key={a.id}><Td>{shortId(a.route_id)}</Td><Td>{a.fuel}</Td><Td right>{n0(a.quantity)}</Td><Td right>tick {a.expected_tick}</Td><Td right className="font-medium">tick {a.estimated_tick}</Td><Td>{a.risk ? <Badge tone="amber">{a.risk}</Badge> : <span className="text-slate-400">on track</span>}</Td></tr>)}
            </tbody></table>
        </Card>
        <Card title="Incoming supply" subtitle={`Estimated arrival and delay risk · ${Math.round((s.eta.supply_delayed_share ?? 0) * 100)}% of open supply is delayed`} pad={false}>
          <table className="w-full"><thead><tr><Th>Depot</Th><Th>Fuel</Th><Th right>Liters</Th><Th right>Planned</Th><Th right>Estimated arrival</Th><Th>Delay risk</Th></tr></thead>
            <tbody>
              {s.eta.supply.slice(0, 8).map((a: any) => <tr key={a.id}><Td>{shortId(a.depot_id)}</Td><Td>{a.fuel}</Td><Td right>{n0(a.quantity)}</Td><Td right>tick {a.planned_tick}</Td><Td right className="font-medium">tick {a.estimated_tick}</Td><Td><Badge tone={a.status === "DELAYED" ? "amber" : a.delay_risk > 0.3 ? "amber" : "slate"}>{a.status === "DELAYED" ? "delayed" : `${Math.round(a.delay_risk * 100)}%`}</Badge></Td></tr>)}
            </tbody></table>
        </Card>
      </div>
      <p className="mt-3 text-xs text-slate-400">{liters(s.metrics.allocation_liters)} dispatched in total · {s.metrics.allocation_failures} simulator-side allocation failures.</p>
    </>
  );
}
