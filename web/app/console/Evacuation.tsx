"use client";

/**
 * Play evacuation: the whole night on the console map, from the warning until the last rider is at a
 * shelter. Data: GET /sim/evacuation (planned with the live planner and travel model, simulated).
 *
 * - Fire: the burned area grows (same detections as the fire replay).
 * - Red dots: households waiting for a ride. At pickup the dot disappears into the vehicle.
 * - Vehicles drive their real runs with a trail (white = responders, orange = neighbors with a seat); the
 *   number next to a vehicle is the seats in use. They drop off at a shelter whenever the next rider
 *   wouldn't fit and end at a shelter outside the area.
 * - Green trails: households driving out on their own.
 * - Counters are counted from the same timelines, so they can't disagree with the map.
 */
import type { Layer } from "@deck.gl/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { create } from "zustand";
import { api, type Evacuation } from "@/lib/api";
import { SimBadge } from "@/components/Shell";
import { countsAt, evacLayers, prepare } from "@/lib/evac";



/** The map reads the evacuation layers from here, so a frame re-renders the map only, not the console. */
export const useEvacLayers = create<{ layers: Layer[] | null; set: (l: Layer[] | null) => void }>((set) => ({
  layers: null,
  set: (layers) => set({ layers }),
}));

const SPEEDS = [2, 5, 10]; // scenario minutes per real second
function hm(min: number): string {
  const m = Math.max(0, Math.round(min));
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function EvacuationPlayer({ onClose, className = "" }: { onClose: () => void; className?: string }) {
  const [data, setData] = useState<Evacuation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [minute, setMinute] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(SPEEDS[0]); // 2 min/s: the fire and the vehicles at a readable pace
  const setLayers = useEvacLayers((s) => s.set);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    let off = false;
    api
      .evacuation()
      .then((d) => {
        if (off) return;
        if (d.error) setError(d.error);
        else {
          setData(d);
          setPlaying(true);
        }
      })
      .catch((e: unknown) => !off && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      off = true;
      setLayers(null);
    };
  }, [setLayers]);

  const prep = useMemo(() => (data ? prepare(data) : null), [data]);

  // Clock: advance `speed` scenario minutes per real second while playing.
  useEffect(() => {
    if (!playing || !data) return;
    let last = performance.now();
    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setMinute((m) => {
        const next = Math.min(data.endMin, m + dt * speed);
        if (next >= data.endMin) setPlaying(false);
        return next;
      });
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [playing, speed, data]);

  // Counts at this minute, from the same timelines the map draws.
  const counts = useMemo(() => (data && prep ? countsAt(data, prep, minute) : null), [data, prep, minute]);

  // Layers for this minute.
  useEffect(() => {
    if (data && prep) setLayers(evacLayers(data, prep, minute));
  }, [data, prep, minute, setLayers]);

  const restart = useCallback(() => {
    setMinute(0);
    setPlaying(true);
  }, []);

  const s = data?.summary;
  const done = data && minute >= data.endMin;
  return (
    <section className={`glass rounded-3xl! p-4 ${className}`} aria-label="Evacuation replay">
      <div className="flex items-center gap-3">
        <span className="eyebrow">Evacuation, start to finish</span>
        <SimBadge />
        <span className="ml-auto font-mono text-sm tabular-nums">{data ? `T+${hm(minute)}` : ""}</span>
        <button className="btn min-h-8" onClick={onClose} aria-label="Close the evacuation replay">
          Close
        </button>
      </div>

      {error && <p className="mt-2 text-sm text-fire">{error}</p>}
      {!data && !error && <p className="mt-2 text-sm text-muted">Planning the whole night…</p>}

      {data && counts && (
        <>
          <div className="mt-3 grid grid-cols-5 gap-2 text-center">
            <Big label="safe at a shelter or out" value={counts.safe} of={counts.canLeave} tone="text-out" />
            <Big label="driving out on their own" value={counts.driving} tone="text-out" />
            <Big label="in a vehicle" value={counts.inVehicle} tone="text-vehicle" />
            <Big label="waiting for a ride" value={counts.waiting} tone="text-fire" />
            <Big label="fire reached before pickup" value={counts.lateRiders} tone={counts.lateRiders ? "text-fire" : "text-muted"} />
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button className="btn min-h-9" onClick={() => (done ? restart() : setPlaying((v) => !v))}>
              {done ? "Replay" : playing ? "Pause" : "Play"}
            </button>
            <input
              type="range"
              min={0}
              max={data.endMin}
              step={0.5}
              value={minute}
              onChange={(e) => {
                setPlaying(false);
                setMinute(Number(e.target.value));
              }}
              className="flex-1 accent-[var(--color-accent)]"
              aria-label="Minutes since the warning"
            />
            <div className="flex gap-1" role="radiogroup" aria-label="Speed">
              {SPEEDS.map((x) => (
                <button
                  key={x}
                  role="radio"
                  aria-checked={speed === x}
                  className={`btn min-h-8 px-2! text-xs ${speed === x ? "border-accent! text-accent" : ""}`}
                  onClick={() => setSpeed(x)}
                >
                  {x} min/s
                </button>
              ))}
            </div>
          </div>
          <p className="mt-2 text-xs text-muted">
            {s?.riders} households need a ride and {s?.selfEvac} leave on their own. Riders out before the fire:{" "}
            <b className="text-ink">
              {s?.ridersOutBeforeFire} of {s?.riders}
            </b>
            {s?.ridersNoVehicle ? ` · ${s.ridersNoVehicle} no vehicle can carry` : ""}. Wheelchair and stretcher riders:{" "}
            <b className="text-ink">
              {s?.mobilityOutBeforeFire} of {s?.mobilityRiders}
            </b>
            . {s?.stayed} chose to stay and{" "}
            {s?.unreached} never answered (door-knock list). {s?.vehicles} vehicles; none ever over its seats.
          </p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
            <Key c="bg-[rgb(244,63,94)]" t="waiting for a ride" />
            <Key c="bg-[rgb(241,245,249)]" t="responders (number = seats in use)" />
            <Key c="bg-[rgb(251,146,60)]" t="neighbors with a seat" />
            <Key c="bg-[rgb(52,211,153)]" t="leaving on their own" />
            <Key c="bg-[rgb(255,92,40)]" t="fire (simulated)" />
          </div>
        </>
      )}
    </section>
  );
}

function Big({ label, value, of, tone = "" }: { label: string; value: number; of?: number; tone?: string }) {
  return (
    <div className="rounded-xl border border-line px-2 py-1.5">
      <div className={`font-mono text-xl font-semibold tabular-nums ${tone}`}>
        {value.toLocaleString()}
        {of != null && <span className="text-sm text-muted"> / {of.toLocaleString()}</span>}
      </div>
      <div className="text-[10px] leading-tight text-muted">{label}</div>
    </div>
  );
}

function Key({ c, t }: { c: string; t: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${c}`} />
      {t}
    </span>
  );
}
