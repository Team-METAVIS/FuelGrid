import clsx from "clsx";
import type { ReactNode } from "react";
import type { Sev } from "../lib/api";

export function Card({ title, subtitle, action, children, className, pad = true }: {
  title?: ReactNode; subtitle?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={clsx("rounded-xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
          <div>
            <h2 className="text-[13px] font-semibold text-slate-900">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={clsx(pad && "p-5")}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone = "default", icon }: {
  label: string; value: ReactNode; hint?: ReactNode; tone?: "default" | "good" | "warn" | "bad"; icon?: ReactNode;
}) {
  const color = { default: "text-slate-900", good: "text-emerald-600", warn: "text-amber-600", bad: "text-rose-600" }[tone];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex items-center justify-between text-xs font-medium text-slate-500">
        <span>{label}</span>
        <span className="text-slate-400">{icon}</span>
      </div>
      <div className={clsx("tabular mt-2 text-2xl font-semibold tracking-tight", color)}>{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

const sevStyles: Record<string, string> = {
  CRITICAL: "bg-rose-50 text-rose-700 ring-rose-200",
  WARNING: "bg-amber-50 text-amber-700 ring-amber-200",
  WATCH: "bg-sky-50 text-sky-700 ring-sky-200",
  OK: "bg-emerald-50 text-emerald-700 ring-emerald-200",
};
export function SevBadge({ sev, children }: { sev: Sev | string; children?: ReactNode }) {
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", sevStyles[sev] ?? sevStyles.OK)}>
      {children ?? sev}
    </span>
  );
}

const tones: Record<string, string> = {
  slate: "bg-slate-100 text-slate-700 ring-slate-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-700 ring-amber-200",
  red: "bg-rose-50 text-rose-700 ring-rose-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200",
};
export function Badge({ tone = "slate", children }: { tone?: keyof typeof tones; children: ReactNode }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", tones[tone])}>
      {children}
    </span>
  );
}

export function statusTone(s: string): keyof typeof tones {
  if (["EXECUTED", "healthy", "OPEN", "AVAILABLE", "RUNNING", "ARRIVED"].includes(s)) return "green";
  if (["FAILED", "down", "OUTAGE", "DISRUPTED"].includes(s)) return "red";
  if (["APPROVED", "PROPOSED"].includes(s)) return "indigo";
  if (["EXPIRED", "REJECTED", "PAUSED", "disabled", "SCHEDULED"].includes(s)) return "slate";
  return "amber";
}

type BtnProps = {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "ghost" | "danger" | "warn";
  size?: "sm" | "md"; disabled?: boolean; icon?: ReactNode; className?: string;
};
export function Button({ children, onClick, variant = "secondary", size = "md", disabled, icon, className }: BtnProps) {
  const v = {
    primary: "bg-brand-600 text-white hover:bg-brand-700 shadow-sm",
    secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
    danger: "bg-white text-rose-700 ring-1 ring-inset ring-rose-200 hover:bg-rose-50",
    warn: "bg-white text-amber-700 ring-1 ring-inset ring-amber-200 hover:bg-amber-50",
  }[variant];
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={clsx("inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition disabled:cursor-not-allowed disabled:opacity-50", size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-3.5 py-2 text-sm", v, className)}
    >
      {icon}
      {children}
    </button>
  );
}

export function Bar({ value, sev = "OK", className }: { value: number; sev?: string; className?: string }) {
  const color = ({ CRITICAL: "bg-rose-500", WARNING: "bg-amber-500", WATCH: "bg-sky-500", OK: "bg-emerald-500" } as Record<string, string>)[sev] ?? "bg-emerald-500";
  return (
    <div className={clsx("h-2 w-full overflow-hidden rounded-full bg-slate-100", className)}>
      <div className={clsx("h-full rounded-full transition-all duration-500", color)} style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }} />
    </div>
  );
}

export function Empty({ icon, title, text }: { icon?: ReactNode; title: string; text?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-10 text-center">
      <div className="text-slate-300">{icon}</div>
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {text && <p className="max-w-sm text-xs text-slate-500">{text}</p>}
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Toggle({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <div>
        <div className="text-sm font-medium text-slate-800">{label}</div>
        {hint && <div className="text-xs text-slate-500">{hint}</div>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={clsx("relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition", checked ? "bg-brand-600" : "bg-slate-300")}
      >
        <span className={clsx("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", checked ? "left-[18px]" : "left-0.5")} />
      </button>
    </div>
  );
}

export function Th({ children, right }: { children?: ReactNode; right?: boolean }) {
  return (
    <th className={clsx("whitespace-nowrap border-b border-slate-200 bg-slate-50 px-4 py-2.5 text-xs font-medium text-slate-500", right ? "text-right" : "text-left")}>
      {children}
    </th>
  );
}
export function Td({ children, right, className }: { children?: ReactNode; right?: boolean; className?: string }) {
  return (
    <td className={clsx("tabular whitespace-nowrap border-b border-slate-100 px-4 py-2.5 text-[13px] text-slate-700", right && "text-right", className)}>
      {children}
    </td>
  );
}
