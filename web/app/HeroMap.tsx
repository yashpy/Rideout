"use client";

/**
 * Landing-page hero: the real product, not a stock photo. The loaded world's whole night
 * (GET /sim/evacuation) plays on a dark map behind the headline: the fire grows, riders disappear into
 * vehicles, vehicles drive to shelters, green streaks are households leaving on their own. Loops.
 * Not interactive. With reduced motion it shows one still frame. If the API can't plan a night (no world
 * seeded yet), the hero keeps its gradient and the illustration underneath.
 */
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay, type MapboxOverlayProps } from "@deck.gl/mapbox";
import type { Layer } from "@deck.gl/core";
import { setWorkerUrl } from "maplibre-gl";
import { useEffect, useMemo, useState } from "react";
import MapGL, { useControl } from "react-map-gl/maplibre";
import { api, type Evacuation } from "@/lib/api";
import { countsAt, evacLayers, prepare } from "@/lib/evac";

setWorkerUrl("/maplibre-gl-worker.mjs");

const DARK = process.env.NEXT_PUBLIC_MAP_STYLE || "https://tiles.openfreemap.org/styles/dark";
const MIN_PER_S = 7; // scenario minutes per second: the whole night in about 40 s
const BOUNDS: Record<string, [[number, number], [number, number]]> = {
  "scottsdale-fire": [
    [-111.96, 33.6],
    [-111.79, 33.72],
  ],
  "pocket-fire": [
    [-111.835, 34.845],
    [-111.715, 35.02],
  ],
};

function Overlay(props: MapboxOverlayProps) {
  const overlay = useControl<MapboxOverlay>(() => new MapboxOverlay(props));
  overlay.setProps(props);
  return null;
}

export type HeroStats = ReturnType<typeof countsAt> & { minute: number; summary: Evacuation["summary"] };

export default function HeroMap({ onStats }: { onStats?: (s: HeroStats) => void }) {
  const [data, setData] = useState<Evacuation | null>(null);
  const [world, setWorld] = useState<string>("scottsdale-fire");
  const [minute, setMinute] = useState(0);
  const prep = useMemo(() => (data ? prepare(data) : null), [data]);

  useEffect(() => {
    let off = false;
    api
      .scenario()
      .then((s) => !off && setWorld(s.name))
      .catch(() => undefined);
    api
      .evacuation()
      .then((d) => !off && !d.error && d.riders && setData(d))
      .catch(() => undefined);
    return () => {
      off = true;
    };
  }, []);

  useEffect(() => {
    if (!data) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) {
      setMinute(data.endMin * 0.35);
      return;
    }
    let raf = 0;
    let last = performance.now();
    let m = 0;
    let lastPaint = 0;
    const step = (now: number) => {
      m += ((now - last) / 1000) * MIN_PER_S;
      last = now;
      if (m > data.endMin + 20) m = 0; // hold the finish for a moment, then loop
      if (now - lastPaint > 33) {
        setMinute(Math.min(m, data.endMin)); // ~30 fps is plenty for a background
        lastPaint = now;
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [data]);

  const layers: Layer[] = useMemo(
    () => (data && prep ? evacLayers(data, prep, minute, "hero", false) : []),
    [data, prep, minute],
  );
  useEffect(() => {
    if (data && prep && onStats) onStats({ ...countsAt(data, prep, minute), minute, summary: data.summary });
  }, [data, prep, minute, onStats]);

  return (
    // z-0 + isolate: the map and its deck.gl canvas stay below the gradient and the words.
    <div className="absolute inset-0 isolate z-0" aria-hidden>
      <MapGL
        key={world}
        initialViewState={{
          bounds: BOUNDS[world] ?? BOUNDS["scottsdale-fire"],
          // Wide screens: the map sits right of the headline. Phones: below it.
          fitBoundsOptions: {
            padding:
              typeof window !== "undefined" && window.innerWidth < 900
                ? { top: 320, bottom: 20, left: 10, right: 10 }
                : { top: 80, bottom: 40, left: 520, right: 40 },
          },
          pitch: 42,
          bearing: -12,
        }}
        mapStyle={DARK}
        style={{ position: "absolute", inset: 0 }}
        interactive={false}
        attributionControl={{ compact: true }}
      >
        <Overlay interleaved={false} layers={layers} />
      </MapGL>
    </div>
  );
}
