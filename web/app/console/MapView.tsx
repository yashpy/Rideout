"use client";

/**
 * Console map: MapLibre basemap + deck.gl layers.
 * Red = fire or a person who needs help, nothing else. Blue = our vehicles and their routes.
 * If the basemap can't load (venue Wi-Fi), the map falls back to a plain dark background: every
 * deck.gl layer still draws.
 */
import "maplibre-gl/dist/maplibre-gl.css";

import { MapboxOverlay, type MapboxOverlayProps } from "@deck.gl/mapbox";
import { IconLayer, PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import { setWorkerUrl, type StyleSpecification } from "maplibre-gl";
import type { Theme } from "@/lib/theme";
import { useEffect, useMemo, useState } from "react";
import MapGL, { useControl, type MapLayerMouseEvent } from "react-map-gl/maplibre";
import { addRelief, rideOutStyle } from "./mapStyle";
import { BasemapSwitcher } from "@/components/BasemapSwitcher";
import { RASTER, useBasemap, type Basemap } from "@/lib/basemaps";
import type { FireView } from "@/lib/api";
import { useEvacLayers } from "./Evacuation";

type Doc = { id: string } & Record<string, unknown>;
type LonLat = [number, number];
type RGBA = [number, number, number, number];

export const COLORS: Record<string, RGBA> = {
  fire: [255, 77, 61, 255],
  help: [245, 165, 36, 255],
  out: [34, 197, 94, 255],
  unknown: [107, 114, 128, 255],
  vehicle: [77, 163, 255, 255],
  shelter: [167, 139, 250, 255],
  ink: [230, 233, 239, 255],
};

// Vehicles are drawn as top-down cars / vans pointing north; IconLayer turns them to their heading.
// Paratransit and agency vans get the longer van shape; neighbors and volunteers a car.
function vehicleSvg(kind: "car" | "van", body: string): string {
  const len = kind === "van" ? 86 : 72;
  const top = (96 - len) / 2;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="96" viewBox="0 0 64 96">` +
    `<rect x="14" y="${top}" width="36" height="${len}" rx="${kind === "van" ? 8 : 13}" fill="${body}" stroke="white" stroke-width="4"/>` +
    // windshield (front = up), rear window, roof line
    `<rect x="19" y="${top + 13}" width="26" height="${kind === "van" ? 12 : 14}" rx="4" fill="#0b1220" fill-opacity="0.78"/>` +
    `<rect x="20" y="${top + len - 15}" width="24" height="8" rx="3" fill="#0b1220" fill-opacity="0.55"/>` +
    `<rect x="22" y="${top + (kind === "van" ? 30 : 31)}" width="20" height="${len - (kind === "van" ? 50 : 50)}" rx="3" fill="white" fill-opacity="0.18"/>` +
    // headlights
    `<circle cx="20" cy="${top + 4}" r="2.4" fill="#fff6c2"/><circle cx="44" cy="${top + 4}" r="2.4" fill="#fff6c2"/>` +
    `</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}
const VEHICLE_ICONS = {
  car: vehicleSvg("car", "#4da3ff"),
  van: vehicleSvg("van", "#4da3ff"),
  carAlert: vehicleSvg("car", "#ff4d3d"),
  vanAlert: vehicleSvg("van", "#ff4d3d"),
};
const isVan = (v: Doc) => ["paratransit", "agency_van", "van"].includes(String(v.kind));
const inDanger = (v: Doc) => ["sos", "man_down"].includes(String((v.safety as { state?: string } | undefined)?.state));

const ROLE_COLOR: Record<string, RGBA> = {
  needs_ride: COLORS.fire,
  can_help: COLORS.help,
  left: COLORS.out,
  stay: [190, 120, 110, 255],
  unknown: COLORS.unknown,
};

// OpenFreeMap's Dark Matter fork: free, no API key (CARTO's basemaps now need one). Override with
// NEXT_PUBLIC_MAP_STYLE, e.g. a CARTO style URL with ?key=… if we get a key.
const STYLE_URL: Record<Theme, string> = {
  dark: process.env.NEXT_PUBLIC_MAP_STYLE || "https://tiles.openfreemap.org/styles/dark",
  light: process.env.NEXT_PUBLIC_MAP_STYLE_LIGHT || "https://tiles.openfreemap.org/styles/positron",
};
/** Satellite / Topo: raster tiles only; every label we need is drawn by deck.gl. */
function rasterStyle(b: Basemap): StyleSpecification | null {
  const r = RASTER[b];
  if (!r) return null;
  return {
    version: 8,
    sources: Object.fromEntries(
      r.layers.map((l, i) => [
        `base-${i}`,
        { type: "raster", tiles: [l.url], tileSize: 256, maxzoom: l.maxzoom, ...(i === 0 ? { attribution: r.attribution } : {}) },
      ]),
    ),
    layers: r.layers.map((l, i) => ({ id: `base-${i}`, type: "raster", source: `base-${i}`, paint: { "raster-opacity": l.opacity ?? 1 } })),
  } as StyleSpecification;
}
const fallbackStyle = (theme: Theme): StyleSpecification => ({
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": theme === "dark" ? "#060a14" : "#eef3fa" } }],
});
// Halo around labels/lines (the page background) and label ink, per theme.
const HALO: Record<Theme, RGBA> = { dark: [6, 10, 20, 255], light: [238, 243, 250, 255] };
const INK: Record<Theme, RGBA> = { dark: [230, 233, 239, 255], light: [18, 22, 29, 255] };
const SHELTER_INK: Record<Theme, RGBA> = { dark: [167, 139, 250, 255], light: [109, 40, 217, 255] };
const FONT = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

// Served from /public by scripts/copy-maplibre-worker.mjs (the bundler can't resolve MapLibre's own URL).
setWorkerUrl("/maplibre-gl-worker.mjs");

// The canyon tract + the Red Rock HS shelter, framed in the gap between the console's side panels.
export type Padding = { top: number; bottom: number; left: number; right: number };
export const CANYON_BOUNDS: [[number, number], [number, number]] = [
  [-111.835, 34.845],
  [-111.715, 35.02],
];
// The console's default: the canyon in the gap between its two side panels, below the KPI strip and
// above the fire replay bar + legend.
const CONSOLE_PADDING: Padding = { top: 150, bottom: 250, left: 390, right: 420 };

function lonlat(doc: unknown): LonLat | null {
  const c = (doc as { location?: { coordinates?: number[] } } | undefined)?.location?.coordinates;
  return c && c.length >= 2 ? [Number(c[0]), Number(c[1])] : null;
}

const EVAC_KEEP = new Set(["zones", "shelters", "shelter-names"]);

function DeckOverlay(props: MapboxOverlayProps) {
  const overlay = useControl<MapboxOverlay>(() => new MapboxOverlay(props));
  overlay.setProps(props);
  return null;
}

export type MapViewProps = {
  households: Doc[];
  requests: Record<string, Doc>;
  vehicles: Doc[];
  assignments: Doc[];
  closures: Doc[];
  hazards: Doc[];
  shelters: Doc[];
  zones: Doc[];
  selectedHouseholdId: string | null;
  highlightAssignmentId: string | null;
  drawing: LonLat[] | null; // road-closure tool: points so far (null = tool off)
  onSelectHousehold: (id: string | null) => void;
  onMapClick: (p: LonLat) => void;
  theme?: Theme;
  padding?: Padding; // keeps the canyon clear of the page's panels
  layersClassName?: string; // where the View dropdown (Map / Terrain / Topo / Satellite) sits
  layersStyle?: React.CSSProperties;
  fire?: FireView | null; // simulated fire replay (GET /hazards/fire)
  bounds?: [[number, number], [number, number]]; // the scenario's box (GET /sim/scenario); default: the canyon
};

export default function MapView(p: MapViewProps) {
  const theme: Theme = p.theme ?? "dark";
  // Base map: "map" = the original OpenFreeMap style; "terrain" = RideOut's recolor + hillshade;
  // "topo" / "satellite" = raster tiles (lib/basemaps.ts). Remembered per browser.
  const [basemap, setBasemap] = useBasemap("console", "map");
  const styleKey = `${theme}-${basemap}`;
  const [failedFor, setFailedFor] = useState<string | null>(null); // basemap unreachable: plain background
  const failed = failedFor === styleKey;
  const [loaded, setLoaded] = useState(false);
  // Vector styles are fetched; the map mounts once the style is ready, so the deck.gl overlay never sees a
  // style swap (a swap drops it). Raster styles are built locally.
  const [styled, setStyled] = useState<{ key: string; style: StyleSpecification } | null>(null);
  const raster = useMemo(() => rasterStyle(basemap), [basemap]);
  useEffect(() => {
    if (raster) return;
    let off = false;
    const key = `${theme}-${basemap}`;
    fetch(STYLE_URL[theme])
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((s: StyleSpecification) => !off && setStyled({ key, style: basemap === "terrain" ? rideOutStyle(s, theme) : s }))
      .catch(() => {
        if (!off) setFailedFor(key);
      });
    return () => {
      off = true;
    };
  }, [theme, basemap, raster]);
  const style = failed ? fallbackStyle(theme) : raster ?? (styled?.key === styleKey ? styled.style : null);
  const halo = HALO[theme];
  const ink = INK[theme];

  const requestByHousehold = useMemo(() => {
    const m: Record<string, Doc> = {};
    for (const r of Object.values(p.requests)) if (r.status !== "closed") m[String(r.householdId)] = r;
    return m;
  }, [p.requests]);

  const homeById = useMemo(() => Object.fromEntries(p.households.map((h) => [h.id, h])), [p.households]);
  // Picked up (on board) or dropped at a shelter: the home turns grey and faint.
  const picked = useMemo(() => {
    const out = new Set<string>();
    for (const r of Object.values(p.requests)) if (r.status === "arrived") out.add(String(r.householdId));
    for (const h of p.households) if (h.safeAt) out.add(h.id);
    return out;
  }, [p.requests, p.households]);
  const vehicleById = useMemo(() => Object.fromEntries(p.vehicles.map((v) => [v.id, v])), [p.vehicles]);

  // Lines: proposed/offered = vehicle → home; accepted = the vehicle's run in stop order.
  const lines = useMemo(() => {
    const out: { path: LonLat[]; status: string; id: string }[] = [];
    const runs: Record<string, Doc[]> = {};
    for (const a of p.assignments) {
      const req = p.requests[String(a.requestId)];
      const home = req ? lonlat(homeById[String(req.householdId)]) : null;
      const veh = lonlat(vehicleById[String(a.vehicleId)]);
      if (!home || !veh) continue;
      if (a.status === "accepted") (runs[String(a.vehicleId)] ??= []).push(a);
      else if (a.status === "proposed" || a.status === "offered") out.push({ path: [veh, home], status: String(a.status), id: a.id });
    }
    for (const [vid, stops] of Object.entries(runs)) {
      const veh = lonlat(vehicleById[vid]);
      const pts = stops
        .filter((a) => {
          const st = p.requests[String(a.requestId)]?.status;
          return st === "driver_accepted" || st === "en_route";
        })
        .sort((a, b) => Number(a.stopOrder ?? 0) - Number(b.stopOrder ?? 0))
        .map((a) => lonlat(homeById[String(p.requests[String(a.requestId)]?.householdId)]))
        .filter((x): x is LonLat => !!x);
      if (veh && pts.length) out.push({ path: [veh, ...pts], status: "accepted", id: `run-${vid}` });
    }
    return out;
  }, [p.assignments, p.requests, homeById, vehicleById]);

  // "Play evacuation" (Evacuation.tsx) swaps the live layers for its own, keeping zones and shelters.
  const evac = useEvacLayers((x) => x.layers);
  const layers = [
    new PolygonLayer<Doc>({
      id: "zones",
      data: p.zones.filter((z) => (z.polygon as { coordinates?: unknown })?.coordinates),
      getPolygon: (z) => (z.polygon as { coordinates: LonLat[][] }).coordinates[0],
      getFillColor: (z) =>
        z.status === "go" ? [255, 77, 61, 28] : z.status === "set" ? [245, 165, 36, 22] : ([...ink.slice(0, 3), 10] as RGBA),
      getLineColor: (z) =>
        z.status === "go" ? COLORS.fire : z.status === "set" ? COLORS.help : ([...ink.slice(0, 3), 110] as RGBA),
      getLineWidth: 2,
      lineWidthUnits: "pixels",
      updateTriggers: {
        getFillColor: [theme, p.zones.map((z) => z.status)],
        getLineColor: [theme, p.zones.map((z) => z.status)],
      },
    }),
    // Simulated fire replay: burned area so far + hotspots from the last 30 min (newest brightest).
    new PolygonLayer<{ ring: LonLat[] }>({
      id: "fire-burned",
      data: p.fire && p.fire.burned.length > 3 ? [{ ring: p.fire.burned }] : [],
      getPolygon: (d) => d.ring,
      getFillColor: [255, 77, 61, theme === "dark" ? 46 : 38],
      getLineColor: [255, 77, 61, 200],
      getLineWidth: 1.5,
      lineWidthUnits: "pixels",
      updateTriggers: { getFillColor: theme },
    }),
    new ScatterplotLayer<FireView["active"][number]>({
      id: "fire-active-glow",
      data: p.fire?.active ?? [],
      getPosition: (d) => [d.lon, d.lat],
      getRadius: (d) => 4 + Math.min(9, d.frp / 8),
      radiusUnits: "pixels",
      getFillColor: (d) => [255, 120, 61, Math.round(70 * (1 - d.ageMin / 35))],
    }),
    new ScatterplotLayer<FireView["active"][number]>({
      id: "fire-active",
      data: p.fire?.active ?? [],
      getPosition: (d) => [d.lon, d.lat],
      getRadius: (d) => 1.5 + Math.min(4, d.frp / 20),
      radiusUnits: "pixels",
      getFillColor: (d) => [255, 77, 61, Math.round(255 - 150 * (d.ageMin / 30))],
      pickable: true,
    }),
    new PolygonLayer<Doc>({
      id: "fire",
      data: p.hazards.filter((h) => (h.geometry as { type?: string })?.type === "Polygon"),
      getPolygon: (h) => (h.geometry as { coordinates: LonLat[][] }).coordinates[0],
      getFillColor: [255, 77, 61, 70],
      getLineColor: COLORS.fire,
      getLineWidth: 2,
      lineWidthUnits: "pixels",
    }),
    new ScatterplotLayer<Doc>({
      id: "fire-points",
      data: p.hazards.filter((h) => (h.geometry as { type?: string })?.type === "Point"),
      getPosition: (h) => (h.geometry as { coordinates: LonLat }).coordinates,
      getRadius: 6,
      radiusUnits: "pixels",
      getFillColor: COLORS.fire,
    }),
    new PathLayer<Doc>({
      id: "closures-halo",
      data: p.closures,
      getPath: (c) => (c.geometry as { coordinates: LonLat[] }).coordinates,
      getColor: halo,
      getWidth: 13,
      widthUnits: "pixels",
      capRounded: true,
    }),
    new PathLayer<Doc>({
      id: "closures",
      data: p.closures,
      getPath: (c) => (c.geometry as { coordinates: LonLat[] }).coordinates,
      getColor: COLORS.fire,
      getWidth: 8,
      widthUnits: "pixels",
      capRounded: true,
    }),
    new PathLayer<{ path: LonLat[]; status: string; id: string }>({
      id: "routes-glow",
      data: lines.filter((l) => l.status === "accepted" || l.id === p.highlightAssignmentId),
      getPath: (l) => l.path,
      getColor: [COLORS.vehicle[0], COLORS.vehicle[1], COLORS.vehicle[2], 55],
      getWidth: 11,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
    }),
    new PathLayer<{ path: LonLat[]; status: string; id: string }>({
      id: "routes",
      data: lines,
      getPath: (l) => l.path,
      getColor: (l) =>
        l.id === p.highlightAssignmentId
          ? ink
          : l.status === "accepted"
            ? COLORS.vehicle
            : l.status === "offered"
              ? [77, 163, 255, 170]
              : [77, 163, 255, 90],
      getWidth: (l) => (l.id === p.highlightAssignmentId ? 4 : l.status === "accepted" ? 3 : 1.5),
      widthUnits: "pixels",
      updateTriggers: { getColor: [theme, p.highlightAssignmentId], getWidth: p.highlightAssignmentId },
    }),
    // Glow: people who need a ride and our vans light up off the dark map.
    new ScatterplotLayer<Doc>({
      id: "homes-glow",
      data: p.households.filter((h) => h.role === "needs_ride" && lonlat(h)),
      getPosition: (h) => lonlat(h)!,
      getRadius: 15,
      radiusUnits: "pixels",
      getFillColor: [COLORS.fire[0], COLORS.fire[1], COLORS.fire[2], theme === "dark" ? 60 : 45],
      updateTriggers: { getFillColor: theme },
    }),
    new ScatterplotLayer<Doc>({
      id: "vehicles-glow",
      data: p.vehicles.filter((v) => lonlat(v)),
      getPosition: (v) => lonlat(v)!,
      getRadius: 19,
      radiusUnits: "pixels",
      getFillColor: [COLORS.vehicle[0], COLORS.vehicle[1], COLORS.vehicle[2], theme === "dark" ? 55 : 40],
      transitions: { getPosition: 900 },
      updateTriggers: { getFillColor: theme },
    }),
    new ScatterplotLayer<Doc>({
      id: "homes",
      data: p.households.filter((h) => lonlat(h)),
      getPosition: (h) => lonlat(h)!,
      getRadius: (h) => (h.role === "needs_ride" && !picked.has(h.id) ? 6 : 3.5),
      radiusUnits: "pixels",
      getFillColor: (h) =>
        picked.has(h.id)
          ? [COLORS.unknown[0], COLORS.unknown[1], COLORS.unknown[2], 110]
          : (ROLE_COLOR[String(h.role)] ?? COLORS.unknown),
      stroked: true,
      getLineColor: (h) =>
        h.id === p.selectedHouseholdId
          ? ink
          : requestByHousehold[h.id]?.escalation
            ? ink
            : h.simulated === false
              ? COLORS.vehicle // a real household (a kiosk visitor)
              : halo,
      getLineWidth: (h) =>
        h.id === p.selectedHouseholdId ? 3 : requestByHousehold[h.id]?.escalation || h.simulated === false ? 2 : 1,
      lineWidthUnits: "pixels",
      pickable: true,
      updateTriggers: {
        getFillColor: [p.households.map((h) => h.role), picked],
        getRadius: [p.households.map((h) => h.role), picked],
        getLineColor: [theme, p.selectedHouseholdId, requestByHousehold, p.households.map((h) => h.simulated)],
        getLineWidth: [p.selectedHouseholdId, requestByHousehold, p.households.map((h) => h.simulated)],
      },
    }),
    new ScatterplotLayer<Doc>({
      id: "shelters",
      data: p.shelters.filter((s) => lonlat(s)),
      getPosition: (s) => lonlat(s)!,
      getRadius: 8,
      radiusUnits: "pixels",
      getFillColor: COLORS.shelter,
      stroked: true,
      getLineColor: ink,
      getLineWidth: 1.5,
      lineWidthUnits: "pixels",
    }),
    new IconLayer<Doc>({
      id: "vehicles",
      data: p.vehicles.filter((v) => lonlat(v)),
      getPosition: (v) => lonlat(v)!,
      getIcon: (v) => {
        const key = `${isVan(v) ? "van" : "car"}${inDanger(v) ? "Alert" : ""}` as keyof typeof VEHICLE_ICONS;
        return { id: key, url: VEHICLE_ICONS[key], width: 64, height: 96, anchorY: 48, mask: false };
      },
      getSize: (v) => (isVan(v) ? 40 : 34),
      sizeUnits: "pixels",
      getAngle: (v) => -Number(v.heading ?? 0), // heading: clockwise from north; deck: counter-clockwise
      billboard: false,
      pickable: true,
      transitions: { getPosition: 900, getAngle: 400 },
      updateTriggers: { getIcon: p.vehicles.map((v) => `${v.kind}|${inDanger(v)}`) },
    }),
    new TextLayer<Doc>({
      id: "vehicle-names",
      data: p.vehicles.filter((v) => lonlat(v)),
      getPosition: (v) => lonlat(v)!,
      getText: (v) => String(v.driverName ?? v.id),
      getSize: 12,
      getColor: ink,
      getPixelOffset: [0, -26],
      fontWeight: 600,
      outlineWidth: 3,
      outlineColor: halo,
      fontFamily: FONT,
      fontSettings: { sdf: true },
      transitions: { getPosition: 900 },
    }),
    new TextLayer<Doc>({
      id: "closure-labels",
      data: p.closures,
      getPosition: (c) => {
        const pts = (c.geometry as { coordinates: LonLat[] }).coordinates;
        return pts[Math.floor(pts.length / 2)] ?? pts[0];
      },
      getText: () => "CLOSED",
      getSize: 11,
      getColor: COLORS.fire,
      getPixelOffset: [24, 0],
      getTextAnchor: "start",
      fontWeight: 700,
      outlineWidth: 3,
      outlineColor: halo,
      fontFamily: FONT,
      fontSettings: { sdf: true },
    }),
    new TextLayer<Doc>({
      id: "shelter-names",
      data: p.shelters.filter((s) => lonlat(s)),
      getPosition: (s) => lonlat(s)!,
      getText: (s) => String(s.name ?? "Shelter").split(",")[0],
      getSize: 11,
      getColor: SHELTER_INK[theme],
      getPixelOffset: [0, 18],
      outlineWidth: 3,
      outlineColor: halo,
      fontFamily: FONT,
      fontSettings: { sdf: true },
    }),
    new PathLayer<{ path: LonLat[] }>({
      id: "drawing",
      data: p.drawing && p.drawing.length ? [{ path: p.drawing.length === 1 ? [p.drawing[0], p.drawing[0]] : p.drawing }] : [],
      getPath: (d) => d.path,
      getColor: [255, 77, 61, 160],
      getWidth: 7,
      widthUnits: "pixels",
      capRounded: true,
    }),
  ];

  const onClick = (e: MapLayerMouseEvent) => p.onMapClick([e.lngLat.lng, e.lngLat.lat]);

  const layersSwitch = (
    <div className={p.layersClassName ?? "absolute top-[4.6rem] right-3"} style={p.layersStyle}>
      <BasemapSwitcher value={basemap} onChange={setBasemap} />
    </div>
  );
  if (!style)
    return (
      <>
        <div className="absolute inset-0 bg-bg" />
        {layersSwitch}
      </>
    );

  return (
    <>
    <MapGL
      // A new basemap style drops the deck.gl overlay, so a theme switch (or the offline fallback) rebuilds the map.
      key={`${styleKey}-${failed}-${JSON.stringify(p.bounds ?? CANYON_BOUNDS)}`}
      initialViewState={{ bounds: p.bounds ?? CANYON_BOUNDS, fitBoundsOptions: { padding: p.padding ?? CONSOLE_PADDING } }}
      mapStyle={style}
      style={{ position: "absolute", inset: 0 }}
      onLoad={(e) => {
        setLoaded(true);
        if (!failed && basemap === "terrain") addRelief(e.target, theme);
      }}
      onError={(e) => {
        // Only a basemap failure before the first load means "offline": a missing terrain tile doesn't.
        const ev = e as unknown as { sourceId?: string };
        if (!loaded && ev.sourceId !== "rideout-terrain") setFailedFor(styleKey); // basemap unreachable: plain background
      }}
      onClick={onClick}
      cursor={p.drawing ? "crosshair" : undefined}
      attributionControl={{ compact: true }}
    >
      <DeckOverlay
        interleaved={false}
        layers={evac ? [...layers.filter((l) => EVAC_KEEP.has(String(l.id))), ...evac] : layers}
        pickingRadius={10} // small dots, big fingers
        onClick={(info: PickingInfo) => {
          if (p.drawing) return false; // the map click handles the tool
          if (info.layer?.id === "homes" && info.object) {
            p.onSelectHousehold((info.object as Doc).id);
            return true;
          }
          return false;
        }}
        getTooltip={(info: PickingInfo) => {
          const o = info.object as Doc | undefined;
          if (!o) return null;
          if (info.layer?.id === "vehicles") return `${o.driverName} · ${o.kind} · ${o.status}`;
          if (info.layer?.id === "fire-active") {
            const d = info.object as unknown as FireView["active"][number];
            return `Hotspot (SIM) · ${d.frp} MW · ${Math.round(d.ageMin)} min ago`;
          }
          if (info.layer?.id === "homes") {
            const r = requestByHousehold[o.id];
            return `${o.address}\n${String(o.role).replace("_", " ")}${r ? ` · ${r.status}` : ""}`;
          }
          return null;
        }}
      />
    </MapGL>
    {/* Terrain view only: a faint coordinate grid and a vignette, so the map reads as an instrument. */}
    {basemap === "terrain" && (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0"
      style={{
        backgroundImage:
          "radial-gradient(ellipse at center, transparent 55%, color-mix(in srgb, var(--color-bg) 45%, transparent) 100%)," +
          "linear-gradient(color-mix(in srgb, var(--color-accent) 7%, transparent) 1px, transparent 1px)," +
          "linear-gradient(90deg, color-mix(in srgb, var(--color-accent) 7%, transparent) 1px, transparent 1px)",
        backgroundSize: "100% 100%, 64px 64px, 64px 64px",
      }}
    />
    )}
    {layersSwitch}
    </>
  );
}
