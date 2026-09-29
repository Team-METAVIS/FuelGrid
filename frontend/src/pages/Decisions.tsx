import { CheckCircle2 } from "lucide-react";
import { useState } from "react";
import RecommendationCard from "../components/RecommendationCard";
import { Badge, Button, Card, Empty, PageHeader, SevBadge, Td, Th, statusTone } from "../components/ui";
import { n0, shortId } from "../lib/format";
import { useLive } from "../lib/live";

const FILTERS = ["ALL", "EXECUTED", "PROPOSED", "FAILED", "REJECTED", "EXPIRED"];

export default function Decisions() {
  const { state: s, decisions, approveAll } = useLive();
  const [f, setF] = useState("ALL");
  if (!s) return null;
  const rows = decisions.filter((d) => f === "ALL" || d.status === f);
  const executed = decisions.filter((d) => d.status === "EXECUTED");
  return (
    <>
      <PageHeader
        title="Decisions"
        description="Recommendations from the decision engine. Every action is logged and requires operator approval unless auto-execute is enabled."
        actions={s.recommendations.length > 1 ? <Button variant="primary" onClick={approveAll}>Approve all ({s.recommendations.length})</Button> : undefined}
      />
      <Card title="Pending recommendations" subtitle={`Policy: ${s.plan?.policy ?? "—"} · solver ${s.plan?.solver_status ?? "—"} · ${s.plan ? Math.round(s.plan.runtime_ms) : 0} ms`}>
        {s.recommendations.length === 0 ? (
          <Empty icon={<CheckCircle2 size={28} />} title="Nothing to approve" text="The network is within safe cover. New recommendations appear here as risk emerges." />
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">{s.recommendations.map((d) => <RecommendationCard key={d.id} d={d} />)}</div>
        )}
      </Card>

      <Card
        className="mt-4"
        title="Decision history"
        subtitle={`${decisions.length} decisions · ${executed.length} executed · ${n0(executed.reduce((a, d) => a + d.quantity, 0))} L dispatched`}
        action={<div className="flex flex-wrap gap-1">{FILTERS.map((x) => <button key={x} onClick={() => setF(x)} className={`rounded-md px-2 py-1 text-[11px] font-medium ${f === x ? "bg-brand-50 text-brand-700" : "text-slate-500 hover:bg-slate-100"}`}>{x}</button>)}</div>}
        pad={false}
      >
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr><Th>#</Th><Th right>Tick</Th><Th>Station</Th><Th>Fuel</Th><Th>Route</Th><Th right>Liters</Th><Th>Severity</Th><Th>Policy</Th><Th>Status</Th><Th>By</Th><Th>Result</Th></tr></thead>
            <tbody>
              {rows.length === 0 && <tr><Td className="text-slate-400">No decisions</Td>{Array.from({ length: 10 }).map((_, i) => <Td key={i} />)}</tr>}
              {rows.map((d) => (
                <tr key={d.id} className="hover:bg-slate-50">
                  <Td>{d.id}</Td><Td right>{d.tick}</Td><Td>{shortId(d.station_id)}</Td><Td>{d.fuel}</Td><Td>{shortId(d.route_id)}</Td><Td right>{n0(d.quantity)}</Td>
                  <Td><SevBadge sev={d.severity} /></Td><Td>{d.policy}</Td><Td><Badge tone={statusTone(d.status)}>{d.status}</Badge></Td><Td>{d.actor}</Td><Td className="max-w-48 truncate">{d.result ?? "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
