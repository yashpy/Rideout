"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import { API_URL } from "@/lib/api";
import { useLive } from "@/lib/live";

export type DrillStatus = "ready" | "set" | "go" | "clear";

export type DrillView = {
  zoneId: string;
  name: string;
  published: DrillStatus;
  publishedAt?: string | null;
  zoneStatus: DrillStatus;
  zoneSource?: string | null;
  watch: {
    armedUntil?: string | null;
    lastCheckAt?: string | null;
    lastSeen?: string | null;
    lastError?: string | null;
    lastChangeAt?: string | null;
    checks?: number;
  };
  drillUrl: string;
  tinyfishConfigured: boolean;
  usage: { fetchesToday: number; dailyCap: number };
};

const STATUSES: DrillStatus[] = ["ready", "set", "go", "clear"];

async function post(path: string, body: unknown): Promise<DrillView> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail ?? res.statusText);
  return res.json();
}

const time = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";

export function DrillControls({ zoneId, initial }: { zoneId: string; initial: DrillView }) {
  const router = useRouter();
  const [view, setView] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // Zone changes (status flipped by TinyFish, watcher checks) arrive over /live; no polling.
  const connect = useLive((s) => s.connect);
  useEffect(() => connect(), [connect]);
  const live = useLive((s) => s.zones[zoneId]) as
    | { status?: DrillStatus; source?: string; watch?: DrillView["watch"]; drill?: { published?: DrillStatus } }
    | undefined;
  const zoneStatus = live?.status ?? view.zoneStatus;
  const watch = { ...view.watch, ...(live?.watch ?? {}) };
  const armed = !!watch.armedUntil && new Date(watch.armedUntil).getTime() > Date.now();

  const act = (fn: () => Promise<DrillView>) =>
    startTransition(async () => {
      try {
        setView(await fn());
        setError(null);
        router.refresh(); // re-render the server "Zone status" line that TinyFish reads
      } catch (e) {
        setError(e instanceof Error ? e.message : "request failed");
      }
    });

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold tracking-wider text-muted uppercase">Publish a drill status</h2>
        <div className="grid grid-cols-4 gap-2">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              disabled={pending}
              onClick={() => act(() => post(`/zones/${zoneId}/drill`, { published: s }))}
              className={`min-h-12 rounded border text-base font-semibold uppercase ${
                view.published === s ? "border-help bg-help/15 text-help" : "border-line hover:bg-ink/5"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted">
          Publishing only changes this page. RideOut acts when the zone watcher reads the page.
        </p>
      </section>

      <section className="flex flex-col gap-3 rounded border border-line p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">Zone watcher</h2>
            <p className="text-xs text-muted">
              Reads this page while armed (stops by itself).
            </p>
          </div>
          <button
            type="button"
            disabled={pending || !view.tinyfishConfigured}
            onClick={() => act(() => post(`/zones/${zoneId}/drill/watch`, { on: !armed }))}
            className={`min-h-12 rounded px-4 font-semibold ${
              armed ? "border border-line text-ink hover:bg-ink/5" : "bg-vehicle text-bg hover:opacity-90"
            } disabled:opacity-40`}
          >
            {armed ? "Disarm" : "Arm"}
          </button>
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">State</dt>
          <dd>{armed ? `armed until ${time(watch.armedUntil)}` : "off"}</dd>
          <dt className="text-muted">Last read</dt>
          <dd>
            {time(watch.lastCheckAt)}
            {watch.lastSeen ? ` · saw ${watch.lastSeen.toUpperCase()}` : ""}
          </dd>
          <dt className="text-muted">Free fetches today</dt>
          <dd className="tabular-nums">
            {view.usage.fetchesToday} / {view.usage.dailyCap}
          </dd>
          <dt className="text-muted">RideOut zone status</dt>
          <dd key={zoneStatus} className="animate-flash rounded font-semibold uppercase">
            {zoneStatus}
            {zoneStatus === "set" || zoneStatus === "go" ? " · calling every home" : ""}
          </dd>
        </dl>
        {!view.tinyfishConfigured && <p className="text-sm text-help">The zone watcher is not configured on the API.</p>}
        {watch.lastError && <p className="text-sm text-help">{watch.lastError}</p>}
        <p className="truncate text-xs text-muted" title={view.drillUrl}>
          Zone watcher reads: {view.drillUrl}
        </p>
      </section>

      {error && <p className="text-sm text-help">{error}</p>}
    </div>
  );
}
