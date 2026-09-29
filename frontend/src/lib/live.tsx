/* eslint-disable @typescript-eslint/no-explicit-any */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { apiUrl, get, post as rawPost } from "./api";
import type { Decision, State } from "./api";

interface Toast { id: number; kind: "ok" | "err"; text: string }
interface Live {
  state: State | null; decisions: Decision[]; audit: any[]; timeline: any[]; connected: boolean;
  refresh: () => Promise<void>; decide: (id: number, action: "approve" | "reject", label: string) => Promise<void>;
  approveAll: () => Promise<void>; act: (url: string, body?: unknown, okText?: string) => Promise<any>;
  toasts: Toast[]; feed: any[]; streaming: boolean;
}
const Ctx = createContext<Live>(null as unknown as Live);
export const useLive = () => useContext(Ctx);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State | null>(null);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [audit, setAudit] = useState<any[]>([]);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [connected, setConnected] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [feed, setFeed] = useState<any[]>([]);
  const [streaming, setStreaming] = useState(false);
  const seen = useRef<Set<number>>(new Set());
  const busy = useRef(false);
  const queued = useRef(false);
  const hidden = useRef<Set<number>>(new Set());
  const last = useRef(0);
  const tid = useRef(0);

  const refresh = useCallback(async () => {
    if (busy.current) { queued.current = true; return; }  // never drop a refresh: rerun when the current one ends
    busy.current = true;
    try {
      const s = await get<State>("/api/state");
      s.recommendations = s.recommendations.filter((d) => !hidden.current.has(d.id));
      setState(s);
      setConnected(true);
      if (Date.now() - last.current > 2500) {
        last.current = Date.now();
        const [d, a, t] = await Promise.all([get("/api/decisions?limit=200"), get("/api/audit?limit=200"), get("/api/timeline")]);
        setDecisions(d);
        setAudit(a);
        setTimeline(t);
      }
    } catch {
      setConnected(false);
    } finally {
      busy.current = false;
      if (queued.current) { queued.current = false; refresh(); }
    }
  }, []);

  const toastRef = useRef<(k: "ok" | "err", t: string) => void>(() => undefined);
  const pushToast = (k: "ok" | "err", t: string) => toastRef.current(k, t);

  useEffect(() => {
    refresh();
    let es: EventSource | null = null;
    let timer: number | undefined;
    const schedule = () => {
      if (timer) return;
      timer = window.setTimeout(() => { timer = undefined; refresh(); }, 600);
    };
    const connect = () => {
      es = new EventSource(apiUrl("/api/stream"));
      es.addEventListener("hello", () => setStreaming(true));
      es.onmessage = (m) => {
        try {
          const e = JSON.parse(m.data);
          if (seen.current.has(e.id)) return; // reconnect replay can repeat events
          seen.current.add(e.id);
          if (e.type !== "snapshot") {
            setFeed((f) => [e, ...f].slice(0, 40));
            const d = e.data ?? {};
            if (e.type === "audit" && (d.severity === "warn" || d.severity === "error") && ["alert", "recovery", "fallback"].includes(d.kind)) {
              pushToast(d.kind === "recovery" ? "ok" : "err", d.message);
            }
            if (e.type === "sim.degraded") pushToast("err", "Simulator link degraded — using cached data");
            if (e.type === "sim.recovered") pushToast("ok", "Simulator link recovered");
          }
        } catch { /* ignore malformed event */ }
        schedule();
      };
      es.onerror = () => { setStreaming(false); es?.close(); setTimeout(connect, 2000); };
    };
    connect();
    const poll = window.setInterval(refresh, 5000);
    return () => { es?.close(); clearInterval(poll); };
  }, [refresh]);

  const toast = useCallback((kind: "ok" | "err", text: string) => {
    const id = ++tid.current;
    setToasts((t) => [...t, { id, kind, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);

  toastRef.current = toast;

  const act = useCallback(async (url: string, body?: unknown, okText = "Done") => {
    try {
      const r = await rawPost(url, body);
      toast("ok", okText);
      last.current = 0;
      await refresh();
      return r;
    } catch (e: any) {
      toast("err", String(e.message || e).slice(0, 200));
    }
  }, [refresh, toast]);

  // optimistic: the card disappears the moment the operator clicks; rolled back if the server refuses
  const decide = useCallback(async (id: number, action: "approve" | "reject", label: string) => {
    hidden.current.add(id);
    setState((s) => (s ? { ...s, recommendations: s.recommendations.filter((d) => d.id !== id) } : s));
    try {
      await rawPost(`/api/decisions/${id}/${action}`);
      toast("ok", label);
    } catch (e: any) {
      let msg = String(e.message || e);
      try { msg = JSON.parse(msg).detail ?? msg; } catch { /* plain text */ }
      toast("err", msg);
      hidden.current.delete(id);
    }
    last.current = 0;
    await refresh();
  }, [refresh, toast]);

  const approveAll = useCallback(async () => {
    const ids = (state?.recommendations ?? []).map((d) => d.id);
    ids.forEach((i) => hidden.current.add(i));
    setState((s) => (s ? { ...s, recommendations: [] } : s));
    try {
      await rawPost("/api/decisions/approve-all");
      toast("ok", `${ids.length} recommendations approved and dispatched`);
    } catch (e: any) {
      ids.forEach((i) => hidden.current.delete(i));
      toast("err", String(e.message || e).slice(0, 200));
    }
    last.current = 0;
    await refresh();
  }, [state, refresh, toast]);

  const value = useMemo(
    () => ({ state, decisions, audit, timeline, connected, refresh, decide, approveAll, act, toasts, feed, streaming }),
    [state, decisions, audit, timeline, connected, refresh, decide, approveAll, act, toasts, feed, streaming],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
