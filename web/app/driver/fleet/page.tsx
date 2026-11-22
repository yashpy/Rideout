"use client";

/**
 * Fleet board: every driver's screen on one page, with their notifications as they happen.
 *   - one card per vehicle: what that driver's phone shows (offer with countdown, next stop, riders, seats)
 *   - a feed of notifications: new offer, accepted, on the way, picked up, dropped off, assignment changed
 * Read from /vehicles/{id}/run, refreshed on every /live change. It never claims a vehicle (no presence
 * pings), so stand-in drivers keep driving. Accept / Decline here act for that driver (demo).
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SimBadge } from "@/components/Shell";
import { AppHeader } from "@/components/ui";
import { api, type DriverRun, type RunStop } from "@/lib/api";
import { useLive } from "@/lib/live";
import { AddressLink, Avatar, needText, OFFER_SECONDS, OpenMapButton, secondsLeft, type Need } from "../Driver";

type Note = { id: string; at: number; vehicleId: string; driver: string; kind: NoteKind; text: string };
type NoteKind = "offer" | "accepted" | "en_route" | "arrived" | "completed" | "changed";

const NOTE_STYLE: Record<NoteKind, { label: string; tone: string }> = {
  offer: { label: "New pickup", tone: "bg-accent text-white" },
  accepted: { label: "Accepted", tone: "bg-accent/15 text-accent" },
  en_route: { label: "On the way", tone: "bg-accent/15 text-accent" },
  arrived: { label: "Picked up", tone: "bg-out/15 text-out" },
  completed: { label: "At shelter", tone: "bg-out/15 text-out" },
  changed: { label: "Changed", tone: "bg-help/15 text-help" },
};

const seatsOf = (s: RunStop) => Number((s.request.need as Need | undefined)?.seats ?? 1);

/** What changed for one driver between two refreshes → notifications. */
function diff(prev: DriverRun | undefined, next: DriverRun, now: number): Omit<Note, "id">[] {
  if (!prev) return [];
  const driver = String(next.vehicle.driverName ?? next.vehicle.id);
  const base = { at: now, vehicleId: String(next.vehicle.id), driver };
  const out: Omit<Note, "id">[] = [];
  const prevOffers = new Set(prev.offers.map((o) => o.id));
  const prevRun = Object.fromEntries(prev.run.map((s) => [s.id, s]));
  const nextRun = Object.fromEntries(next.run.map((s) => [s.id, s]));
  for (const o of next.offers)
    if (!prevOffers.has(o.id))
      out.push({ ...base, kind: "offer", text: `${o.household.address} · ${needText(o.request.need as Need)}` });
  for (const s of next.run) {
    const was = prevRun[s.id];
    if (!was) {
      if (prevOffers.has(s.id)) out.push({ ...base, kind: "accepted", text: String(s.household.address) });
      continue;
    }
    if (was.request.status !== s.request.status) {
      if (s.request.status === "en_route") out.push({ ...base, kind: "en_route", text: String(s.household.address) });
      if (s.request.status === "arrived")
        out.push({ ...base, kind: "arrived", text: `${s.household.address} · ${seatsOf(s)} on board` });
    }
  }
  for (const s of prev.run)
    if (!nextRun[s.id])
      out.push(
        s.request.status === "arrived"
          ? { ...base, kind: "completed", text: `${seatsOf(s)} dropped off from ${s.household.address}` }
          : { ...base, kind: "changed", text: `${s.household.address} moved to another driver` },
      );
  return out;
}

