"use client";

/**
 * Landing hero: the live simulation full-bleed behind the headline, a readable gradient on the left, two
 * clear actions (one primary), the QR card, and a strip of numbers counted from the same simulation.
 */
import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useState } from "react";
import { Arrow } from "@/components/ui";
import type { HeroStats } from "../HeroMap";
import { ShareQR } from "./ShareQR";

const HeroMap = dynamic(() => import("../HeroMap"), { ssr: false });

function clock(m: number): string {
  const x = Math.max(0, Math.round(m));
  return `T+${Math.floor(x / 60)}h ${String(x % 60).padStart(2, "0")}m`;
}

/** Shown under the map while it loads, and instead of it if there's no world to play. */
function Backdrop() {
  return (
    <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <defs>
        <radialGradient id="glow" cx="78%" cy="38%" r="45%">
          <stop offset="0" stopColor="#ff6a2b" stopOpacity="0.55" />
          <stop offset="0.45" stopColor="#b91c1c" stopOpacity="0.18" />
          <stop offset="1" stopColor="#060a14" stopOpacity="0" />
        </radialGradient>
        <pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse">
          <path d="M48 0H0V48" fill="none" stroke="#5b7bd6" strokeOpacity="0.08" />
        </pattern>
      </defs>
      <rect width="1600" height="900" fill="#060a14" />
      <rect width="1600" height="900" fill="url(#grid)" />
      <rect width="1600" height="900" fill="url(#glow)" />
      <path d="M0 640 L180 560 L320 610 L470 500 L640 590 L820 470 L1000 560 L1180 420 L1360 520 L1600 430 L1600 900 L0 900Z" fill="#0b1224" />
      <path d="M1040 520 Q1180 380 1320 470 T1600 400" fill="none" stroke="#ff8a3d" strokeWidth="3" strokeOpacity="0.8" />
      <g stroke="#34d399" strokeOpacity="0.55" strokeWidth="2" strokeLinecap="round">
        <path d="M900 700 H620 V760 H380" />
        <path d="M980 640 H760 V700 H520" />
        <path d="M1060 760 H820 V820 H560" />
      </g>
    </svg>
  );
}

export function Hero() {
  const [stats, setStats] = useState<HeroStats | null>(null);
  const onStats = useCallback((s: HeroStats) => setStats(s), []);
  const sm = stats?.summary;

  return (
    <section className="relative isolate min-h-[92svh] overflow-hidden bg-[#060a14] text-white" aria-labelledby="hero-title">
      <Backdrop />
      <HeroMap onStats={onStats} />
      {/* Readability: dark on the left where the words are, the map shows through on the right. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-[1] bg-[linear-gradient(90deg,#060a14_0%,rgba(6,10,20,0.92)_34%,rgba(6,10,20,0.35)_62%,rgba(6,10,20,0.1)_100%)]"
      />
      <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-40 bg-gradient-to-t from-[#060a14] to-transparent" />

      <div className="relative z-[2] mx-auto flex min-h-[92svh] max-w-7xl flex-col justify-center px-5 pt-28 pb-16 sm:px-8">
        <div className="max-w-2xl">
          <span className="eyebrow text-white/70" style={{ "--eyebrow-dot": "#ff6a2b" } as React.CSSProperties}>
            Wildfire evacuation · for people who can&apos;t drive out
          </span>
          <h1 id="hero-title" className="display mt-5 text-[2.75rem] sm:text-[4.25rem]">
            Everyone gets
            <br />
            <span className="bg-gradient-to-r from-[#ffb36b] via-[#ff6a2b] to-[#f43f5e] bg-clip-text text-transparent">
              a safe seat out.
            </span>
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-white/75">
            When the warning comes, RideOut calls every home in the zone at once, finds who can&apos;t leave on their
            own (wheelchair users, people in bed, people without a car), and sends responders and neighbors with a seat
            to them first, before the fire gets there.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href="/talk" className="btn btn-primary btn-lg">
              Talk to RideOut <Arrow />
            </Link>
            <Link href="/console" className="btn btn-lg border-white/20! bg-white/5! text-white! hover:bg-white/10!">
              Open the dispatch console
            </Link>
          </div>
          <p className="mt-4 text-xs text-white/50">
            The map behind this text is our live simulation: North Scottsdale, 6,000 simulated homes. Not an official
            emergency service.
          </p>
        </div>

        <div className="mt-12 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:max-w-3xl">
            <Stat
              label="riders out before the fire"
              value={sm ? `${sm.ridersOutBeforeFire} / ${sm.riders}` : "98%"}
              tone="text-[#34d399]"
            />
            <Stat
              label="wheelchair & stretcher riders out"
              value={sm ? `${sm.mobilityOutBeforeFire ?? "–"} / ${sm.mobilityRiders ?? "–"}` : "99%"}
              tone="text-[#34d399]"
            />
            <Stat label="homes called at once" value={sm ? (sm.homes ?? 0).toLocaleString() : "6,000"} />
            <Stat label="vehicles, none over its seats" value={sm ? String(sm.vehicles) : "132"} />
          </dl>
          <ShareQR className="w-full max-w-sm border-white/10! bg-white/[0.06]! [&_.text-ink]:text-white [&_.text-muted]:text-white/60" />
        </div>

        {stats && (
          <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-xs text-white/60" aria-live="off">
            <span className="text-white/80">{clock(stats.minute)}</span>
            <span>
              <b className="text-[#34d399]">{stats.safe.toLocaleString()}</b> out safely
            </span>
            <span>
              <b className="text-white">{stats.inVehicle}</b> in a vehicle
            </span>
            <span>
              <b className="text-[#f43f5e]">{stats.waiting}</b> waiting for a ride
            </span>
            <span className="text-white/40">simulated</span>
          </div>
        )}
      </div>
    </section>
  );
}

function Stat({ label, value, tone = "text-white" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.05] px-4 py-3 backdrop-blur">
      <dd className={`font-mono text-2xl font-semibold tabular-nums ${tone}`}>{value}</dd>
      <dt className="mt-0.5 text-[11px] leading-tight text-white/60">{label}</dt>
    </div>
  );
}
