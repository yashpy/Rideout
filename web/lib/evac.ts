/**
 * Evacuation replay geometry, shared by the console player and the landing-page hero: where everyone is
 * at minute `m` of GET /sim/evacuation, and the deck.gl layers that draw it. Pure functions, no React.
 */
import { PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import type { Evacuation } from "@/lib/api";

export type P3 = [number, number, number];
export type Prepared = {
  self: { path: P3[]; leave: number; arrive: number; fire: number | null }[];
  vehicles: (Evacuation["vehicles"][number] & { neighbor: boolean })[];
};

export const TRAIL_MIN = 6; // vehicle trail length (scenario minutes)
export const SELF_TRAIL_MIN = 0.8; // short streaks: thousands of cars at once

export function prepare(data: Evacuation): Prepared {
  const self = data.selfEvac.map(([lon, lat, leave, flat, fire]) => {
    const path: P3[] = [[lon, lat, leave]];
    for (let i = 0; i + 2 < flat.length; i += 3) path.push([flat[i], flat[i + 1], flat[i + 2]]);
    return { path, leave, arrive: path[path.length - 1][2], fire };
  });
  return { self, vehicles: data.vehicles.map((v) => ({ ...v, neighbor: v.kind === "neighbor" })) };
}

export function at(path: P3[], m: number): [number, number] {
  if (m <= path[0][2]) return [path[0][0], path[0][1]];
  const last = path[path.length - 1];
  if (m >= last[2]) return [last[0], last[1]];
  let lo = 0;
  let hi = path.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (path[mid][2] <= m) lo = mid;
    else hi = mid;
  }
  const a = path[lo];
  const b = path[hi];
  const f = b[2] > a[2] ? (m - a[2]) / (b[2] - a[2]) : 1;
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
}

/** The stretch of `path` driven between minutes m0 and m1 (corners included). */
export function slice(path: P3[], m0: number, m1: number): [number, number][] {
  const out: [number, number][] = [at(path, m0)];
  for (const p of path) if (p[2] > m0 && p[2] < m1) out.push([p[0], p[1]]);
  out.push(at(path, m1));
  return out;
}

const EARTH_M = 6_371_000;
/** The fire front `minute` minutes after the warning, as a ring (empty before ignition). Matches the API's
 *  api/hazard/spread.front, which is also what set every home's fire arrival time. */
export function fireRing(model: NonNullable<Evacuation["fireModel"]>, minute: number, points = 96): [number, number][] {
  const elapsed = minute - model.ignitionMin;
  if (elapsed <= 0) return [];
  const [lon0, lat0] = model.ignition;
  const lat1 = (lat0 * Math.PI) / 180;
  const lon1 = (lon0 * Math.PI) / 180;
  const ring: [number, number][] = [];
  for (let i = 0; i <= points; i++) {
    const th = (2 * Math.PI * i) / points;
    const speed = (model.headMPerMin * (1 - model.eccentricity)) / (1 - model.eccentricity * Math.cos(th));
    const d = (elapsed * speed) / EARTH_M;
    const b = ((model.downwindDeg + (th * 180) / Math.PI) * Math.PI) / 180;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(b));
    const lon2 = lon1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(lat1), Math.cos(d) - Math.sin(lat1) * Math.sin(lat2));
    ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return ring;
}

/** Counts at minute m, from the same timelines the map draws. */
export function countsAt(data: Evacuation, prep: Prepared, m: number) {
  let waiting = 0,
    inVehicle = 0,
    ridersSafe = 0,
    lateRiders = 0;
  for (const [, , pick, drop, , fire] of data.riders) {
    // The fire got to their home before the pickup (stays counted after a late pickup too).
    if (fire != null && fire <= m && (pick == null || pick > fire)) lateRiders++;
    if (pick == null || pick > m) waiting++;
    else if (drop == null || drop > m) inVehicle++;
    else ridersSafe++;
  }
  let driving = 0,
    selfSafe = 0;
  for (const s of prep.self) {
    if (s.arrive <= m) selfSafe++;
    else if (s.leave <= m) driving++;
  }
  const canLeave = data.riders.length + prep.self.length;
  return { waiting, inVehicle, ridersSafe, lateRiders, driving, selfSafe, safe: ridersSafe + selfSafe, canLeave };
}