/** Seats on this trip. Up to 12 seats: one square each (wrapping inside the card); a bus gets a bar. */
function SeatSquares({ run }: { run: DriverRun }) {
  const seats = run.seats;
  if (!seats) return null;
  const label = seats.left === 0 ? "full" : `${seats.left}/${seats.capacity} seats left`;
  if (seats.capacity > 12) {
    const used = (seats.used / seats.capacity) * 100;
    const held = (seats.offered / seats.capacity) * 100;
    return (
      <div className="flex min-w-0 items-center gap-2">
        <div className="relative h-3.5 min-w-0 flex-1 overflow-hidden rounded-full border border-line bg-panel-2" aria-hidden>
          <span className="absolute inset-y-0 left-0 bg-accent" style={{ width: `${used}%` }} />
          <span
            className="absolute inset-y-0 border-l border-dashed border-accent bg-accent/20"
            style={{ left: `${used}%`, width: `${held}%` }}
          />
        </div>
        <span className={`shrink-0 text-xs font-medium ${seats.left === 0 ? "text-help" : "text-muted"}`}>{label}</span>
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <div className="flex flex-wrap gap-1" aria-hidden>
        {Array.from({ length: seats.capacity }, (_, i) => (
          <span
            key={i}
            className={`h-3.5 w-3.5 rounded-[4px] border ${
              i < seats.used
                ? "border-accent bg-accent"
                : i < seats.used + seats.offered
                  ? "border-dashed border-accent bg-accent/15"
                  : "border-line bg-panel-2"
            }`}
          />
        ))}
      </div>
      <span className={`text-xs font-medium ${seats.left === 0 ? "text-help" : "text-muted"}`}>{label}</span>
    </div>
  );
}

function DriverCard({
  run,
  now,
  flash,
  onAct,
}: {
  run: DriverRun;
  now: number;
  flash: boolean;
  onAct: (fn: () => Promise<unknown>) => void;
}) {
  const v = run.vehicle;
  const offers = run.offers.filter((o) => secondsLeft(o.expiresAt, now) > 0);
  const current = run.run.find((s) => s.request.status === "driver_accepted" || s.request.status === "en_route");
  const onboard = run.run.filter((s) => s.request.status === "arrived");
  const people = onboard.reduce((n, s) => n + seatsOf(s), 0);
  const state = offers.length
    ? { text: `${offers.length} new ${offers.length === 1 ? "pickup" : "pickups"}`, tone: "text-accent" }
    : current
      ? { text: current.request.status === "en_route" ? "On the way" : "Next pickup", tone: "text-ink" }
      : people
        ? { text: `${people} on board → shelter`, tone: "text-out" }
        : { text: "Standing by", tone: "text-muted" };

  return (
    <article
      className={`card flex min-w-0 flex-col gap-3 overflow-hidden rounded-3xl! p-4 transition-shadow ${
        flash ? "animate-rise shadow-[0_0_0_3px_color-mix(in_srgb,var(--color-accent)_45%,transparent)]" : ""
      }`}
    >
      <header className="flex items-center gap-3">
        <Avatar name={String(v.driverName ?? v.id)} size="h-10 w-10 text-sm" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-semibold">{String(v.driverName ?? v.id)}</span>
            {!!v.simulated && <SimBadge />}
          </div>
          <div className="text-xs text-muted">{String(v.kind ?? "").replace(/_/g, " ")}</div>
        </div>
        <Link
          href={`/driver?v=${encodeURIComponent(String(v.id))}`}
          className="btn min-h-8 px-2.5 text-xs"
          title="Open this driver's phone screen"
        >
          Open
        </Link>
      </header>
      <div className="flex flex-col gap-2">
        <span className={`text-sm font-semibold ${state.tone}`}>{state.text}</span>
        <SeatSquares run={run} />
      </div>

      {offers.map((o) => {
        const left = secondsLeft(o.expiresAt, now);
        return (
          <div key={o.id} className="rounded-2xl bg-gradient-to-br from-night to-night-2 p-3 text-white">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <span className="text-[10px] font-semibold tracking-[0.12em] text-white/60 uppercase">New pickup</span>
                <AddressLink
                  address={o.household.address}
                  loc={o.household.location}
                  className="block truncate font-semibold"
                />
                <div className="text-xs text-white/70">
                  {needText(o.request.need as Need)} · ~{Math.round(Number(o.etaMinutes ?? 0))} min
                </div>
              </div>
              <span className="font-mono text-sm tabular-nums">
                {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
              </span>
            </div>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-white/15">
              <span className="block h-full bg-[#8fa6ff]" style={{ width: `${(left / OFFER_SECONDS) * 100}%` }} />
            </div>
            <div className="mt-2 grid grid-cols-2 gap-1.5">
              <button className="btn btn-primary min-h-9 text-sm" onClick={() => onAct(() => api.accept(o.id))}>
                Accept
              </button>
              <button
                className="btn min-h-9 border-white/20 bg-white/10 text-sm text-white hover:bg-white/15"
                onClick={() => onAct(() => api.decline(o.id))}
              >
                Decline
              </button>
            </div>
          </div>
        );
      })}

      {run.run.length > 0 && (
        <ol className="flex flex-col gap-1.5">
          {run.run.map((s, i) => (
            <li key={s.id} className="flex items-center gap-2 rounded-xl bg-panel-2/70 px-2.5 py-1.5 text-sm">
              <span className="w-4 shrink-0 text-center font-mono text-[11px] text-muted">{i + 1}</span>
              <span className="min-w-0 flex-1">
                <AddressLink address={s.household.address} loc={s.household.location} className="block truncate" />
                <span className="text-[11px] text-muted">
                  {s.request.status === "arrived"
                    ? "on board"
                    : s === current
                      ? s.request.status === "en_route"
                        ? `on the way · ~${Math.round(Number(s.etaMinutes ?? 0))} min`
                        : "next"
                      : "later"}{" "}
                  · {needText(s.request.need as Need)}
                </span>
              </span>
              <OpenMapButton loc={s.household.location} className="btn min-h-7 shrink-0 px-2 text-[11px]" label="Map" />
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

export default function Fleet() {
  const connect = useLive((s) => s.connect);
  const assignments = useLive((s) => s.assignments);
  const requests = useLive((s) => s.requests);
  const vehiclesLive = useLive((s) => s.vehicles);
  useEffect(() => connect(), [connect]);

  const [runs, setRuns] = useState<Record<string, DriverRun>>({});
  const [notes, setNotes] = useState<Note[]>([]);
  const [flash, setFlash] = useState<Record<string, number>>({});
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);
  const prev = useRef<Record<string, DriverRun>>({});
  const seq = useRef(0);
  const vehicleCount = Object.keys(vehiclesLive).length;

  const refresh = useCallback(async () => {
    try {
      const vehicles = await api.vehicles();
      const all = await Promise.all(vehicles.map((v) => api.run(String(v.id)).catch(() => null)));
      const next: Record<string, DriverRun> = {};
      for (const r of all) if (r) next[String(r.vehicle.id)] = r;
      const t = Date.now();
      const fresh = Object.values(next).flatMap((r) => diff(prev.current[String(r.vehicle.id)], r, t));
      if (fresh.length) {
        setNotes((n) => [...fresh.map((x) => ({ ...x, id: `n${++seq.current}` })).reverse(), ...n].slice(0, 60));
        setFlash((f) => ({
          ...f,
          ...Object.fromEntries(fresh.filter((x) => x.kind === "offer").map((x) => [x.vehicleId, t])),
        }));
      }
      prev.current = next;
      setRuns(next);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  // Refresh on any live change (debounced), and every 5 s as a backstop.
  useEffect(() => {
    const t = setTimeout(refresh, 300);
    return () => clearTimeout(t);
  }, [refresh, assignments, requests, vehicleCount]);
  useEffect(() => {
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const act = useCallback(
    (fn: () => Promise<unknown>) => {
      fn()
        .catch((e) => setError((e as Error).message))
        .finally(() => void refresh());
    },
    [refresh],
  );

  const list = useMemo(
    () =>
      Object.values(runs).sort((a, b) => {
        const score = (r: DriverRun) => (r.offers.length ? 0 : r.run.length ? 1 : 2);
        return score(a) - score(b) || String(a.vehicle.driverName).localeCompare(String(b.vehicle.driverName));
      }),
    [runs],
  );
  const totals = useMemo(() => {
    const t = { seats: 0, left: 0, offers: 0, riders: 0 };
    for (const r of list) {
      t.seats += r.seats?.capacity ?? 0;
      t.left += r.seats?.left ?? 0;
      t.offers += r.offers.length;
      t.riders += r.run.length;
    }
    return t;
  }, [list]);
  const toasts = notes.filter((n) => now - n.at < 6000).slice(0, 4);

  return (
    <main className="flex min-h-dvh flex-col">
      <AppHeader />
      <div className="mx-auto flex w-full max-w-[1500px] flex-1 flex-col gap-5 px-5 py-6 lg:flex-row">
        <section className="min-w-0 flex-1">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <span className="eyebrow">Fleet · every driver&apos;s screen</span>
              <h1 className="display mt-1 text-[2rem]">All drivers</h1>
            </div>
            <dl className="flex gap-5 text-sm">
              {[
                ["drivers", list.length],
                ["offers waiting", totals.offers],
                ["riders assigned", totals.riders],
                ["seats left", `${totals.left}/${totals.seats}`],
              ].map(([k, v]) => (
                <div key={String(k)} className="flex flex-col items-end">
                  <dt className="text-[11px] text-muted uppercase tracking-[0.1em]">{k}</dt>
                  <dd className="font-mono text-lg font-semibold tabular-nums">{v}</dd>
                </div>
              ))}
            </dl>
          </div>
          {error && <p className="mb-3 rounded-xl bg-help/10 px-3 py-2 text-sm text-help">{error}</p>}
          {list.length === 0 ? (
            <p className="rounded-3xl border border-dashed border-line p-8 text-center text-muted">
              No vehicles yet. Seed the scenario, or press <b>Drive test</b> on the console.
            </p>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(18.5rem,1fr))] gap-3">
              {list.map((r) => (
                <DriverCard
                  key={String(r.vehicle.id)}
                  run={r}
                  now={now}
                  flash={now - (flash[String(r.vehicle.id)] ?? 0) < 4000}
                  onAct={act}
                />
              ))}
            </div>
          )}
        </section>

        <aside className="flex w-full flex-col gap-3 lg:w-[22rem]" aria-label="Notifications">
          <span className="eyebrow">Notifications</span>
          <ol className="scroll-soft flex max-h-[calc(100dvh-10rem)] flex-col gap-2 overflow-y-auto">
            {notes.length === 0 && (
              <li className="rounded-2xl border border-dashed border-line p-5 text-center text-sm text-muted">
                Waiting for the first offer. Every driver&apos;s notifications land here.
              </li>
            )}
            {notes.map((n) => (
              <li key={n.id} className="card animate-rise flex gap-3 rounded-2xl! p-3">
                <Avatar name={n.driver} size="h-8 w-8 text-[11px]" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{n.driver}</span>
                    <span className={`rounded-full px-2 py-px text-[10px] font-semibold ${NOTE_STYLE[n.kind].tone}`}>
                      {NOTE_STYLE[n.kind].label}
                    </span>
                    <span className="ml-auto font-mono text-[10px] text-muted tabular-nums">
                      {new Date(n.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </span>
                  </div>
                  <p className="mt-0.5 truncate text-sm text-muted">{n.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </div>

      {/* Toasts: like the push notification each driver's phone would show. */}
      <div
        className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 flex-col-reverse gap-2"
        aria-live="polite"
      >
        {toasts.map((n) => (
          <div
            key={n.id}
            className="glass animate-rise flex items-start gap-3 rounded-2xl! p-3 shadow-[var(--shadow-float)]"
          >
            <Avatar name={n.driver} size="h-8 w-8 text-[11px]" />
            <div className="min-w-0">
              <p className="text-sm font-semibold">
                {n.driver} · {NOTE_STYLE[n.kind].label}
              </p>
              <p className="truncate text-xs text-muted">{n.text}</p>
            </div>
          </div>
        ))}
      </div>
    </main>
  );
}
