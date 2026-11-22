"use client";

/**
 * Call floor. Left: every call, live ones first. Right: the selected call's transcript
 * streaming in over /live (`call.turn`), the household record filling (`household.updated`),
 * and a latency chip on every agent turn. REST only on load and after a reconnect.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatedNumber, AppHeader } from "@/components/ui";
import { api, type CallDetail as Detail, type CallSummary, type CallTurn, type HouseholdRecord } from "@/lib/api";
import { useLive } from "@/lib/live";
import { CallDetail } from "./CallDetail";
import { CallList } from "./CallList";

type LiveTurn = CallTurn & { callId: string; householdId: string };
type Correction = { field: string; from: unknown; to: unknown; at: string };

function useNow(everyMs: number) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(t);
  }, [everyMs]);
  return now;
}

/** Turns newer than `since` (ISO strings from the same encoder compare correctly as text). */
const newer = (turns: LiveTurn[] | undefined, since?: string | null) =>
  (turns ?? []).filter((t) => !since || (t.at ?? "") > since);

export default function CallsPage() {
  const connect = useLive((s) => s.connect);
  useEffect(() => connect(), [connect]);
  const connected = useLive((s) => s.connected);
  const liveEvents = useLive((s) => s.turns);
  const households = useLive((s) => s.households);
  const requests = useLive((s) => s.requests);

  const [calls, setCalls] = useState<Record<string, CallSummary>>({});
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"live" | "ended">("live");
  const [error, setError] = useState<string | null>(null);
  const now = useNow(5000);

  const loadList = useCallback(async () => {
    try {
      const rows = await api.calls();
      setCalls(Object.fromEntries(rows.map((r) => [r.id, r])));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "API unreachable");
    }
  }, []);

  // Load on mount and again after every reconnect, so nothing is missed while the socket was down.
  useEffect(() => {
    void loadList();
  }, [loadList, connected]);

  const liveByCall = useMemo(() => {
    const m = new Map<string, LiveTurn[]>();
    for (const e of liveEvents) {
      const t = e.data as unknown as LiveTurn;
      if (!t?.callId) continue;
      const list = m.get(t.callId) ?? [];
      list.push({ ...t, at: t.at ?? e.at });
      m.set(t.callId, list);
    }
    return m;
  }, [liveEvents]);

  // A turn for a call we've never seen means a new call connected: refresh the list once.
  const unknownCalls = useMemo(() => [...liveByCall.keys()].filter((id) => !calls[id]).length, [liveByCall, calls]);
  useEffect(() => {
    if (unknownCalls) void loadList();
  }, [unknownCalls, loadList]);

  const merged = useMemo(
    () =>
      Object.values(calls).map((c) => {
        const hh = households[c.householdId] as CallSummary["household"] | undefined;
        const household = c.household && hh ? { ...c.household, role: hh.role, record: hh.record, reach: hh.reach } : c.household;
        const extra = newer(liveByCall.get(c.id), c.updatedAt);
        if (!extra.length) return { ...c, household };
        const last = extra[extra.length - 1];
        return {
          ...c,
          household,
          updatedAt: last.at,
          lastText: last.text,
          lastSpeaker: last.speaker,
          turnCount: c.turnCount + extra.length,
          stage: last.stage ?? c.stage,
          done: c.done || last.stage === "goodbye",
        };
      }),
    [calls, households, liveByCall],
  );

  const liveCalls = merged.filter((c) => !c.done).sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  const ended = merged
    .filter((c) => c.done)
    .sort((a, b) => (b.endedAt ?? b.updatedAt ?? "").localeCompare(a.endedAt ?? a.updatedAt ?? ""));
  const visible = tab === "live" ? liveCalls : ended;
  const current = selected ?? visible[0]?.id ?? null;
  const currentCall = merged.find((c) => c.id === current) ?? null;
  const needsRide = merged.filter((c) => c.household?.role === "needs_ride").length;

  useEffect(() => {
    if (!current) return;
    let cancelled = false;
    api
      .call(current)
      .then((d) => !cancelled && setDetail(d))
      .catch(() => !cancelled && setDetail(null));
    return () => {
      cancelled = true;
    };
  }, [current, connected]);

  const shownDetail = detail && detail.id === current ? detail : null;
  const turns = useMemo(() => {
    if (!shownDetail) return [];
    const last = shownDetail.turns[shownDetail.turns.length - 1]?.at;
    return [...shownDetail.turns, ...newer(liveByCall.get(shownDetail.id), last)];
  }, [shownDetail, liveByCall]);

  const hhLive = currentCall ? (households[currentCall.householdId] as Record<string, unknown> | undefined) : undefined;
  const record = (hhLive?.record ?? shownDetail?.household?.record) as HouseholdRecord | undefined;
  const corrections = ((hhLive?.corrections ?? shownDetail?.household?.corrections) ?? []) as Correction[];
  const liveRequest = currentCall
    ? Object.values(requests).find((r) => r.householdId === currentCall.householdId && r.status !== "closed")
    : undefined;
  const lastStatus = [...turns].reverse().find((t) => t.speaker === "agent")?.requestStatus;
  const requestStatus = ((liveRequest?.status as string | undefined) ?? shownDetail?.request?.status ?? lastStatus) || null;

  return (
    <main className="flex h-dvh flex-col">
      <AppHeader />
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-line px-4 pt-6 pb-5 sm:px-6">
        <div className="flex flex-col gap-2">
          <span className="eyebrow">Call floor</span>
          <h1 className="display text-3xl sm:text-4xl">
            Every call, <span className="text-muted">as it happens.</span>
          </h1>
        </div>
        <div className="flex items-center gap-3">
          <Counter label="in call" value={liveCalls.length} />
          <Counter label="need a ride" value={needsRide} tone="text-fire" />
          <Counter label="all calls" value={merged.length} />
        </div>
      </div>
      {error && (
        <p className="border-b border-help/30 bg-help/10 px-6 py-2 text-sm text-help">
          Can&apos;t reach the API ({error}). Retrying when the connection comes back.
        </p>
      )}
      <div className="flex min-h-0 flex-1">
        <nav className="flex w-80 shrink-0 flex-col border-r border-line bg-panel">
          <div className="m-3 flex gap-1 rounded-full border border-line bg-panel-2 p-1">
            {(["live", "ended"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => {
                  setTab(t);
                  setSelected(null);
                }}
                className={`flex-1 rounded-full px-2 py-1.5 text-[13px] transition-colors ${
                  tab === t ? "bg-panel font-medium text-ink shadow-[0_1px_3px_rgb(16_24_40/0.12)]" : "text-muted hover:text-ink"
                }`}
              >
                {t === "live" ? `Live (${liveCalls.length})` : `Ended (${ended.length})`}
              </button>
            ))}
          </div>
          <div className="scroll-soft min-h-0 flex-1 overflow-y-auto">
            <CallList calls={visible} selected={current} onSelect={setSelected} now={now} />
          </div>
        </nav>
        <section className="flex min-w-0 flex-1 flex-col">
          {currentCall ? (
            <CallDetail
              call={currentCall}
              turns={turns}
              record={record}
              corrections={corrections}
              requestStatus={requestStatus}
            />
          ) : (
            <div className="m-auto flex flex-col items-center gap-2 text-center">
              <span className="eyebrow">No call selected</span>
              <p className="text-sm text-muted">Calls appear on the left the moment one connects.</p>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function Counter({ label, value, tone = "text-ink" }: { label: string; value: number; tone?: string }) {
  return (
    <span className="card flex min-w-24 flex-col rounded-2xl! px-4 py-2.5 shadow-none!">
      <span className={`text-2xl leading-none font-semibold tracking-[-0.03em] tabular-nums ${tone}`}>
        <AnimatedNumber value={value} />
      </span>
      <span className="mt-1 text-[11px] text-muted">{label}</span>
    </span>
  );
}
