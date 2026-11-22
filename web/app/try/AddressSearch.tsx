"use client";

/**
 * Type your real address → suggestions inside the warning zone (OpenStreetMap data via Photon, searched
 * from your browser; nothing is stored until you ask for a call). Picking one returns the address and
 * its coordinates; the page then uses the nearest home on the map as yours and moves it there.
 */
import { useEffect, useId, useRef, useState } from "react";
import type { Place } from "@/lib/api";

type Hit = Place & { key: string };
const PHOTON = process.env.NEXT_PUBLIC_GEOCODER || "https://photon.komoot.io/api/";

function label(p: Record<string, string | undefined>): string {
  const street = [p.housenumber, p.street ?? p.name].filter(Boolean).join(" ");
  return [street || p.name, p.city ?? p.town ?? p.district, p.state, p.postcode].filter(Boolean).join(", ");
}

export function AddressSearch({
  bounds,
  value,
  onPick,
  disabled,
}: {
  bounds: [[number, number], [number, number]] | null;
  value: Place | null;
  onPick: (p: Place | null) => void;
  disabled?: boolean;
}) {
  const [q, setQ] = useState(value?.address ?? "");
  const [hits, setHits] = useState<Hit[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [state, setState] = useState<"idle" | "loading" | "none" | "offline">("idle");
  const listId = useId();
  const seq = useRef(0);

  useEffect(() => {
    if (value && q === value.address) return;
    const text = q.trim();
    if (text.length < 4 || !bounds) {
      setHits([]);
      setState("idle");
      return;
    }
    const n = ++seq.current;
    const t = setTimeout(async () => {
      setState("loading");
      const [[w, s], [e, nn]] = bounds;
      const url = `${PHOTON}?q=${encodeURIComponent(text)}&limit=6&lang=en&bbox=${w},${s},${e},${nn}`;
      try {
        const r = await fetch(url);
        const j = (await r.json()) as {
          features: { geometry: { coordinates: [number, number] }; properties: Record<string, string> }[];
        };
        if (n !== seq.current) return;
        const out = j.features
          .map((f, i) => ({
            key: `${i}-${f.geometry.coordinates.join(",")}`,
            address: label(f.properties),
            lon: f.geometry.coordinates[0],
            lat: f.geometry.coordinates[1],
          }))
          .filter((h) => h.lon >= w && h.lon <= e && h.lat >= s && h.lat <= nn);
        setHits(out);
        setActive(0);
        setOpen(true);
        setState(out.length ? "idle" : "none");
      } catch {
        if (n === seq.current) setState("offline");
      }
    }, 350);
    return () => clearTimeout(t);
  }, [q, bounds, value]);

  function pick(h: Hit) {
    setQ(h.address);
    setOpen(false);
    onPick({ address: h.address, lon: h.lon, lat: h.lat });
  }

  return (
    <div className="relative">
      <label className="flex flex-col gap-1.5 text-[11px] font-medium uppercase tracking-[0.12em] text-muted">
        Your address (optional)
        <span className="flex min-h-12 items-center gap-2 rounded-2xl border border-line bg-panel-2 px-4 focus-within:border-accent focus-within:ring-4 focus-within:ring-accent/15">
          <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" strokeLinejoin="round" />
            <circle cx="12" cy="9.5" r="2.5" />
          </svg>
          <input
            role="combobox"
            aria-expanded={open && hits.length > 0}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={open && hits[active] ? `${listId}-${active}` : undefined}
            autoComplete="street-address"
            disabled={disabled}
            placeholder="e.g. 9500 E Via Linda, Scottsdale"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              if (value) onPick(null);
            }}
            onFocus={() => hits.length && setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onKeyDown={(e) => {
              if (!open || !hits.length) return;
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => (a + 1) % hits.length);
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => (a - 1 + hits.length) % hits.length);
              } else if (e.key === "Enter") {
                e.preventDefault();
                pick(hits[active]);
              } else if (e.key === "Escape") setOpen(false);
            }}
            className="min-w-0 flex-1 bg-transparent text-base font-normal normal-case tracking-normal text-ink outline-none placeholder:text-muted/60"
          />
          {state === "loading" && (
            <span className="h-3.5 w-3.5 shrink-0 animate-spin rounded-full border-2 border-muted/30 border-t-accent" />
          )}
        </span>
      </label>
      {open && hits.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="card absolute inset-x-0 top-full z-20 mt-1 overflow-hidden rounded-2xl! py-1 shadow-[var(--shadow-float)]"
        >
          {hits.map((h, i) => (
            <li
              key={h.key}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(h);
              }}
              onMouseEnter={() => setActive(i)}
              className={`cursor-pointer px-4 py-2.5 text-sm ${i === active ? "bg-accent/10 text-ink" : "text-muted"}`}
            >
              {h.address}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-1.5 text-xs text-muted" aria-live="polite">
        {state === "none"
          ? "No match inside the warning zone. Try a street in the area, or tap a house on the map."
          : state === "offline"
            ? "Address lookup isn't reachable right now. Tap a house on the map instead."
            : value
              ? "Got it: your home is placed at this address on the map."
              : "Inside the shaded zone only. Or skip this and tap a house on the map."}
      </p>
    </div>
  );
}
