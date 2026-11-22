"use client";

/**
 * Shared look for every screen: wordmark, the header with the pill nav, the live chip, animated numbers
 * and the progress ring. Styling only; no data fetching here (pages pass what they show).
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useLive } from "@/lib/live";

// ── brand ─────────────────────────────────────────────────────────────────────
export function Mark({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <path d="M7 24 L16 7 L25 24" fill="none" stroke="var(--color-accent)" strokeWidth="3.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="24" r="3" fill="var(--color-fire)" />
    </svg>
  );
}

export function Wordmark({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 rounded-full pr-1" aria-label="RideOut home">
      <Mark />
      <span className="text-[1.15rem] font-semibold tracking-[-0.03em] text-ink">
        RideOut<span className="text-accent">.</span>
      </span>
    </Link>
  );
}

// ── navigation ────────────────────────────────────────────────────────────────
const NAV = [
  { href: "/console", label: "Console" },
  { href: "/calls", label: "Calls" },
  { href: "/system", label: "System" },
  { href: "/driver", label: "Driver" },
  { href: "/driver/fleet", label: "Fleet" },
  { href: "/drill", label: "Drill" },
  { href: "/results", label: "Results" },
  { href: "/try", label: "Try it" },
];

export function NavPill({ className = "" }: { className?: string }) {
  const path = usePathname();
  // The most specific tab wins: /driver/fleet is Fleet, not Driver.
  const current = NAV.filter((n) => path === n.href || path.startsWith(`${n.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;
  return (
    <nav
      aria-label="Screens"
      className={`flex items-center gap-0.5 overflow-x-auto rounded-full border border-line bg-panel-2/70 p-1 shadow-[inset_0_1px_2px_rgb(16_24_40/0.04)] ${className}`}
    >
      {NAV.map((n) => {
        const active = n.href === current;
        return (
          <Link
            key={n.href}
            href={n.href}
            aria-current={active ? "page" : undefined}
            className={`whitespace-nowrap rounded-full px-3.5 py-1.5 text-[13px] transition-colors ${
              active ? "bg-panel font-medium text-ink shadow-[0_1px_3px_rgb(16_24_40/0.12)]" : "text-muted hover:text-ink"
            }`}
          >
            {n.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function LiveChip() {
  const connected = useLive((s) => s.connected);
  return (
    <span className="chip" title={connected ? "Connected to live updates" : "Reconnecting to live updates"}>
      <span className="relative flex h-1.5 w-1.5">
        {connected && <span className="absolute inset-0 animate-ping-slow rounded-full bg-out" />}
        <span className={`relative h-1.5 w-1.5 rounded-full ${connected ? "bg-out" : "bg-unknown"}`} />
      </span>
      {connected ? "Live data" : "Reconnecting"}
    </span>
  );
}

/** The header on every screen. `floating` = a glass bar over the map (console). */
export function AppHeader({ floating = false, right }: { floating?: boolean; right?: React.ReactNode }) {
  return (
    <header
      className={
        floating
          ? "glass grid grid-cols-[auto_1fr_auto] items-center gap-3 px-3 py-2"
          : "sticky top-0 z-30 border-b border-line bg-bg/80 backdrop-blur-xl"
      }
    >
      {floating ? (
        <>
          <div className="pl-1">
            <Wordmark />
          </div>
          <NavPill className="justify-self-center" />
          <div className="flex items-center gap-2">
            {right}
            <LiveChip />
            <ThemeToggle />
          </div>
        </>
      ) : (
        <div className="mx-auto grid max-w-7xl grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-3 sm:px-6">
          <Wordmark />
          <NavPill className="hidden justify-self-center md:flex" />
          <div className="flex items-center gap-2">
            {right}
            <LiveChip />
            <ThemeToggle />
          </div>
          <NavPill className="col-span-3 md:hidden" />
        </div>
      )}
    </header>
  );
}

// ── numbers ───────────────────────────────────────────────────────────────────
/** Counts smoothly from the last value to the new one (instant with reduced motion). */
export function useAnimatedNumber(value: number, ms = 700): number {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const start = from.current;
    if (start === value) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      from.current = value;
      setShown(value);
      return;
    }
    const t0 = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      const eased = 1 - Math.pow(1 - k, 3);
      const v = start + (value - start) * eased;
      setShown(v);
      from.current = v;
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return shown;
}

export function AnimatedNumber({ value, decimals = 0 }: { value: number; decimals?: number }) {
  const v = useAnimatedNumber(value);
  return <>{v.toFixed(decimals)}</>;
}

/** A progress ring like an instrument dial. `value` and `max` in the same unit. */
export function Ring({
  value,
  max,
  size = 132,
  stroke = 10,
  tone = "var(--color-accent)",
  track = "rgb(255 255 255 / 0.12)",
  children,
}: {
  value: number;
  max: number;
  size?: number;
  stroke?: number;
  tone?: string;
  track?: string;
  children?: React.ReactNode;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const shown = useAnimatedNumber(max > 0 ? Math.min(1, value / max) : 0, 900);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={track} strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={tone}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - shown)}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}

/** Small round icon button used in toasts and cards. */
export function CloseButton({ onClick, label = "Dismiss" }: { onClick: () => void; label?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:bg-ink/5 hover:text-ink"
    >
      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
        <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
      </svg>
    </button>
  );
}

export function Arrow({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
