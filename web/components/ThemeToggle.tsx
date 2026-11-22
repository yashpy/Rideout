"use client";

import { type ThemeMode, useTheme } from "@/lib/theme";

const ICON: Record<ThemeMode, React.ReactNode> = {
  system: (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" strokeLinecap="round" />
    </svg>
  ),
  light: (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <circle cx="12" cy="12" r="4" />
      <path
        d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
        strokeLinecap="round"
      />
    </svg>
  ),
  dark: (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" strokeLinejoin="round" />
    </svg>
  ),
};

const OPTIONS: { mode: ThemeMode; label: string }[] = [
  { mode: "system", label: "System" },
  { mode: "light", label: "Light" },
  { mode: "dark", label: "Dark" },
];

/**
 * System / Light / Dark. System is the default; the choice is remembered on this device.
 * labels: "never" (icons only), "wide" (labels from the sm breakpoint up), "always".
 */
export function ThemeToggle({ labels = "never" }: { labels?: "never" | "wide" | "always" }) {
  const { mode, setMode } = useTheme();
  const labelClass = labels === "always" ? "" : labels === "wide" ? "hidden sm:inline" : "sr-only";
  return (
    <div role="radiogroup" aria-label="Theme" className="flex rounded-full border border-line bg-panel p-0.5 text-xs shadow-[0_1px_2px_rgb(16_24_40/0.05)]">
      {OPTIONS.map((o) => (
        <button
          key={o.mode}
          type="button"
          role="radio"
          aria-checked={mode === o.mode}
          title={`${o.label} theme`}
          onClick={() => setMode(o.mode)}
          className={`flex h-7 min-w-7 items-center justify-center gap-1.5 rounded-full px-2 transition-colors ${
            mode === o.mode ? "bg-panel-2 text-accent ring-1 ring-line" : "text-muted hover:text-ink"
          }`}
        >
          {ICON[o.mode]}
          <span className={labelClass}>{o.label}</span>
        </button>
      ))}
    </div>
  );
}
