"use client";

/**
 * Try it: 1) enter your phone number, 2) type your address (or tap a house), 3) choose who you are there:
 *   - "I need help getting out": RideOut calls you as that resident (the real agent; the transcript and
 *     record fill in here as you talk);
 *   - "I can drive": a volunteer car is parked at that house and you get pickups on the driver screen.
 * The map is the lightweight house picker (HomeMap: an SVG map of the canyon), not the console map.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SimBadge } from "@/components/Shell";
import { AppHeader, Arrow } from "@/components/ui";
import { ApiError, SCENARIOS, api, type HouseholdRecord, type Place, type Scenario } from "@/lib/api";
import { useLive } from "@/lib/live";
import { recordRows } from "../calls/format";
import { HomeMap, type Home } from "../HomeMap";
import { AddressSearch } from "./AddressSearch";

type Turn = { callId: string; speaker: "agent" | "resident"; text: string; at?: string };

function Step({ n, done, active, children }: { n: number; done: boolean; active: boolean; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-3">
      <span
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold transition-colors ${
          done
            ? "bg-out text-white"
            : active
              ? "bg-accent text-white shadow-[0_0_0_4px_color-mix(in_srgb,var(--color-accent)_18%,transparent)]"
              : "border border-line text-muted"
        }`}
      >
        {done ? (
          <svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            aria-hidden
          >
            <path d="M5 12.5l4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          n
        )}
      </span>
      <span className={`text-sm ${active ? "font-medium text-ink" : "text-muted"}`}>{children}</span>
    </li>
  );
}

export default function Kiosk() {
  const connect = useLive((s) => s.connect);
  useEffect(() => connect(), [connect]);
  const households = useLive((s) => s.households);
  const liveTurns = useLive((s) => s.turns);
  const liveZones = useLive((s) => s.zones);
  const [selected, setSelected] = useState<string | null>(null);
  // The visitor's own address (optional): the nearest home on the map becomes theirs and moves there.
  const [myPlace, setMyPlace] = useState<Place | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [world, setWorld] = useState<Scenario | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [bounds, setBounds] = useState<[[number, number], [number, number]] | null>(null);
  const loadWorld = useCallback(async () => {
    try {
      const s = await api.scenario();
      setWorld(s.name as Scenario);
      setBounds(s.bounds);
      return s.name as Scenario;
    } catch {
      return null;
    }
  }, []);
  // Build a world (homes, fleet, fire, census answers) and redraw. Used when the visitor picks another world,
  // and when the loaded one has no homes yet, so the map is never empty.
  const seedWorld = useCallback(
    async (scenario: Scenario) => {
      setSeeding(true);
      setSelected(null);
      setMyPlace(null);
      try {
        await api.seed({ scenario, census: "instant" });
        await loadWorld();
        await useLive.getState().resync();
      } catch {
        setError("Couldn't build the world. Try again in a moment.");
      } finally {
        setSeeding(false);
      }
    },
    [loadWorld],
  );
  useEffect(() => {
    let off = false;
    (async () => {
      const name = await loadWorld();
      if (off || !name) return;
      const homesNow = await api.households().catch(() => null);
      if (!off && homesNow && homesNow.length === 0) await seedWorld(name);
    })();
    return () => {
      off = true;
    };
  }, [loadWorld, seedWorld]);

  // Map context: zone outlines, shelters, closures (same source as the console). Live zone status wins.
  type Doc = { id: string } & Record<string, unknown>;
  const [statics, setStatics] = useState<{ zones: Doc[]; shelters: Doc[]; closures: Doc[] }>({
    zones: [],
    shelters: [],
    closures: [],
  });
  useEffect(() => {
    api
      .hazards()
      .then((h) => setStatics({ zones: h.zones ?? [], shelters: h.shelters ?? [], closures: h.closures }))
      .catch(() => undefined);
  }, []);
  const zones = useMemo(
    () => statics.zones.map((z) => (liveZones[z.id] ? { ...z, status: liveZones[z.id].status } : z)),
    [statics.zones, liveZones],
  );

  const homes = useMemo(() => Object.values(households) as unknown as Home[], [households]);
  const liveRequests = useLive((s) => s.requests);
  // Picked up (on board) or already dropped at a shelter: drawn grey and faint.
  const pickedUp = useMemo(() => {
    const out = new Set<string>();
    for (const r of Object.values(liveRequests)) if (r.status === "arrived") out.add(String(r.householdId));
    for (const h of Object.values(households)) if ((h as Record<string, unknown>).safeAt) out.add(h.id);
    return out;
  }, [liveRequests, households]);
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [callId, setCallId] = useState<string | null>(null);
  const [driver, setDriver] = useState<{ vehicleId: string; driverUrl: string; driverName: string } | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const phoneRef = useRef<HTMLInputElement>(null);

  const home = selected ? (households[selected] as unknown as Home & { record?: Record<string, unknown> }) : null;
  const e164 = `+1${phone.replace(/\D/g, "").replace(/^1(?=\d{10}$)/, "")}`;
  const valid = /^\+1\d{10}$/.test(e164);
  const turns = useMemo(
    () => liveTurns.map((e) => e.data as unknown as Turn).filter((t) => t.callId === callId),
    [liveTurns, callId],
  );

  function pickAddress(p: Place | null) {
    setMyPlace(p);
    if (!p || callId || driver) return;
    let best: string | null = null;
    let bestD = Infinity;
    for (const h of homes) {
      const c = (h as unknown as { location?: { coordinates?: number[] } }).location?.coordinates;
      if (!c) continue;
      const d = (c[0] - p.lon) ** 2 + ((c[1] - p.lat) * 1.2) ** 2;
      if (d < bestD) {
        bestD = d;
        best = h.id;
      }
    }
    if (best) setSelected(best);
    if (!valid) setHint("Now enter your phone number, then choose who you are.");
  }

  function pickHouse(id: string) {
    setMyPlace(null); // tapping a house uses that house's (simulated) address
    if (callId || driver) return;
    if (!valid) {
      setHint("Enter your phone number first, then tap your house.");
      phoneRef.current?.focus();
      return;
    }
    setHint(null);
    setSelected(id);
  }

  async function drive() {
    if (!selected || !valid) return;
    setBusy(true);
    setError(null);
    try {
      setDriver(await api.volunteer(selected, e164, myPlace));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function callMe() {
    if (!selected || !valid) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.kiosk(selected, e164, myPlace);
      setCallId(res.callId);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Something went wrong";
      setError(e instanceof ApiError && e.status === 503 ? "The phone line isn't set up yet." : msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex h-dvh flex-col">
      <AppHeader />
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <section className="relative min-h-64 flex-1 bg-bg p-2">
          {/* Blueprint grid behind the house picker. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              backgroundImage:
                "linear-gradient(color-mix(in srgb, var(--color-accent) 7%, transparent) 1px, transparent 1px)," +
                "linear-gradient(90deg, color-mix(in srgb, var(--color-accent) 7%, transparent) 1px, transparent 1px)",
              backgroundSize: "48px 48px",
            }}
          />
          <HomeMap
            homes={homes}
            selected={selected}
            onSelect={pickHouse}
            pickedUp={pickedUp}
            selectedLabel={myPlace?.address ?? null}
            zones={zones}
            shelters={statics.shelters}
            closures={statics.closures}
          />
          <div className="absolute top-4 left-4 z-10 flex items-center gap-2">
            <label className="glass flex items-center gap-2 rounded-full! py-1 pr-1.5 pl-3 text-xs text-muted">
              <SimBadge />
              <span className="sr-only">World</span>
              <select
                value={world ?? ""}
                disabled={seeding || !!callId || !!driver}
                onChange={(e) => void seedWorld(e.target.value as Scenario)}
                className="rounded-full bg-transparent py-1 pr-1 text-xs font-medium text-ink outline-none"
                aria-label="Pick a world (rebuilds the simulated homes)"
              >
                {SCENARIOS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
              <span className="pr-1.5">{seeding ? "building the world…" : "other homes are simulated"}</span>
            </label>
          </div>
        </section>

        <aside className="scroll-soft flex w-full flex-col gap-6 overflow-y-auto border-t border-line bg-panel px-6 py-7 md:w-[26rem] md:border-t-0 md:border-l">
          {driver ? (
            <>
              <div className="overflow-hidden rounded-3xl bg-gradient-to-br from-night to-night-2 p-5 text-white shadow-[var(--shadow-float)]">
                <span
                  className="eyebrow text-white/60"
                  style={{ "--eyebrow-dot": "var(--color-out)" } as React.CSSProperties}
                >
                  You&apos;re a volunteer driver
                </span>
                <p className="mt-3 text-lg font-semibold tracking-[-0.02em]">{driver.driverName}</p>
                <p className="mt-1 text-sm text-white/70">3 seats · parked at {home?.address}</p>
                <Link href={driver.driverUrl} className="btn btn-primary btn-lg mt-4 w-full">
                  Open my driver screen <Arrow />
                </Link>
              </div>
              <ol className="flex flex-col gap-2 text-sm text-muted">
                <li>
                  • Open the driver screen on your phone:{" "}
                  {typeof window !== "undefined" ? `${window.location.host}${driver.driverUrl}` : driver.driverUrl}
                </li>
                <li>• When dispatch approves a pickup near you, it pops up there with a 2-minute countdown.</li>
                <li>• Accept fills your seats; when you&apos;re full, the next driver gets the rest.</li>
              </ol>
              <button
                type="button"
                onClick={() => {
                  setDriver(null);
                  setSelected(null);
                }}
                className="btn btn-lg w-full"
              >
                Done
              </button>
            </>
          ) : !callId ? (
            <>
              <div className="flex flex-col gap-3">
                <span className="eyebrow">Try it · real call, real agent</span>
                <h1 className="display text-[2.15rem]">
                  Be the resident.
                  <br />
                  <span className="text-muted">Hear what they hear.</span>
                </h1>
                <p className="text-[15px] leading-relaxed text-muted">
                  RideOut calls every home in the warning zone at once. Pick one and take the call yourself, or join as a
                  neighbor who can drive.
                </p>
              </div>

              <ol className="flex flex-col gap-3">
                <Step n={1} done={valid} active={!valid}>
                  Enter your phone number
                </Step>
                <Step n={2} done={!!selected} active={valid && !selected}>
                  Type your address, or tap a house on the map
                </Step>
                <Step n={3} done={false} active={valid && !!selected}>
                  Choose: you need help, or you can drive
                </Step>
              </ol>

              <div className="flex flex-col gap-3">
                <label className="flex flex-col gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
                  Your phone number (US)
                  <span className="flex min-h-12 items-center rounded-2xl border border-line bg-panel-2 px-4 focus-within:border-accent focus-within:ring-4 focus-within:ring-accent/15">
                    <span className="mr-2 font-mono text-sm normal-case tracking-normal text-muted">+1</span>
                    <input
                      ref={phoneRef}
                      inputMode="tel"
                      autoComplete="tel"
                      placeholder="(480) 555-1234"
                      value={phone}
                      onChange={(e) => {
                        setPhone(e.target.value);
                        setHint(null);
                      }}
                      className="min-w-0 flex-1 bg-transparent text-base font-normal normal-case tracking-normal text-ink outline-none placeholder:text-muted/60"
                    />
                  </span>
                </label>
                <AddressSearch bounds={bounds} value={myPlace} onPick={pickAddress} disabled={!!callId || !!driver} />
                <div
                  className={`rounded-2xl border px-4 py-3 transition-colors ${home ? "border-accent/40 bg-accent/[0.05]" : "border-dashed border-line"}`}
                >
                  <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted">Your house</p>
                  <p className={`mt-0.5 font-medium ${home ? "text-ink" : "text-muted"}`}>
                    {myPlace?.address ?? home?.address ?? (valid ? "Type your address or tap a house" : "Enter your number first")}
                  </p>
                </div>
                {hint && <p className="rounded-xl bg-accent/10 px-3 py-2 text-sm text-accent">{hint}</p>}

                <fieldset disabled={!selected || !valid || busy} className="grid gap-2.5 disabled:opacity-50">
                  <legend className="mb-2 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
                    Who are you here?
                  </legend>
                  <button
                    type="button"
                    onClick={callMe}
                    className="card flex items-start gap-3 rounded-2xl! p-4 text-left transition-colors hover:border-fire/50 disabled:pointer-events-none"
                  >
                    <span
                      className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-fire/10 text-fire"
                      aria-hidden
                    >
                      <svg
                        viewBox="0 0 24 24"
                        className="h-5 w-5"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" />
                      </svg>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block font-semibold">{busy ? "Calling…" : "I need help getting out"}</span>
                      <span className="block text-sm text-muted">
                        RideOut calls you now as the person who lives here.
                      </span>
                    </span>
                    <Arrow />
                  </button>
                  <button
                    type="button"
                    onClick={drive}
                    className="card flex items-start gap-3 rounded-2xl! p-4 text-left transition-colors hover:border-accent/50 disabled:pointer-events-none"
                  >
                    <span
                      className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent"
                      aria-hidden
                    >
                      <svg
                        viewBox="0 0 24 24"
                        className="h-5 w-5"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M5 17h14M6 17l1.5-5h9L18 17M7.5 12l1.2-3.5h6.6L16.5 12" />
                        <circle cx="8" cy="17.5" r="1.5" />
                        <circle cx="16" cy="17.5" r="1.5" />
                      </svg>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block font-semibold">I can drive and help</span>
                      <span className="block text-sm text-muted">
                        Your car is parked here. Get pickups for neighbors on the driver screen.
                      </span>
                    </span>
                    <Arrow />
                  </button>
                </fieldset>
                {error && <p className="rounded-xl bg-help/10 px-3 py-2 text-sm text-help">{error}</p>}
              </div>

              <div className="rounded-2xl bg-panel-2 p-4">
                <span className="eyebrow" style={{ "--eyebrow-dot": "var(--color-sim)" } as React.CSSProperties}>
                  Try playing Rosa, 81
                </span>
                <p className="mt-2 text-sm leading-relaxed text-muted">
                  Say it&apos;s just you, then &ldquo;no wait, my husband is here, he&apos;s in a power chair&rdquo;.
                  Then ask &ldquo;is someone coming?&rdquo; It won&apos;t promise a ride until a driver says yes.
                </p>
              </div>

              <p className="flex items-start gap-2 text-xs text-muted">
                <svg
                  viewBox="0 0 24 24"
                  className="mt-px h-3.5 w-3.5 shrink-0"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden
                >
                  <path d="M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6z" strokeLinejoin="round" />
                </svg>
                Your number and address are used for this demo call, its callbacks, and your volunteer car only.
              </p>
            </>
          ) : (
            <>
              <div className="overflow-hidden rounded-3xl bg-gradient-to-br from-night to-night-2 p-5 text-white shadow-[var(--shadow-float)]">
                <span
                  className="eyebrow text-white/60"
                  style={{ "--eyebrow-dot": "var(--color-out)" } as React.CSSProperties}
                >
                  On the call
                </span>
                <div className="mt-3 flex items-center gap-4">
                  <span className="relative flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-white/10">
                    <span className="absolute inset-0 animate-ping-slow rounded-full bg-white/15" />
                    <svg
                      viewBox="0 0 24 24"
                      className="h-5 w-5"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      aria-hidden
                    >
                      <path
                        d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm text-white/70">
                      {turns.length ? "You're talking to RideOut" : "Your phone should ring now"}
                    </p>
                    <p className="truncate text-lg font-semibold tracking-[-0.02em]">{home?.address}</p>
                  </div>
                </div>
              </div>

              <section className="flex flex-col gap-2">
                <span className="eyebrow">Transcript</span>
                <ol className="flex flex-col gap-2">
                  {turns.map((t, i) => (
                    <li
                      key={`${t.at}|${i}`}
                      className={`max-w-[88%] animate-rise rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
                        t.speaker === "agent"
                          ? "self-start rounded-tl-md bg-panel-2"
                          : "self-end rounded-tr-md bg-accent text-white"
                      }`}
                    >
                      {t.text}
                    </li>
                  ))}
                  {!turns.length && (
                    <li className="flex items-center gap-2 text-sm text-muted">
                      <span className="flex gap-1">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted" />
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:150ms]" />
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:300ms]" />
                      </span>
                      Waiting for you to pick up
                    </li>
                  )}
                </ol>
              </section>

              <section className="flex flex-col gap-2">
                <span className="eyebrow">What RideOut heard</span>
                <dl className="card flex flex-col px-4 py-2">
                  {recordRows(home?.record as HouseholdRecord | undefined).map((row) => (
                    <div
                      key={row.key}
                      className="flex justify-between gap-3 border-b border-line/70 py-2 text-sm last:border-0"
                    >
                      <dt className="text-muted">{row.label}</dt>
                      <dd
                        key={row.value ?? "—"}
                        className={`animate-flash rounded px-1 font-medium ${row.value ? "" : "text-muted/50"}`}
                      >
                        {row.value ?? "—"}
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>

              <button
                type="button"
                onClick={() => {
                  setCallId(null);
                  setSelected(null);
                }}
                className="btn btn-lg w-full"
              >
                Done
              </button>
            </>
          )}
        </aside>
      </div>
    </main>
  );
}
