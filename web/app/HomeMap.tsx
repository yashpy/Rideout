"use client";

/**
 * Try-it house picker, drawn as a light map of Oak Creek Canyon: canyon terrain bands and contours along
 * SR 89A, Oak Creek, the highway, place names, evacuation zones, closures and shelters, with the homes on
 * top as small dots. Pan (drag), zoom (wheel, + / −) and tap a dot to pick a house.
 *
 * Plain SVG, no WebGL. "Map" is our own drawing and works offline; Terrain / Topo / Satellite add raster
 * tiles underneath (lib/basemaps.ts). Everything is projected to screen pixels, so dots, labels and line
 * widths stay the same size at any zoom while the map scales under them.
 * Red = a person who needs a ride, or fire / a closed road (the only uses of red).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BasemapSwitcher } from "@/components/BasemapSwitcher";
import { RASTER, RELIEF, tileUrl, useBasemap, type RasterLayer } from "@/lib/basemaps";

export type Home = {
  id: string;
  address: string;
  role?: string;
  simulated?: boolean;
  reach?: string;
  location?: { coordinates?: [number, number] };
};

type Doc = { id: string } & Record<string, unknown>;
type LonLat = [number, number];
type XY = [number, number];

const FILL: Record<string, string> = {
  needs_ride: "var(--color-fire)",
  can_help: "var(--color-help)",
  left: "var(--color-out)",
  stay: "var(--color-help)",
};

// SR 89A, south → north (same approximate vertices as api/sim/geo.py).
const SR89A: LonLat[] = [
  [-111.8215, 34.856],
  [-111.8, 34.861],
  [-111.785, 34.864],
  [-111.765, 34.8635],
  [-111.7615, 34.8705],
  [-111.7497, 34.8875],
  [-111.7395, 34.8985],
  [-111.733, 34.914],
  [-111.74, 34.93],
  [-111.7529, 34.9437],
  [-111.748, 34.962],
  [-111.7461, 34.9897],
  [-111.742, 35.0],
  [-111.7383, 35.0122],
  [-111.736, 35.02],
  [-111.733, 35.027],
  [-111.72, 35.07],
  [-111.695, 35.139],
];

const PLACES: { name: string; at: LonLat; strong?: boolean }[] = [
  { name: "Sedona", at: [-111.7615, 34.8705], strong: true },
  { name: "Midgley Bridge", at: [-111.7497, 34.8875] },
  { name: "Grasshopper Point", at: [-111.7395, 34.8985] },
  { name: "Indian Gardens", at: [-111.733, 34.914] },
  { name: "Slide Rock", at: [-111.7529, 34.9437] },
  { name: "West Fork", at: [-111.7461, 34.9897] },
  { name: "Pine Flat", at: [-111.7383, 35.0122] },
  { name: "Oak Creek Vista · to Flagstaff", at: [-111.733, 35.027] },
];

// Local flat projection in meters around the canyon (fine over a few tens of km). y grows southward.
const LAT0 = 34.95;
const KX = 111_320 * Math.cos((LAT0 * Math.PI) / 180);
const KY = 110_540;
const toM = ([lon, lat]: LonLat): XY => [(lon + 111.75) * KX, (LAT0 - lat) * KY];

const fromM = ([x, y]: XY): LonLat => [x / KX - 111.75, LAT0 - y / KY];
const EARTH = 40_075_016.686;
const tileX = (lon: number, z: number) => Math.floor(((lon + 180) / 360) * 2 ** z);
const tileY = (lat: number, z: number) => {
  const r = (lat * Math.PI) / 180;
  return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z);
};
const tileLon = (x: number, z: number) => (x / 2 ** z) * 360 - 180;
const tileLat = (y: number, z: number) => (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / 2 ** z))) * 180) / Math.PI;

/** Polyline offset sideways by `d` meters (positive = east of a south→north line). */
function offset(pts: XY[], d: number): XY[] {
  return pts.map((p, i) => {
    const a = pts[Math.max(0, i - 1)];
    const b = pts[Math.min(pts.length - 1, i + 1)];
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len = Math.hypot(dx, dy) || 1;
    return [p[0] - (dy / len) * d, p[1] + (dx / len) * d];
  });
}

const MIN_ZOOM = 0.6;
const MAX_ZOOM = 14;
const DOT = 4.5; // px
const DOT_SELECTED = 7;
const zoneLabel = (z: Doc) => {
  const n = String(z.name ?? z.id).match(/zone\s*(\d+)/i);
  return n ? `Zone ${n[1]}` : String(z.name ?? z.id);
};
const NICE = [50, 100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000];

