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

export function DrillControls({ zoneId, initial }: { zoneId: string; initial: DrillView }) {
  const router = useRouter();
  const [view, setView] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // Zone changes (this page, the county webhook, the simulated fire) arrive over /live; no polling.
  const connect = useLive((s) => s.connect);
  useEffect(() => connect(), [connect]);
  const live = useLive((s) => s.zones[zoneId]) as { status?: DrillStatus } | undefined;
  const zoneStatus = live?.status ?? view.zoneStatus;

  const act = (fn: () => Promise<DrillView>) =>
    startTransition(async () => {
      try {
        setView(await fn());
        setError(null);
        router.refresh(); // re-render the server "Zone status" line
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
        <p className="text-xs text-muted">Publishing sets the zone status. SET or GO starts calling every home.</p>
      </section>

      <section className="flex flex-col gap-3 rounded border border-line p-4">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">RideOut zone status</dt>
          <dd key={zoneStatus} className="animate-flash rounded font-semibold uppercase">
            {zoneStatus}
            {zoneStatus === "set" || zoneStatus === "go" ? " · calling every home" : ""}
          </dd>
        </dl>
      </section>

      {error && <p className="text-sm text-help">{error}</p>}
    </div>
  );
}
