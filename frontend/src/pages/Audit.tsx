import { useState } from "react";
import { Badge, Card, PageHeader, Td, Th } from "../components/ui";
import { useLive } from "../lib/live";

const KINDS = ["all", "alert", "recovery", "fallback", "operator", "scenario", "integration"];
const tone: Record<string, any> = { alert: "red", recovery: "green", fallback: "amber", operator: "indigo", scenario: "blue", integration: "slate" };

export default function Audit() {
  const { audit } = useLive();
  const [k, setK] = useState("all");
  const rows = audit.filter((a) => k === "all" || a.kind === k);
  return (
    <>
      <PageHeader title="Audit log" description="Immutable record of alerts, incidents, recoveries, fallbacks, operator actions and scenario changes (persisted in PostgreSQL)." />
      <Card
        pad={false}
        title={`${rows.length} events`}
        action={<div className="flex flex-wrap gap-1">{KINDS.map((x) => <button key={x} onClick={() => setK(x)} className={`rounded-md px-2 py-1 text-[11px] font-medium capitalize ${k === x ? "bg-brand-50 text-brand-700" : "text-slate-500 hover:bg-slate-100"}`}>{x}</button>)}</div>}
      >
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr><Th>Time</Th><Th right>Tick</Th><Th>Kind</Th><Th>Severity</Th><Th>Message</Th></tr></thead>
            <tbody>
              {rows.map((a, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <Td>{String(a.created_at ?? "").replace("T", " ").slice(11, 19)}</Td>
                  <Td right>{a.tick ?? "—"}</Td>
                  <Td><Badge tone={tone[a.kind] ?? "slate"}>{a.kind}</Badge></Td>
                  <Td>{a.severity}</Td>
                  <Td className="whitespace-normal">{a.message}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
