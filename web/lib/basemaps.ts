"use client";

/**
 * Base map choices shared by the console map and the Try-it house picker. All free, no API key.
 *   map       the original OpenFreeMap style (positron / dark by theme)
 *   terrain   RideOut's recolored style + hillshade (console) / shaded relief under the drawing (picker)
 *   topo      Esri World Topographic Map (contours, trails, land cover)
 *   satellite Esri World Imagery with place-name and road reference layers on top
 * The choice is remembered per browser and per screen.
 */
import { useCallback, useEffect, useState } from "react";

export type Basemap = "map" | "terrain" | "topo" | "satellite";

export const BASEMAPS: { id: Basemap; label: string }[] = [
  { id: "map", label: "Map" },
  { id: "terrain", label: "Terrain" },
  { id: "topo", label: "Topo" },
  { id: "satellite", label: "Satellite" },
];

const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services";

/** XYZ raster layers, bottom to top. `{z}/{y}/{x}` order is Esri's. */
export type RasterLayer = { url: string; maxzoom: number; opacity?: number };
export const RASTER: Partial<Record<Basemap, { layers: RasterLayer[]; attribution: string }>> = {
  satellite: {
    layers: [
      { url: `${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, maxzoom: 19 },
      { url: `${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}`, maxzoom: 19, opacity: 0.85 },
      { url: `${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, maxzoom: 19 },
    ],
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community",
  },
  topo: {
    layers: [{ url: `${ESRI}/World_Topo_Map/MapServer/tile/{z}/{y}/{x}`, maxzoom: 19 }],
    attribution: "© Esri, HERE, Garmin, USGS, NGA, EPA, USDA, NPS",
  },
};

/** Shaded relief only (picker "terrain": drawn under our own canyon drawing). */
export const RELIEF: { layers: RasterLayer[]; attribution: string } = {
  layers: [{ url: `${ESRI}/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}`, maxzoom: 13 }],
  attribution: "Relief © Esri, USGS",
};

export const tileUrl = (url: string, z: number, x: number, y: number) =>
  url.replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));

/** Remembered base map choice for one screen ("console", "picker"). */
export function useBasemap(screen: string, fallback: Basemap = "map"): [Basemap, (b: Basemap) => void] {
  const key = `rideout.basemap.${screen}`;
  const [value, setValue] = useState<Basemap>(fallback);
  useEffect(() => {
    try {
      const v = localStorage.getItem(key);
      if (v && BASEMAPS.some((b) => b.id === v)) setValue(v as Basemap);
    } catch {
      /* storage blocked: keep the default */
    }
  }, [key]);
  const set = useCallback(
    (b: Basemap) => {
      setValue(b);
      try {
        localStorage.setItem(key, b);
      } catch {
        /* storage blocked: choice lasts this visit */
      }
    },
    [key],
  );
  return [value, set];
}
