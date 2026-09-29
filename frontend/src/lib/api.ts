/* eslint-disable @typescript-eslint/no-explicit-any */
export type Sev = "OK" | "WATCH" | "WARNING" | "CRITICAL";

export interface FuelLevel { inventory: number; capacity: number }
export interface Station { id: string; name: string; region_id: string; status: string; profile: string; demand_multiplier: number; fuels: Record<string, FuelLevel> }
export interface Depot { id: string; name: string; region_id: string; status: string; dispatch_capacity: number; fuels: Record<string, FuelLevel> }
export interface Route { id: string; source_depot_id: string; destination_station_id: string; transit_ticks: number; max_shipment: number; status: string }
export interface Risk {
  station_id: string; fuel: string; inventory: number; capacity: number; incoming: number; demand_horizon: number;
  hours_to_stockout: number | null; stockout_prob: number; severity: Sev; confidence: number; signals: string[];
}
export interface Decision {
  id: number; tick: number; station_id: string; fuel: string; depot_id: string; route_id: string; quantity: number; severity: Sev;
  hours_to_stockout: number | null; inventory: number; demand_horizon: number; risk_before: number; risk_after: number;
  unmet_before: number; unmet_after: number; confidence: number; policy: string; reasons: string[]; alternatives: any[];
  requires_review: boolean; review_reason: string | null; status: string; actor: string; result: string | null; created_at: number;
}
export interface Health {
  status: string; mode: string; stale: boolean; snapshot_age_s: number | null; version: string;
  components: Record<string, { status: string; detail: string; mape?: number | null; last_cycle_ms?: number; breaker_open?: boolean }>;
  api: { requests: number; avg_ms: number; p95_ms: number; error_rate: number; rps: number };
  process: { cpu_pct: number; rss_mb: number; uptime_s: number };
}
export interface Settings {
  auto_execute: boolean; policy: string; forecaster: string; paused: boolean; max_auto_liters: number;
  min_confidence: number; decision_every_ticks: number; rolled_back: boolean;
}
export interface State {
  ready: boolean; health: Health;
  instance: { tick: number; sim_time: string; status: string; tick_minutes: number; scenario_id: string; seed: number };
  metrics: { service_level: number; unmet_demand_liters: number; served_demand_liters: number; allocation_liters: number; allocation_failures: number };
  stations: Station[]; depots: Depot[]; routes: Route[]; in_transit: any[]; supply_arrivals: any[]; events: any[];
  demand: Record<string, Record<string, number[]>>; risks: Risk[]; recommendations: Decision[];
  incidents: { key: string; type: string; severity: string; message: string; since_tick: number }[];
  plan: { policy: string; solver_status: string; runtime_ms: number; fallback_used: boolean; fallback_reason: string | null; tick: number; notes: string[]; forecast_model: string; comparison: Record<string, any>; cadence_ticks: number | null; bottlenecks: any[] } | null;
  settings: Settings;
  regions: any[]; eta: { routes: any[]; shipments: any[]; supply: any[]; supply_mean_late_ticks: number; supply_delayed_share: number };
  source: { kind: string; label: string; supports_admin: boolean };
}

const KEY = "fuelgrid_api_key";
export const apiKey = {
  get: () => { try { return localStorage.getItem(KEY) ?? ""; } catch { return ""; } },
  set: (v: string) => { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch { /* storage unavailable */ } },
};
/** Where the API lives. Empty = same origin (the Docker image serves both). Set VITE_API_BASE when the console is hosted separately (e.g. Vercel). */
export const API_BASE = ((import.meta as any).env?.VITE_API_BASE ?? "").replace(/\/+$/, "");
export const apiUrl = (path: string) => (path.startsWith("http") ? path : API_BASE + path);
const authHeaders = (): Record<string, string> => (apiKey.get() ? { "x-api-key": apiKey.get() } : {});

export async function get<T = any>(url: string): Promise<T> {
  const r = await fetch(apiUrl(url), { headers: authHeaders() });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/** Write actions: sends the operator key; on 401 asks the console to prompt for it. */
export async function post<T = any>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(apiUrl(url), { method: "POST", headers: { "content-type": "application/json", ...authHeaders() }, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) {
    window.dispatchEvent(new Event("fuelgrid-auth-required"));
    throw new Error("An operator API key is required for this action.");
  }
  if (!r.ok) {
    const text = (await r.text()).slice(0, 400);
    try { throw new Error(JSON.parse(text).detail ?? text); } catch (e) { throw e instanceof SyntaxError ? new Error(text) : e; }
  }
  return r.json();
}
