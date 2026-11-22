"use client";

/**
 * Results: the numbers, in one place, each with what it measures.
 * - The loaded world's whole night (GET /sim/evacuation): riders out before the fire, wheelchair and stretcher
 *   riders, households leaving on their own, seats never exceeded; and over time, pickups against the fire
 *   reaching those same homes (the evacuation stays ahead of the fire).
 * - Today vs RideOut: the impact simulation (data/sim-results.json, 150 runs, Oak Creek Canyon).
 * Everything here is simulated and says so.
 */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { SimBadge } from "@/components/Shell";
import { AppHeader, Arrow } from "@/components/ui";
import { api, type Evacuation } from "@/lib/api";

// data/sim-results.json (generated 2026-11-15, gitSha a4de1ed): median and range across low/middle/high settings.
const IMPACT = {
  label: "Oak Creek Canyon, 200 homes, 150 simulated runs",
  metric: "Share of people who needed a ride picked up before their deadline (10 min before the fire reaches the home)",
  bars: [
    { label: "Today (911 queue)", median: 47.6, min: 36.6, max: 52.7, tone: "bg-help" },
    { label: "RideOut", median: 90.9, min: 86.2, max: 95.9, tone: "bg-out" },
  ],
};

function pct(a: number, b: number): string {
  return b ? `${((a / b) * 100).toFixed(1)}%` : "–";
}

export default function Results() {
  const [data, setData] = useState<Evacuation | null>(null);
  const [world, setWorld] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .scenario()
      .then((s) => setWorld(s.name === "scottsdale-fire" ? "North Scottsdale" : "Oak Creek Canyon"))
      .catch(() => undefined);
    api
      .evacuation()
      .then((d) => (d.error ? setError(d.error) : setData(d)))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Over time: riders picked up vs rider homes the fire has reached (both cumulative, same households).
  const series = useMemo(() => {
    if (!data) return null;
    const end = data.endMin;
    const step = Math.max(1, Math.round(end / 120));
    const pts: { m: number; picked: number; fire: number; safe: number }[] = [];
    const selfArrive = data.selfEvac.map((s) => s[3][s[3].length - 1]);
    for (let m = 0; m <= end; m += step) {
      let picked = 0,
        fire = 0;
      for (const r of data.riders) {
        if (r[2] != null && r[2] <= m) picked++;
        if (r[5] != null && r[5] <= m) fire++;
      }
      const safe = selfArrive.filter((t) => t <= m).length + data.riders.filter((r) => r[3] != null && r[3] <= m).length;
      pts.push({ m, picked, fire, safe });
    }
    return pts;
  }, [data]);

  const s = data?.summary;
  const n = (k: string) => Number(s?.[k] ?? 0);
  return (
    <main className="min-h-dvh bg-bg">
      <AppHeader />
      <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8">
        <span className="eyebrow">Results</span>
        <h1 className="display mt-3 text-[2.4rem] text-ink">What the numbers say</h1>
        <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-muted">
          Every number on this page is counted from the simulation, not typed in. The fire, homes and people are
          simulated <SimBadge />. Live calls in Try it are real.
        </p>

        <section className="mt-10" aria-labelledby="night">
          <h2 id="night" className="text-lg font-semibold text-ink">
            One night, {world || "the loaded world"}
          </h2>
          {error && <p className="mt-3 text-sm text-fire">{error} Run the census in the console first.</p>}
          {!data && !error && <p className="mt-3 text-sm text-muted">Planning the whole night…</p>}
          {s && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi
                big={`${n("ridersOutBeforeFire")} / ${n("riders")}`}
                sub={`${pct(n("ridersOutBeforeFire"), n("riders"))} of households that needed a ride were picked up before the fire reached their home`}
                tone="text-out"
              />
              <Kpi
                big={`${n("mobilityOutBeforeFire")} / ${n("mobilityRiders")}`}
                sub={`${pct(n("mobilityOutBeforeFire"), n("mobilityRiders"))} of wheelchair and stretcher riders, the people this is built for`}
                tone="text-out"
              />
              <Kpi
                big={`${n("selfEvac") - n("selfEvacLate")} / ${n("selfEvac")}`}
                sub="households that could leave on their own reached a shelter before the fire"
              />
              <Kpi
                big={`${n("homes").toLocaleString()} · ${n("vehicles")}`}
                sub="homes called at once · vehicles; no vehicle ever over its seats or inside the fire"
              />
            </div>
          )}
          {series && data && (
            <figure className="card mt-4 p-5">
              <figcaption className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-semibold text-ink">The evacuation stays ahead of the fire</span>
                <span className="text-xs text-muted">households needing a ride · minutes after the warning</span>
              </figcaption>
              <Chart pts={series} total={data.riders.length} end={data.endMin} />
              <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
                <Key c="bg-out" t="picked up by a vehicle" />
                <Key c="bg-fire" t="fire has reached their home" />
              </div>
              <p className="mt-3 text-xs leading-relaxed text-muted">
                Same households, same clock. The green line is how many have been picked up; the red line is how many
                homes the fire has reached. Green above red means people are leaving before the fire arrives.
              </p>
            </figure>
          )}
        </section>

        <section className="mt-12" aria-labelledby="impact">
          <h2 id="impact" className="text-lg font-semibold text-ink">
            Today vs RideOut
          </h2>
          <p className="mt-1 text-sm text-muted">
            {IMPACT.metric}. {IMPACT.label}; median with the range across low, middle and high settings.
          </p>
          <div className="card mt-4 grid gap-5 p-6">
            {IMPACT.bars.map((b) => (
              <div key={b.label}>
                <div className="flex items-baseline justify-between text-sm">
                  <span className="font-medium text-ink">{b.label}</span>
                  <span className="font-mono text-2xl font-semibold tabular-nums text-ink">{b.median}%</span>
                </div>
                <div className="relative mt-2 h-4 rounded-full bg-panel-2">
                  <span className={`absolute inset-y-0 left-0 rounded-full ${b.tone}`} style={{ width: `${b.median}%` }} />
                  <span
                    className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-ink/40"
                    style={{ left: `${b.min}%`, width: `${b.max - b.min}%` }}
                    title={`range ${b.min}–${b.max}%`}
                  />
                </div>
                <p className="mt-1 text-xs text-muted">
                  range {b.min}–{b.max}%
                </p>
              </div>
            ))}
            <p className="text-xs leading-relaxed text-muted">
              Today: residents call 911 and wait in a first-come queue for the nearest unit. RideOut: every home is called
              at once and the fleet, including neighbors with a seat, is planned together. Not lives saved; not a
              forecast.
            </p>
          </div>
        </section>

        <section className="mt-12 grid gap-3 sm:grid-cols-3" aria-label="See it">
          {[
            ["/console", "Watch the night", "Console → Play evacuation"],
            ["/try", "Take a real call", "Try it with your own phone"],
            ["/system", "Under the hood", "Latency, honesty checks, dispatch"],
          ].map(([href, t, d]) => (
            <Link key={href} href={href} className="card group flex items-center justify-between p-5 hover:border-accent/50">
              <span>
                <span className="block font-semibold text-ink">{t}</span>
                <span className="block text-sm text-muted">{d}</span>
              </span>
              <Arrow />
            </Link>
          ))}
        </section>
      </div>
    </main>
  );
}

