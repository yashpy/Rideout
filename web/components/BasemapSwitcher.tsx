"use client";

import { useEffect, useRef, useState } from "react";
import { BASEMAPS, type Basemap } from "@/lib/basemaps";

/**
 * "View" dropdown for the map style (Map · Terrain · Topo · Satellite), top-right of the console map and
 * the house picker. One small button that opens a menu; Escape or a click outside closes it.
 */
export function BasemapSwitcher({
  value,
  onChange,
  className = "",
}: {
  value: Basemap;
  onChange: (b: Basemap) => void;
  className?: string;
  vertical?: boolean; // kept for callers; the dropdown has one layout
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const current = BASEMAPS.find((b) => b.id === value) ?? BASEMAPS[0];

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div ref={box} className={`z-20 ${/\babsolute\b/.test(className) ? "" : "relative"} ${className}`}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Map view: ${current.label}`}
        onClick={() => setOpen((v) => !v)}
        className="glass flex min-h-9 items-center gap-2 rounded-full! py-1.5 pr-3 pl-3.5 text-[12px] font-medium text-ink"
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4 text-muted" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
          <path d="M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5" strokeLinejoin="round" />
        </svg>
        <span className="text-muted">View</span>
        {current.label}
        <svg viewBox="0 0 24 24" className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div role="menu" aria-label="Map view" className="glass absolute right-0 mt-1.5 flex w-40 flex-col p-1">
          {BASEMAPS.map((b) => {
            const on = b.id === value;
            return (
              <button
                key={b.id}
                type="button"
                role="menuitemradio"
                aria-checked={on}
                onClick={() => {
                  onChange(b.id);
                  setOpen(false);
                }}
                className={`flex items-center justify-between rounded-xl px-3 py-2 text-left text-[13px] transition-colors ${
                  on ? "bg-accent/12 font-medium text-accent" : "text-ink hover:bg-ink/5"
                }`}
              >
                {b.label}
                {on && (
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
                    <path d="M5 12.5l4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
