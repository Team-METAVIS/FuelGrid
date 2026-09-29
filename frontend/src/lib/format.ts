export const n0 = (v: number | null | undefined) => (v == null ? "—" : Math.round(v).toLocaleString("en-US"));
export const liters = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v).toLocaleString("en-US")} L`);
export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : `${(v * 100).toFixed(v > 0 && v < 0.1 && digits === 0 ? 1 : digits)}%`;
export const hours = (v: number | null | undefined) => (v == null ? "None in horizon" : `${v.toFixed(1)} h`);
export const shortId = (id: string) => id.replace(/^(station|depot|route|region)-/, "");
export const title = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
export const simTime = (t?: string) => (t ? t.replace("T", " ").slice(0, 16) : "—");
export const fuelColor: Record<string, string> = { DIESEL: "#4f46e5", PETROL: "#0ea5e9", OCTANE: "#f59e0b" };