function Kpi({ big, sub, tone = "text-ink" }: { big: string; sub: string; tone?: string }) {
  return (
    <div className="card p-5">
      <div className={`font-mono text-3xl font-semibold tabular-nums ${tone}`}>{big}</div>
      <p className="mt-2 text-sm leading-snug text-muted">{sub}</p>
    </div>
  );
}

function Key({ c, t }: { c: string; t: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-4 rounded-full ${c}`} />
      {t}
    </span>
  );
}

function Chart({ pts, total, end }: { pts: { m: number; picked: number; fire: number }[]; total: number; end: number }) {
  const W = 960,
    H = 280,
    L = 48,
    R = 12,
    T = 12,
    B = 30;
  const x = (m: number) => L + (m / end) * (W - L - R);
  const y = (v: number) => T + (1 - v / Math.max(1, total)) * (H - T - B);
  const line = (k: "picked" | "fire") => pts.map((p, i) => `${i ? "L" : "M"}${x(p.m).toFixed(1)},${y(p[k]).toFixed(1)}`).join("");
  const ticks = Array.from({ length: Math.floor(end / 60) + 1 }, (_, i) => i * 60);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 h-auto w-full" role="img" aria-label="Riders picked up and homes reached by the fire over time">
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line x1={L} x2={W - R} y1={y(total * f)} y2={y(total * f)} stroke="var(--color-line)" />
          <text x={L - 8} y={y(total * f) + 4} textAnchor="end" fontSize={11} fill="var(--color-muted)">
            {Math.round(total * f)}
          </text>
        </g>
      ))}
      {ticks.map((m) => (
        <text key={m} x={x(m)} y={H - 8} textAnchor="middle" fontSize={11} fill="var(--color-muted)">
          {m / 60}h
        </text>
      ))}
      <path d={line("fire")} fill="none" stroke="var(--color-fire)" strokeWidth={2.5} />
      <path d={line("picked")} fill="none" stroke="var(--color-out)" strokeWidth={3} />
    </svg>
  );
}
