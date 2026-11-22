/**
 * RideOut's own basemap look, built on OpenFreeMap's open styles (no API key):
 *   dark  = "night ops": deep navy land, roads as faint blue light, the canyon lit by terrain shading
 *   light = "blueprint": pale paper-blue land, roads and relief drawn in blue ink
 * Every layer of the source style is recolored; shields, one-way arrows and airport icons are hidden so the
 * map stays quiet and our data (riders, vans, fire) is what stands out.
 * Terrain: AWS Terrain Tiles (open data, Terrarium encoding, no key), added by addRelief() only after the
 * basemap has loaded, so a browser that can't shade terrain still gets the full map.
 */
import type { Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import type { Theme } from "@/lib/theme";

type Palette = {
  land: string;
  landuse: string;
  park: string;
  water: string;
  waterline: string;
  building: string;
  roadMinor: string;
  roadMajor: string;
  motorway: string;
  casing: string;
  rail: string;
  boundary: string;
  label: string;
  labelMajor: string;
  halo: string;
  shadow: string;
  highlight: string;
  accent: string;
  relief: number;
};

const PALETTE: Record<Theme, Palette> = {
  dark: {
    land: "#070d1a",
    landuse: "#0a1222",
    park: "#0a1628",
    water: "#08204a",
    waterline: "#1b4d9a",
    building: "#101a31",
    roadMinor: "#1d3157",
    roadMajor: "#2e5aa6",
    motorway: "#4f8ff5",
    casing: "#070d1a",
    rail: "#22325a",
    boundary: "#33436a",
    label: "#7e8db5",
    labelMajor: "#c4d0ee",
    halo: "#070d1a",
    shadow: "#000000",
    highlight: "#5b8be8",
    accent: "#13265a",
    relief: 0.85,
  },
  light: {
    land: "#eef3fa",
    landuse: "#e9eff8",
    park: "#e3ecf6",
    water: "#cfe0f5",
    waterline: "#a3c0e9",
    building: "#dde6f3",
    roadMinor: "#d0dcee",
    roadMajor: "#aec5ea",
    motorway: "#6f97db",
    casing: "#eef3fa",
    rail: "#c6d2e6",
    boundary: "#b6c4dc",
    label: "#6b7c9c",
    labelMajor: "#33466d",
    halo: "#eef3fa",
    shadow: "#3a5590",
    highlight: "#ffffff",
    accent: "#8ea6d2",
    relief: 0.8,
  },
};

const HIDE = /shield|oneway|airport|aeroway-taxiway/;

function fillColor(id: string, c: Palette): string {
  if (/water/.test(id)) return c.water;
  if (/park|wood|landcover/.test(id)) return c.park;
  if (/building/.test(id)) return c.building;
  if (/pier/.test(id)) return c.land;
  return c.landuse;
}

function lineColor(id: string, c: Palette): string {
  if (/water/.test(id)) return c.waterline;
  if (/casing/.test(id)) return c.casing;
  if (/motorway/.test(id)) return c.motorway;
  if (/major/.test(id)) return c.roadMajor;
  if (/rail/.test(id)) return c.rail;
  if (/boundary/.test(id)) return c.boundary;
  return c.roadMinor;
}

const MAJOR_LABEL = /city|town|state|country|place_city/;

/** Recolor an OpenFreeMap style into RideOut's look and add terrain shading under the roads. */
export function rideOutStyle(base: StyleSpecification, theme: Theme): StyleSpecification {
  const c = PALETTE[theme];
  const layers = base.layers.map((layer) => {
    const l = JSON.parse(JSON.stringify(layer)) as Record<string, unknown> & {
      id: string;
      type: string;
      paint?: Record<string, unknown>;
      layout?: Record<string, unknown>;
    };
    const paint = (l.paint ??= {});
    if (HIDE.test(l.id)) l.layout = { ...(l.layout ?? {}), visibility: "none" };
    switch (l.type) {
      case "background":
        paint["background-color"] = c.land;
        break;
      case "fill":
        delete paint["fill-pattern"];
        paint["fill-color"] = fillColor(l.id, c);
        paint["fill-outline-color"] = fillColor(l.id, c);
        break;
      case "line":
        paint["line-color"] = lineColor(l.id, c);
        break;
      case "symbol":
        paint["text-color"] = MAJOR_LABEL.test(l.id) ? c.labelMajor : c.label;
        paint["text-halo-color"] = c.halo;
        paint["text-halo-width"] = 1.4;
        paint["icon-opacity"] = 0.5;
        break;
    }
    return l;
  }) as StyleSpecification["layers"];

  return { ...base, layers };
}

/** Terrain shading under the roads. Call after the map's "load"; any failure leaves the map as it is. */
export function addRelief(map: MapLibreMap, theme: Theme): void {
  const c = PALETTE[theme];
  try {
    if (map.getSource("rideout-terrain")) return;
    map.addSource("rideout-terrain", {
      type: "raster-dem",
      tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
      encoding: "terrarium",
      tileSize: 256,
      maxzoom: 14,
      attribution: "Terrain: Mapzen / AWS Open Data",
    });
    map.addLayer(
      {
        id: "rideout-relief",
        type: "hillshade",
        source: "rideout-terrain",
        paint: {
          "hillshade-exaggeration": c.relief,
          "hillshade-shadow-color": c.shadow,
          "hillshade-highlight-color": c.highlight,
          "hillshade-accent-color": c.accent,
          "hillshade-illumination-direction": 315,
        },
      },
      map.getLayer("water") ? "water" : undefined,
    );
  } catch {
    /* no terrain: the basemap is still complete */
  }
}