/** deck.gl layers for minute m. `idPrefix` keeps two maps (hero + console) from sharing layer ids. */
export function evacLayers(data: Evacuation, prep: Prepared, m: number, idPrefix = "evac", labels = true): Layer[] {
  // The front at exactly this minute (smooth), plus where it was 12 min ago: the band between is the
  // active edge; inside is the burn scar.
  const frame = data.fireModel
    ? { ring: fireRing(data.fireModel, m) }
    : data.fire[Math.min(data.fire.length - 1, Math.max(0, Math.floor(m / 5)))];
  const scar = data.fireModel ? fireRing(data.fireModel, m - 12) : [];
  const movers: { path: [number, number][] }[] = [];
  const parked: [number, number][] = [];
  for (const s of prep.self) {
    if (m < s.leave) parked.push([s.path[0][0], s.path[0][1]]);
    else if (m < s.arrive) movers.push({ path: slice(s.path, Math.max(s.leave, m - SELF_TRAIL_MIN), m) });
  }
  const waiting = data.riders.filter((r) => r[2] == null || r[2] > m);
  const picked = data.riders.filter((r) => r[2] != null && r[2] <= m);
  const vehicles = prep.vehicles.map((v) => {
    let load = 0;
    for (const [t, n] of v.loads) if (t <= m) load = n;
    return { pos: at(v.path, m), trail: slice(v.path, Math.max(v.path[0][2], m - TRAIL_MIN), m), load, neighbor: v.neighbor };
  });
  const tick = Math.floor(m);
  const layers: Layer[] = [
    new PolygonLayer<{ ring: [number, number][] }>({
      id: `${idPrefix}-fire`,
      data: frame?.ring?.length ? [{ ring: frame.ring }] : [],
      getPolygon: (d) => d.ring,
      getFillColor: [255, 92, 40, 120], // the active band (burning now)
      getLineColor: [255, 170, 70, 255],
      lineWidthMinPixels: 3,
      stroked: true,
      filled: true,
    }),
    new PolygonLayer<{ ring: [number, number][] }>({
      id: `${idPrefix}-scar`,
      data: scar.length ? [{ ring: scar }] : [],
      getPolygon: (d) => d.ring,
      getFillColor: [60, 18, 12, 170], // burned out
      stroked: false,
      filled: true,
    }),
    new ScatterplotLayer<[number, number]>({
      id: `${idPrefix}-parked`,
      data: parked,
      getPosition: (d) => d,
      getRadius: 1.6,
      radiusUnits: "pixels",
      getFillColor: [148, 163, 184, 140],
    }),
    new ScatterplotLayer<[number, number, number | null]>({
      id: `${idPrefix}-stayed`,
      data: [...data.stayed, ...data.unreached],
      getPosition: (d) => [d[0], d[1]],
      getRadius: 1.8,
      radiusUnits: "pixels",
      getFillColor: (d) => (d[2] != null && d[2] <= m ? [120, 20, 20, 220] : [100, 116, 139, 160]),
      updateTriggers: { getFillColor: tick },
    }),
    new PathLayer<{ path: [number, number][] }>({
      id: `${idPrefix}-self`,
      data: movers,
      getPath: (d) => d.path,
      getColor: [52, 211, 153, 170],
      getWidth: 1.5,
      widthUnits: "pixels",
      capRounded: true,
    }),
    new ScatterplotLayer<Evacuation["riders"][number]>({
      id: `${idPrefix}-picked`,
      data: picked,
      getPosition: (d) => [d[0], d[1]],
      getRadius: 2.6,
      radiusUnits: "pixels",
      getFillColor: [148, 163, 184, 120], // picked up: grey and faint (the person is in the vehicle)
    }),
    new ScatterplotLayer<Evacuation["riders"][number]>({
      id: `${idPrefix}-waiting`,
      data: waiting,
      getPosition: (d) => [d[0], d[1]],
      getRadius: 3.2,
      radiusUnits: "pixels",
      getFillColor: (d) => (d[5] != null && d[5] <= m ? [127, 29, 29, 255] : [244, 63, 94, 235]),
      getLineColor: [255, 255, 255, 160],
      lineWidthMinPixels: 0.5,
      stroked: true,
      updateTriggers: { getFillColor: tick },
    }),
    new PathLayer<(typeof vehicles)[number]>({
      id: `${idPrefix}-vehicle-trails`,
      data: vehicles,
      getPath: (d) => d.trail,
      getColor: (d) => (d.neighbor ? [251, 146, 60, 230] : [241, 245, 249, 230]),
      getWidth: 3,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
    }),
    new ScatterplotLayer<(typeof vehicles)[number]>({
      id: `${idPrefix}-vehicles`,
      data: vehicles,
      getPosition: (d) => d.pos,
      getRadius: (d) => (d.load > 0 ? 5.5 : 4),
      radiusUnits: "pixels",
      getFillColor: (d) => (d.neighbor ? [251, 146, 60, 255] : [241, 245, 249, 255]),
      getLineColor: [15, 23, 42, 255],
      lineWidthMinPixels: 1.5,
      stroked: true,
    }),
  ];
  if (labels)
    layers.push(
      new TextLayer<(typeof vehicles)[number]>({
        id: `${idPrefix}-loads`,
        data: vehicles.filter((v) => v.load > 0),
        getPosition: (d) => d.pos,
        getText: (d) => String(d.load),
        getSize: 11,
        getColor: [255, 255, 255, 255],
        getPixelOffset: [10, -10],
        fontWeight: 700,
        outlineWidth: 2,
        outlineColor: [15, 23, 42, 255],
        fontSettings: { sdf: true },
      }),
    );
  return layers;
}