export function HomeMap({
  homes,
  selected,
  onSelect,
  zones = [],
  shelters = [],
  closures = [],
  pickedUp,
  selectedLabel,
}: {
  homes: Home[];
  selected: string | null;
  onSelect: (id: string) => void;
  zones?: Doc[];
  shelters?: Doc[];
  closures?: Doc[];
  pickedUp?: Set<string>; // households a driver has picked up (or dropped at a shelter): drawn grey and faint
  selectedLabel?: string | null; // the address shown in the popup (a typed address wins over the house's)
}) {
  // Callback ref: the <svg> only exists once homes have arrived, so effects key off the element itself.
  const [svgEl, setSvgEl] = useState<SVGSVGElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [basemap, setBasemap] = useBasemap("picker", "map");
  const [view, setView] = useState({ s: 1, px: 0, py: 0 });
  const drag = useRef<{ id: number; x: number; y: number; px: number; py: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);

  useEffect(() => {
    if (!svgEl) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(svgEl);
    return () => ro.disconnect();
  }, [svgEl]);

  const pts = useMemo(() => homes.filter((h) => h.location?.coordinates?.length === 2), [homes]);
  // The canyon art (SR 89A, creek, contours, place names) only belongs to the Oak Creek scenario. The Phoenix
  // metro scenario has no hand drawing, so it always shows real street tiles underneath.
  const canyon = useMemo(
    () => pts.length > 0 && pts.reduce((s, h) => s + Number(h.location!.coordinates![1]), 0) / pts.length > 34.4,
    [pts],
  );

  // Frame: the homes' extent in meters, with a margin.
  const frame = useMemo(() => {
    if (!pts.length) return null;
    const xy = pts.map((h) => toM(h.location!.coordinates as LonLat));
    const xs = xy.map((p) => p[0]);
    const ys = xy.map((p) => p[1]);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, w: Math.max(x1 - x0, 400) * 1.12, h: Math.max(y1 - y0, 400) * 1.08 };
  }, [pts]);

  const fit = frame && size.w && size.h ? Math.min(size.w / frame.w, size.h / frame.h) : 0;
  const k = fit * view.s; // px per meter
  const project = useCallback(
    (m: XY): XY =>
      frame ? [size.w / 2 + (m[0] - frame.cx) * k + view.px, size.h / 2 + (m[1] - frame.cy) * k + view.py] : [0, 0],
    [frame, size.w, size.h, k, view.px, view.py],
  );
  const P = useCallback((ll: LonLat) => project(toM(ll)), [project]);
  const path = (xy: XY[]) => xy.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");

  const road = useMemo(() => SR89A.map(toM), []);
  const contours = useMemo(() => [-1900, -1300, -800, 800, 1300, 1900].map((d) => offset(road, d)), [road]);
  const creek = useMemo(() => offset(road, -70), [road]);

  // Zoom around a screen point.
  const zoomAt = useCallback(
    (factor: number, sx: number, sy: number) => {
      setView((v) => {
        const s = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.s * factor));
        const r = s / v.s;
        return {
          s,
          px: sx - size.w / 2 - (sx - size.w / 2 - v.px) * r,
          py: sy - size.h / 2 - (sy - size.h / 2 - v.py) * r,
        };
      });
    },
    [size.w, size.h],
  );

  // A new selection (tap or typed address): zoom in a little and bring the house to the middle.
  const selLL = useMemo(() => {
    const h = selected ? pts.find((x) => x.id === selected) : null;
    return (h?.location?.coordinates as LonLat | undefined) ?? null;
  }, [selected, pts]);
  const selKey = selLL ? `${selected}|${selLL[0]}|${selLL[1]}` : null;
  useEffect(() => {
    if (!selKey || !selLL || !frame || !fit) return;
    const [mx, my] = toM(selLL);
    setView((v) => {
      const s = Math.max(v.s, 3);
      return { s, px: -(mx - frame.cx) * fit * s, py: -(my - frame.cy) * fit * s };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the selection itself changes
  }, [selKey, !!frame, fit > 0]);

  useEffect(() => {
    const el = svgEl;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [svgEl, zoomAt]);

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, px: view.px, py: view.py, moved: false };
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 5) return;
    if (!d.moved) {
      d.moved = true;
      e.currentTarget.setPointerCapture(e.pointerId); // only once it's a drag, so taps still reach the dots
    }
    setView((v) => ({ ...v, px: d.px + dx, py: d.py + dy }));
  };
  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    suppressClick.current = d.moved;
    drag.current = null;
  };
  const pick = (id: string) => {
    if (suppressClick.current) {
      suppressClick.current = false;
      return;
    }
    onSelect(id);
  };

  const scale = useMemo(() => {
    if (!k) return null;
    const target = 110 / k; // meters in ~110 px
    const m = NICE.reduce((best, n) => (Math.abs(n - target) < Math.abs(best - target) ? n : best), NICE[0]);
    return { px: m * k, label: m >= 1000 ? `${m / 1000} km` : `${m} m` };
  }, [k]);

  // Raster tiles for the chosen base map, covering the visible area.
  const base = canyon || (basemap !== "map" && basemap !== "terrain") ? basemap : "topo";
  const raster = base === "terrain" ? RELIEF : RASTER[base];
  const tiles = useMemo(() => {
    if (!raster || !frame || !k || !size.w) return [];
    const inv = (sx: number, sy: number) =>
      fromM([frame.cx + (sx - size.w / 2 - view.px) / k, frame.cy + (sy - size.h / 2 - view.py) / k]);
    const [w0, n0] = inv(0, 0);
    const [e0, s0] = inv(size.w, size.h);
    const out: { key: string; href: string; x: number; y: number; w: number; h: number; opacity: number }[] = [];
    raster.layers.forEach((layer: RasterLayer, li) => {
      // Zoom where one 256 px tile is about 256 screen px; capped by the layer's max zoom.
      const z = Math.max(
        3,
        Math.min(layer.maxzoom, Math.round(Math.log2((EARTH * Math.cos((LAT0 * Math.PI) / 180) * k) / 256))),
      );
      const [x0, x1] = [tileX(w0, z), tileX(e0, z)];
      const [y0, y1] = [tileY(n0, z), tileY(s0, z)];
      if ((x1 - x0 + 1) * (y1 - y0 + 1) > 160) return;
      for (let x = x0; x <= x1; x++)
        for (let y = y0; y <= y1; y++) {
          const [ax, ay] = P([tileLon(x, z), tileLat(y, z)]);
          const [bx, by] = P([tileLon(x + 1, z), tileLat(y + 1, z)]);
          out.push({
            key: `${li}/${z}/${x}/${y}`,
            href: tileUrl(layer.url, z, x, y),
            x: ax,
            y: ay,
            w: bx - ax,
            h: by - ay,
            opacity: layer.opacity ?? 1,
          });
        }
    });
    return out;
  }, [raster, frame, k, size.w, size.h, view.px, view.py, P]);
  const drawn = canyon && (basemap === "map" || basemap === "terrain"); // our own canyon drawing (bands, contours, creek)

  if (!pts.length) {
    return (
      <p className="relative m-auto p-6 text-sm text-muted">No homes yet. Seed the scenario first (POST /sim/seed).</p>
    );
  }

  const sel = pts.find((h) => h.id === selected);
  const ordered = sel ? [...pts.filter((h) => h.id !== selected), sel] : pts;
  const halo = { paintOrder: "stroke", stroke: "var(--color-bg)", strokeWidth: 3.5, strokeLinejoin: "round" } as const;
  const zoneColor = (st: unknown) =>
    st === "go" ? "var(--color-fire)" : st === "set" ? "var(--color-help)" : "var(--color-muted)";

  return (
    <div className="absolute inset-0">
      <svg
        ref={setSvgEl}
        className="h-full w-full cursor-grab select-none active:cursor-grabbing"
        style={{ touchAction: "none" }}
        role="group"
        aria-label="Map of homes in Oak Creek Canyon"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {fit > 0 && (
          <>
            {/* raster base map (Terrain / Topo / Satellite) */}
            {tiles.map((t) => (
              <image
                key={t.key}
                href={t.href}
                x={t.x}
                y={t.y}
                width={t.w + 0.5}
                height={t.h + 0.5}
                preserveAspectRatio="none"
                opacity={basemap === "terrain" ? 0.55 : t.opacity}
              />
            ))}

            {/* terrain: canyon rim, canyon floor, contours */}
            {drawn && (
              <>
                <path
                  d={path(road.map(project))}
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  stroke="color-mix(in srgb, var(--color-help) 9%, transparent)"
                  strokeWidth={4200 * k}
                />
                <path
                  d={path(road.map(project))}
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  stroke="color-mix(in srgb, var(--color-out) 11%, transparent)"
                  strokeWidth={1500 * k}
                />
                {contours.map((c, i) => (
                  <path
                    key={i}
                    d={path(c.map(project))}
                    fill="none"
                    strokeLinejoin="round"
                    stroke="color-mix(in srgb, var(--color-help) 30%, var(--color-line-strong))"
                    strokeOpacity={0.55}
                    strokeWidth={1}
                    strokeDasharray={i % 2 ? "0" : "6 5"}
                  />
                ))}
              </>
            )}

            {/* evacuation zones */}
            {zones.map((z) => {
              const ring = (z.polygon as { coordinates?: LonLat[][] })?.coordinates?.[0];
              if (!ring) return null;
              const c = zoneColor(z.status);
              // Label just outside the zone's west edge, halfway up, clear of the homes.
              const xy = ring.map(P);
              const ys = xy.map((q) => q[1]);
              const ly = (Math.min(...ys) + Math.max(...ys)) / 2;
              const lx = Math.min(...xy.map((q) => q[0]));
              return (
                <g key={z.id}>
                  <path
                    d={path(ring.map(P)) + "Z"}
                    fill={`color-mix(in srgb, ${c} 7%, transparent)`}
                    stroke={c}
                    strokeOpacity={0.7}
                    strokeWidth={1.5}
                    strokeDasharray="7 5"
                  />
                  <text x={lx - 8} y={ly + 4} fontSize={11} fontWeight={600} fill={c} textAnchor="end" style={halo}>
                    {zoneLabel(z)}
                    {z.status ? ` · ${String(z.status).toUpperCase()}` : ""}
                  </text>
                </g>
              );
            })}

            {/* Oak Creek + SR 89A */}
            {drawn && (
              <path
                d={path(creek.map(project))}
                fill="none"
                strokeLinecap="round"
                strokeLinejoin="round"
                stroke="color-mix(in srgb, var(--color-vehicle) 55%, transparent)"
                strokeWidth={2}
              />
            )}
            {canyon && (
              <>
                <path
                  d={path(road.map(project))}
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  stroke="var(--color-line-strong)"
                  strokeWidth={7}
                />
                <path
                  d={path(road.map(project))}
                  fill="none"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  stroke="var(--color-panel)"
                  strokeWidth={4}
                />
              </>
            )}
            {closures.map((c) => {
              const line = (c.geometry as { coordinates?: LonLat[] })?.coordinates;
              return line?.length ? (
                <path
                  key={c.id}
                  d={path(line.map(P))}
                  fill="none"
                  stroke="var(--color-fire)"
                  strokeWidth={5}
                  strokeLinecap="round"
                  strokeDasharray="2 7"
                />
              ) : null;
            })}
            {canyon && (() => {
              const [x, y] = P([-111.7429, 34.9205]);
              return (
                <text
                  x={x - 12}
                  y={y}
                  fontSize={10}
                  fontWeight={700}
                  letterSpacing="0.08em"
                  fill="var(--color-muted)"
                  textAnchor="end"
                  style={halo}
                >
                  SR 89A
                </text>
              );
            })()}

            {/* shelters */}
            {shelters.map((s) => {
              const ll = (s.location as { coordinates?: LonLat })?.coordinates;
              if (!ll) return null;
              const [x, y] = P(ll);
              return (
                <g key={s.id}>
                  <rect
                    x={x - 5}
                    y={y - 5}
                    width={10}
                    height={10}
                    rx={2}
                    fill="var(--color-sim)"
                    stroke="var(--color-panel)"
                    strokeWidth={1.5}
                  />
                  <text x={x + 9} y={y + 4} fontSize={11} fontWeight={600} fill="var(--color-sim)" style={halo}>
                    {String(s.name ?? "Shelter")}
                  </text>
                </g>
              );
            })}

            {/* homes */}
            {ordered.map((h) => {
              const [x, y] = P(h.location!.coordinates as LonLat);
              const isSel = h.id === selected;
              return (
                <g key={h.id} className="cursor-pointer" onClick={() => pick(h.id)}>
                  <circle cx={x} cy={y} r={DOT + 3} fill="transparent" />
                  {isSel && (
                    <circle
                      cx={x}
                      cy={y}
                      r={DOT_SELECTED + 5}
                      fill="color-mix(in srgb, var(--color-accent) 22%, transparent)"
                    />
                  )}
                  {isSel && (
                    <circle cx={x} cy={y} r={DOT_SELECTED + 5} fill="none" stroke="var(--color-accent)" strokeWidth={2}>
                      <animate attributeName="r" values={`${DOT_SELECTED + 3};${DOT_SELECTED + 16}`} dur="1.4s" repeatCount="indefinite" />
                      <animate attributeName="opacity" values="0.9;0" dur="1.4s" repeatCount="indefinite" />
                    </circle>
                  )}
                  <circle
                    cx={x}
                    cy={y}
                    r={isSel ? DOT_SELECTED : DOT}
                    opacity={pickedUp?.has(h.id) && !isSel ? 0.45 : 1}
                    fill={pickedUp?.has(h.id) ? "var(--color-unknown)" : (FILL[h.role ?? ""] ?? "var(--color-unknown)")}
                    stroke={
                      isSel
                        ? "var(--color-accent)"
                        : h.simulated === false
                          ? "var(--color-vehicle)"
                          : "var(--color-panel)"
                    }
                    strokeWidth={isSel ? 2.5 : h.simulated === false ? 2 : 1.25}
                  >
                    <title>{h.address}</title>
                  </circle>
                </g>
              );
            })}
            {/* places */}
            {(canyon ? PLACES : []).map((p) => {
              const [x, y] = P(p.at);
              return (
                <g key={p.name} pointerEvents="none">
                  <circle cx={x} cy={y} r={2.5} fill="var(--color-muted)" />
                  <text
                    x={x + 12}
                    y={y + 4}
                    fontSize={p.strong ? 13 : 11}
                    fontWeight={p.strong ? 600 : 500}
                    fill={p.strong ? "var(--color-ink)" : "var(--color-muted)"}
                    style={halo}
                  >
                    {p.name}
                  </text>
                </g>
              );
            })}
          </>
        )}
      </svg>

      {/* the selected house: its address, pinned above the dot */}
      {sel && fit > 0 && (() => {
        const [x, y] = P(sel.location!.coordinates as LonLat);
        if (x < 0 || y < 0 || x > size.w || y > size.h) return null;
        return (
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full animate-rise"
            style={{ left: x, top: y - 16 }}
            role="status"
          >
            <div className="glass max-w-72 rounded-2xl! px-3.5 py-2.5 text-left">
              <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-accent">Your house</p>
              <p className="mt-0.5 text-[13px] leading-snug font-medium text-ink">{selectedLabel ?? sel.address}</p>
            </div>
            <span className="mx-auto block h-2.5 w-2.5 -translate-y-1.5 rotate-45 border-r border-b border-line bg-panel" />
          </div>
        );
      })()}

      {/* north arrow + scale */}
      <div className="pointer-events-none absolute right-4 bottom-4 flex flex-col items-end gap-2">
        {scale && (
          <div className="glass flex flex-col items-start gap-1 rounded-lg! px-2.5 py-1.5 text-[10px] text-muted">
            <span>{scale.label}</span>
            <span className="block h-1.5 border-x-2 border-b-2 border-muted" style={{ width: scale.px }} />
          </div>
        )}
      </div>

      {/* base map + zoom */}
      {raster && (
        <span className="pointer-events-none absolute right-4 bottom-[4.6rem] max-w-[22rem] text-right text-[9px] text-muted">
          {raster.attribution}
        </span>
      )}
      <div className="absolute top-4 right-4 flex flex-col items-end gap-2">
        <BasemapSwitcher value={basemap} onChange={setBasemap} />
        <div className="glass flex overflow-hidden rounded-full! text-ink">
          {[
            { label: "Zoom in", text: "+", f: 1.6 },
            { label: "Zoom out", text: "−", f: 1 / 1.6 },
          ].map((b) => (
            <button
              key={b.label}
              type="button"
              aria-label={b.label}
              title={b.label}
              onClick={() => zoomAt(b.f, size.w / 2, size.h / 2)}
              className="h-8 w-8 text-base leading-none hover:bg-ink/5"
            >
              {b.text}
            </button>
          ))}
          <button
            type="button"
            aria-label="Reset view"
            title="Reset view"
            onClick={() => setView({ s: 1, px: 0, py: 0 })}
            className="h-8 px-2.5 text-[11px] text-muted hover:bg-ink/5 hover:text-ink"
          >
            Reset
          </button>
        </div>
        <div className="pointer-events-none mr-1 flex flex-col items-center text-muted" aria-hidden>
          <svg viewBox="0 0 24 32" className="h-8 w-6">
            <path d="M12 2 L18 22 L12 18 L6 22 Z" fill="var(--color-ink)" fillOpacity={0.75} />
          </svg>
          <span className="text-[10px] font-semibold">N</span>
        </div>
      </div>

      {/* legend */}
      <div className="glass pointer-events-none absolute bottom-4 left-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-full! px-3 py-1.5 text-[11px] text-muted">
        {[
          ["var(--color-fire)", "needs a ride"],
          ["var(--color-help)", "can help"],
          ["var(--color-out)", "left"],
          ["var(--color-unknown)", "not reached"],
          ["color-mix(in srgb, var(--color-unknown) 45%, transparent)", "picked up"],
        ].map(([c, l]) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: c }} />
            {l}
          </span>
        ))}
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full border-2 border-accent" />
          your house
        </span>
      </div>
    </div>
  );
}
