"use client";

/**
 * /system: under the hood. Every number comes from GET /system/metrics:
 * live calls in the database, evals/run.py results, data/sim-results.json, the census and the audit log.
 * A missing source shows as "not measured yet", never as a made-up number.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { SimBadge } from "@/components/Shell";
import { AnimatedNumber, AppHeader, Ring } from "@/components/ui";
import { api, type EvalSummary, type SystemMetrics } from "@/lib/api";
import { useLive } from "@/lib/live";

const FIELD_LABEL: Record<string, string> = {
  canLeave: "Can leave",
  peopleCount: "People",
  pets: "Pets",
  hasCar: "Car",
  mobility: "Mobility",
  medical: "Medical",
  assistance: "Help out",
};

const ms = (v: number | null | undefined) => (v == null ? "—" : v < 10 ? `${v.toFixed(1)}` : `${Math.round(v)}`);
const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);

function Card({
  title,
  sim,
  className = "",
  children,
}: {
  title: string;
  sim?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`card flex animate-rise flex-col gap-4 p-6 ${className}`}>
      <h2 className="flex items-center justify-between gap-2">
        <span className="eyebrow">{title}</span>
        {sim && <SimBadge />}
      </h2>
      {children}
    </section>
  );
}

function Big({ value, unit, label }: { value: string; unit?: string; label: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span key={value} className="flex items-baseline gap-1">
        <span className="animate-flash rounded text-[2rem] leading-none font-semibold tracking-[-0.04em] tabular-nums">{value}</span>
        {unit && value !== "—" && <span className="text-sm text-muted">{unit}</span>}
      </span>
      <span className="text-xs text-muted">{label}</span>
    </div>
  );
}

function Missing({ children }: { children: React.ReactNode }) {
  return <p className="rounded-2xl border border-dashed border-line px-4 py-6 text-center text-sm text-muted">{children}</p>;
}

/** data/sim-results.json from the impact simulation (api/sim/compare.py). */
type SimResults = {
  label?: string;
  metric?: string;
  runs?: number;
  bars?: { key: string; label: string; available?: boolean; median?: number; min?: number; max?: number }[];
  headline?: { text?: string };
};

