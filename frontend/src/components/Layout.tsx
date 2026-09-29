import clsx from "clsx";
import { Activity, AlertTriangle, BrainCircuit, ClipboardList, FlaskConical, Fuel, LayoutDashboard, Network, ScrollText, ServerCog, WifiOff } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useLive } from "../lib/live";
import { simTime } from "../lib/format";
import { Badge, statusTone } from "./ui";

const NAV = [
  { group: "Operations", items: [
    { to: "/", label: "Overview", icon: LayoutDashboard },
    { to: "/network", label: "Network", icon: Network },
    { to: "/recommendations", label: "Decisions", icon: ClipboardList, badge: true },
  ] },
  { group: "Intelligence", items: [
    { to: "/intelligence", label: "Forecast & Models", icon: BrainCircuit },
    { to: "/scenarios", label: "Scenarios & Chaos", icon: FlaskConical },
  ] },
  { group: "Platform", items: [
    { to: "/system", label: "System health", icon: ServerCog },
    { to: "/audit", label: "Audit log", icon: ScrollText },
  ] },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { state, connected, toasts, act } = useLive();
  const pending = state?.recommendations.length ?? 0;
  const h = state?.health;
  return (
    <div className="flex h-full bg-slate-50">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
        <div className="flex h-14 items-center gap-2.5 border-b border-slate-100 px-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-white"><Fuel size={17} /></div>
          <div>
            <div className="text-sm font-semibold leading-none text-slate-900">FuelGrid</div>
            <div className="mt-1 text-[11px] leading-none text-slate-500">Operations console</div>
          </div>
        </div>
        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5">
          {NAV.map((g) => (
            <div key={g.group}>
              <div className="mb-1.5 px-2 text-[11px] font-medium uppercase tracking-wider text-slate-400">{g.group}</div>
              {g.items.map((it) => (
                <NavLink
                  key={it.to}
                  to={it.to}
                  end={it.to === "/"}
                  className={({ isActive }) => clsx("group mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition", isActive ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900")}
                >
                  <it.icon size={16} />
                  <span className="flex-1">{it.label}</span>
                  {it.badge && pending > 0 && <span className="rounded-full bg-brand-600 px-1.5 py-px text-[10px] font-semibold text-white">{pending}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-4 text-[11px] leading-relaxed text-slate-500">
          <div className="mb-1 flex items-center gap-1.5 font-medium text-amber-700"><AlertTriangle size={12} /> Simulated environment</div>
          No real fuel infrastructure is controlled. Consequential actions require operator approval.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 sm:px-6">
          <div className="flex items-center gap-2 lg:hidden"><div className="grid h-7 w-7 place-items-center rounded-lg bg-brand-600 text-white"><Fuel size={15} /></div><span className="text-sm font-semibold">FuelGrid</span></div>
          <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
            {state?.ready && (
              <>
                <span className="tabular hidden text-xs text-slate-500 sm:inline">Tick <b className="text-slate-800">{state.instance.tick}</b> · {simTime(state.instance.sim_time)}</span>
                <Badge tone={statusTone(state.instance.status)}>{state.instance.status}</Badge>
                <Badge tone={h?.status === "healthy" ? "green" : "amber"}><Activity size={11} /> System {h?.status}</Badge>
                {h?.mode !== "live" && <Badge tone="amber">Degraded · cached state</Badge>}
              </>
            )}
            <span className={clsx("flex items-center gap-1.5 text-xs", connected ? "text-emerald-600" : "text-rose-600")}>
              {connected ? <><span className="live-dot h-2 w-2 rounded-full bg-emerald-500" /> Live</> : <><WifiOff size={13} /> Offline</>}
            </span>
          </div>
        </header>
        {!connected && <div className="border-b border-rose-200 bg-rose-50 px-6 py-2 text-xs text-rose-700">Backend unreachable — showing the last known data. Reconnecting…</div>}
        {state?.ready && h?.mode !== "live" && (
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-xs text-amber-800">
            Degraded mode: simulator data is stale or unreachable. Recommendations use cached state and auto-execution is suspended until recovery.
          </div>
        )}
        {state?.settings.rolled_back && (
          <div className="flex flex-wrap items-center gap-3 border-b border-amber-200 bg-amber-50 px-6 py-2 text-xs text-amber-800">
            <span>Automatic rollback: the optimizer failed repeatedly, so the simpler rule-based planner is active.</span>
            <button onClick={() => act("/api/settings", { policy: "optimizer" }, "Optimizer restored")} className="rounded-md bg-white px-2 py-1 font-medium text-amber-800 ring-1 ring-amber-300 hover:bg-amber-100">Restore optimizer</button>
          </div>
        )}
        {state?.plan?.fallback_used && !state.settings.rolled_back && (
          <div className="border-b border-amber-200 bg-amber-50 px-6 py-2 text-xs text-amber-800">Fallback policy active — {state.plan.fallback_reason}</div>
        )}
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6">{children}</div>
        </main>
      </div>

      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={clsx("pointer-events-auto max-w-sm rounded-lg px-4 py-2.5 text-sm shadow-lg ring-1", t.kind === "ok" ? "bg-white text-slate-800 ring-slate-200" : "bg-rose-50 text-rose-800 ring-rose-200")}>{t.text}</div>
        ))}
      </div>
    </div>
  );
}
