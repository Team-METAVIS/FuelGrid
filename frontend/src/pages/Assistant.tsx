import { Send, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge, Card, PageHeader } from "../components/ui";
import { get, post } from "../lib/api";

interface Msg { role: "user" | "bot"; text: string; mode?: string; provider?: string; model?: string }
const SUGGESTED = [
  "What is happening right now?",
  "Which stations are at risk?",
  "What should I approve next?",
  "Why is mirpur diesel low?",
  "Are there any incidents?",
  "Is the optimizer better than doing nothing?",
  "Is the system healthy?",
];

export default function Assistant() {
  const [msgs, setMsgs] = useState<Msg[]>([{ role: "bot", text: "Hello. Ask me about fuel levels, risks, recommendations, incidents or system health. I answer from live data and never take actions myself.", mode: "grounded" }]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [ai, setAi] = useState<any>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { get("/api/assistant/status").then(setAi).catch(() => undefined); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const ask = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setQ(""); setBusy(true);
    try {
      const r = await post("/api/assistant", { question });
      setMsgs((m) => [...m, { role: "bot", text: r.answer, mode: r.mode, provider: r.provider, model: r.model }]);
      get("/api/assistant/status").then(setAi).catch(() => undefined);
    } catch {
      setMsgs((m) => [...m, { role: "bot", text: "Sorry, I could not reach the FuelGrid server.", mode: "error" }]);
    }
    setBusy(false);
  };

  return (
    <>
      <PageHeader title="Ops assistant" description="Plain-language answers about the live situation. It explains; it never decides or acts." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" pad={false}>
          <div className="flex h-[60vh] flex-col">
            <div className="flex-1 space-y-3 overflow-y-auto p-5">
              {msgs.map((m, i) => (
                <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                  <div className={m.role === "user" ? "max-w-[80%] rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2.5 text-sm text-white" : "max-w-[85%] rounded-2xl rounded-bl-sm bg-slate-100 px-4 py-2.5 text-sm text-slate-800"}>
                    {m.text}
                    {m.role === "bot" && m.mode && m.mode !== "error" && i > 0 && (
                      <div className="mt-1.5 flex items-center gap-1 text-[11px] text-slate-500"><ShieldCheck size={11} />{m.mode === "llm" ? `Reworded by ${m.provider === "gemini" ? "Gemini" : "Groq"} (${m.model}); numbers verified against live data` : "Built directly from live data"}</div>
                    )}
                  </div>
                </div>
              ))}
              {busy && <div className="text-xs text-slate-400">Thinking…</div>}
              <div ref={end} />
            </div>
            <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex gap-2 border-t border-slate-100 p-3">
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about stations, risks, recommendations…" className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100" />
              <button disabled={busy || q.trim().length < 2} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"><Send size={14} /> Ask</button>
            </form>
          </div>
        </Card>
        <div className="space-y-4">
          <Card title={<span className="flex items-center gap-2"><Sparkles size={14} className="text-brand-600" />Try asking</span>}>
            <div className="flex flex-wrap gap-2">
              {SUGGESTED.map((s) => <button key={s} onClick={() => ask(s)} className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 hover:border-brand-500 hover:text-brand-700">{s}</button>)}
            </div>
          </Card>
          <Card title="AI providers" subtitle="Free models, rotated automatically">
            {!ai ? <div className="text-xs text-slate-400">Checking…</div> : !ai.configured ? (
              <div className="text-xs text-slate-600">No API key set, so answers are built directly from live data. Add <code className="rounded bg-slate-100 px-1">GEMINI_API_KEY</code> (and optionally <code className="rounded bg-slate-100 px-1">GROQ_API_KEY</code> as backup) to <code className="rounded bg-slate-100 px-1">.env</code> to enable rewording.</div>
            ) : (
              <ul className="space-y-3 text-xs">
                {ai.providers.map((p: any) => (
                  <li key={p.provider}>
                    <div className="flex items-center justify-between"><span className="font-medium capitalize text-slate-800">{p.provider}{p.provider === "groq" ? " (backup)" : ""}</span><Badge tone={!p.configured ? "slate" : p.active ? "green" : "amber"}>{!p.configured ? "not set" : p.active ? "ready" : "paused"}</Badge></div>
                    {p.configured && <div className="mt-1 space-y-0.5 text-slate-500">
                      <div>{p.models_discovered} models discovered · using {p.next_models[0] ?? "—"}</div>
                      {p.models_cooling.length > 0 && <div>cooling down: {p.models_cooling.join(", ")}</div>}
                      {p.last_error && <div className="text-amber-700">last issue: {p.last_error}</div>}
                    </div>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="How it works">
            <ul className="space-y-2 text-xs text-slate-600">
              <li>Every answer is assembled from the same live numbers as the dashboard.</li>
              <li>It cannot approve, reject or change anything.</li>
              <li>If a free language model is configured (Gemini, with Groq as backup) it may only reword the answer; any reply containing a number not in the data is discarded and the next model is tried.</li>
              <li>With no outside service, the assistant still works fully.</li>
            </ul>
            <div className="mt-3"><Badge tone="green">Grounded</Badge> <Badge tone="slate">Read-only</Badge></div>
          </Card>
        </div>
      </div>
    </>
  );
}