function Dispatch({ d }: { d: SimResults }) {
  const bars = (d.bars ?? []).filter((b) => b.available !== false && typeof b.median === "number");
  return (
    <>
      <ul className="flex flex-col gap-5">
        {bars.map((b) => {
          const today = b.key === "today";
          return (
            <li key={b.key} className="flex flex-col gap-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium">{b.label}</span>
                <span className="flex items-baseline gap-1.5">
                  <span className={`text-2xl font-semibold tracking-[-0.03em] tabular-nums ${today ? "text-help" : "text-accent"}`}>
                    <AnimatedNumber value={Math.round(b.median!)} />%
                  </span>
                  {b.min != null && b.max != null && (
                    <span className="font-mono text-xs text-muted">
                      {Math.round(b.min)}–{Math.round(b.max)}
                    </span>
                  )}
                </span>
              </div>
              <div className="relative h-3 overflow-hidden rounded-full bg-panel-2">
                {b.min != null && b.max != null && (
                  <div
                    className={`absolute h-full ${today ? "bg-help/20" : "bg-accent/20"}`}
                    style={{ left: `${b.min}%`, width: `${b.max - b.min}%` }}
                  />
                )}
                <div
                  className={`absolute h-full rounded-full transition-[width] duration-1000 ${
                    today ? "bg-help" : "bg-gradient-to-r from-accent to-accent-2"
                  }`}
                  style={{ width: `${b.median}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
      <p className="text-sm leading-relaxed text-muted">
        {d.metric}
        {d.runs ? ` ${d.runs} simulated runs.` : ""} {d.label}
      </p>
    </>
  );
}

export default function SystemPage() {
  const connect = useLive((s) => s.connect);
  useEffect(() => connect(), [connect]);
  const connected = useLive((s) => s.connected);
  const turnCount = useLive((s) => s.turns.length);
  const [m, setM] = useState<SystemMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);

  const load = useCallback(async () => {
    last.current = Date.now();
    try {
      setM(await api.systemMetrics());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "API unreachable");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, connected]);

  // New call turns arrive over /live: refresh the numbers at most every 5 s (no polling).
  useEffect(() => {
    if (!turnCount) return;
    const wait = Math.max(0, 5000 - (Date.now() - last.current));
    const t = setTimeout(() => void load(), wait);
    return () => clearTimeout(t);
  }, [turnCount, load]);

  const script: EvalSummary | undefined = m?.evals?.modes?.script?.summary;
  const answers: EvalSummary | undefined = m?.evals?.modes?.answers?.summary;
  const real = m?.live.latencyMs.realPhone;

  return (
    <main className="min-h-dvh">
      <AppHeader />
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-4 py-8 sm:px-6 sm:py-10">
        <div className="card flex items-center gap-3 rounded-2xl! px-5 py-3 text-sm text-muted shadow-none!">
          <span className={`h-1.5 w-1.5 rounded-full ${error ? "bg-help" : connected ? "bg-out" : "bg-unknown"}`} />
          {error
            ? `Can't reach the API (${error}).`
            : "Connected to live data · every number on this page comes from the running system"}
        </div>

        <section className="grid items-center gap-8 lg:grid-cols-[1.1fr_1fr]">
          <div className="flex flex-col gap-5">
            <span className="eyebrow">Under the hood</span>
            <h1 className="display text-5xl sm:text-6xl">
              Every number,
              <br />
              <span className="text-muted">measured.</span>
            </h1>
            <p className="max-w-lg text-[17px] leading-relaxed text-muted">
              Honesty, speed and dispatch results come straight from the running API, the evals and the simulation. If a
              number isn&apos;t measured yet, this page says so.
            </p>
            <p className="flex items-center gap-2 text-sm text-muted">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6z" strokeLinejoin="round" />
              </svg>
              The AI never writes ride status, ETAs or driver names. Code does.
            </p>
          </div>

          <div className="overflow-hidden rounded-[1.75rem] bg-gradient-to-br from-night to-night-2 p-7 text-white shadow-[var(--shadow-float)]">
            <div className="flex items-center justify-between">
              <span className="eyebrow text-white/60" style={{ "--eyebrow-dot": "#8fa6ff" } as React.CSSProperties}>
                Honesty at a glance
              </span>
              <span className="rounded-full border border-white/15 px-2.5 py-0.5 text-[11px] text-white/70">
                {m?.evals?.judge ? "Model judge" : "Checked by code"}
              </span>
            </div>
            {script ? (
              <div className="mt-6 flex flex-col items-center gap-6 sm:flex-row sm:items-center">
                <Ring value={script.honesty.turnsPassed} max={script.honesty.turnsJudged} tone="#8fa6ff">
                  <span className="text-[2rem] leading-none font-semibold tracking-[-0.04em] tabular-nums">
                    <AnimatedNumber value={Math.round((script.honesty.turnsPassed / Math.max(1, script.honesty.turnsJudged)) * 100)} />
                    <span className="text-base text-white/70">%</span>
                  </span>
                  <span className="mt-1 text-[11px] text-white/60">turns passed</span>
                </Ring>
                <div className="flex flex-col gap-2">
                  <p className="text-[1.6rem] leading-tight font-semibold tracking-[-0.03em]">No promise before a driver says yes.</p>
                  <p className="text-sm text-white/70">
                    {script.honesty.turnsPassed} of {script.honesty.turnsJudged} agent turns, {script.personas} simulated personas.
                  </p>
                  <p className="text-sm text-white/70">
                    The guard dropped {m?.live.acks.blocked ?? 0} of {m?.live.acks.proposed ?? 0} AI acknowledgments on live calls.
                  </p>
                </div>
              </div>
            ) : (
              <p className="mt-6 text-white/70">Not measured yet. Run evals/run.py.</p>
            )}
            <div className="mt-7 flex flex-wrap items-baseline gap-x-8 gap-y-2 border-t border-white/10 pt-5 text-sm text-white/70">
              <span>
                <span className="mr-1.5 text-xl font-semibold text-white tabular-nums">
                  <AnimatedNumber value={m?.live.calls ?? 0} />
                </span>
                calls so far
              </span>
              <span>
                <span className="mr-1.5 text-xl font-semibold text-white tabular-nums">{ms(real?.p50)}</span>
                {real?.p50 != null ? "ms median turn" : "median turn (no real calls yet)"}
              </span>
            </div>
          </div>
        </section>

        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          <Card title="Voice turn latency">
            <div className="grid grid-cols-2 gap-6">
              <Big value={ms(real?.p50)} unit="ms" label={`real phone p50 · ${real?.turns ?? 0} turns`} />
              <Big value={ms(real?.p95)} unit="ms" label="real phone p95" />
              <Big
                value={ms(m?.live.latencyMs.standIns.p50)}
                unit="ms"
                label={`stand-ins p50 · ${m?.live.latencyMs.standIns.turns ?? 0} turns`}
              />
              <Big value={ms(m?.live.latencyMs.standIns.p95)} unit="ms" label="stand-ins p95" />
            </div>
            <p className="text-sm leading-relaxed text-muted">
              Measured inside the API, per turn. Interpreter:{" "}
              {Object.entries(m?.live.interpreter ?? {})
                .map(([k, v]) => `${k} ${v}`)
                .join(", ") || "—"}
              {m?.live.fallbacks ? ` · ${m.live.fallbacks} fallbacks` : ""}. Budget: interpreter ≤ 1,000 ms at p50.
            </p>
          </Card>

          <Card title="Dispatch vs. today" sim className="xl:col-span-2">
            {m?.dispatch ? (
              <Dispatch d={m.dispatch as unknown as SimResults} />
            ) : (
              <Missing>Waiting for the impact simulation (data/sim-results.json).</Missing>
            )}
          </Card>

          <Card title="What the agent heard" sim>
            {script && answers ? (
              <>
                <table className="w-full text-sm">
                  <thead className="text-[11px] uppercase tracking-[0.08em] text-muted">
                    <tr>
                      <th className="pb-2 text-left font-medium">Field</th>
                      <th className="pb-2 text-right font-medium">Own words</th>
                      <th className="pb-2 text-right font-medium">Direct</th>
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {Object.keys(answers.fieldAccuracy).map((f) => (
                      <tr key={f} className="border-t border-line/70">
                        <td className="py-2">{FIELD_LABEL[f] ?? f}</td>
                        <td className="py-2 text-right font-mono text-[13px]">{pct(script.fieldAccuracy[f])}</td>
                        <td className="py-2 text-right font-mono text-[13px]">{pct(answers.fieldAccuracy[f])}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-sm leading-relaxed text-muted">
                  {script.personas} fictional personas (EN + ES) through the real agent. &quot;Own words&quot;: each persona
                  says its own lines whatever is asked. &quot;Direct&quot;: it answers each question. Corrections caught:{" "}
                  {answers.correctionsCaught}. Interpreter: {m?.evals?.interpreterConfigured}.
                </p>
              </>
            ) : (
              <Missing>Not measured yet. Run evals/run.py.</Missing>
            )}
          </Card>

          <Card title="Census right now">
            <dl className="grid grid-cols-2 gap-3">
              {Object.entries(m?.census.reach ?? {}).map(([k, v]) => (
                <div key={k} className="rounded-2xl bg-panel-2 px-4 py-3">
                  <dd className="text-xl font-semibold tracking-[-0.02em] tabular-nums">
                    <AnimatedNumber value={v} />
                  </dd>
                  <dt className="text-xs text-muted">{k.replace(/_/g, " ")}</dt>
                </div>
              ))}
              <div className="rounded-2xl bg-panel-2 px-4 py-3">
                <dd className="text-xl font-semibold tracking-[-0.02em] text-fire tabular-nums">
                  <AnimatedNumber value={Object.values(m?.census.openRequests ?? {}).reduce((a, b) => a + b, 0)} />
                </dd>
                <dt className="text-xs text-muted">open ride requests</dt>
              </div>
              <div className="rounded-2xl bg-panel-2 px-4 py-3">
                <dd className="text-xl font-semibold tracking-[-0.02em] tabular-nums">
                  <AnimatedNumber value={m?.census.duplicatesMerged ?? 0} />
                </dd>
                <dt className="text-xs text-muted">duplicates merged</dt>
              </div>
            </dl>
          </Card>

          <Card title="How a turn works">
            <ol className="flex flex-col gap-3 text-sm">
              {[
                "ElevenLabs turns speech into text and sends it to /agent/turn.",
                "Gemini turns the words into record fields (Claude if Gemini is slow).",
                "Code picks the next question. Templates write every ride sentence.",
                "The honesty guard drops any AI words that sound like a promise.",
                "ElevenLabs speaks the reply. The record and the map update live.",
              ].map((s, i) => (
                <li key={i} className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/10 font-mono text-[11px] font-semibold text-accent">
                    {i + 1}
                  </span>
                  <span className="pt-0.5 leading-relaxed text-muted">{s}</span>
                </li>
              ))}
            </ol>
          </Card>

          <Card title="Audit trail" className="md:col-span-2 xl:col-span-3">
            {(m?.audit ?? []).length ? (
              <ol className="scroll-soft flex max-h-80 flex-col overflow-y-auto">
                {(m?.audit ?? []).map((a) => (
                  <li key={a.id} className="grid grid-cols-[5.5rem_9rem_1fr] items-baseline gap-3 border-b border-line/60 py-2 text-[13px] last:border-0">
                    <span className="font-mono text-xs text-muted tabular-nums">
                      {new Date(a.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </span>
                    <span className="truncate font-medium text-ink">{a.kind}</span>
                    <span className="truncate text-muted">{a.message}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <Missing>Nothing logged yet.</Missing>
            )}
          </Card>
        </div>
      </div>
    </main>
  );
}
