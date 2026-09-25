"use client";

import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import * as turf from "@turf/turf";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { ParcelFC } from "@/lib/types";
import { ACCESS_COLOR, RESERVE_COLOR, TECH_COLOR, n0 } from "@/lib/format";
import type { LayoutPiece } from "@/lib/layout";

export interface MapPiece extends LayoutPiece {
  plotId: string;
  cropName?: string;
  techniqueName?: string;
}

interface Props {
  parcels: ParcelFC | null;
  selected: string[];
  onToggle: (id: string) => void;
  pieces: MapPiece[] | null; // results layout; null while planning
  fitToken: number; // change to refit
  fitIds: string[] | null; // plots to fit to (null = current selection)
}

maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const QATAR: [number, number, number, number] = [50.7, 24.4, 51.75, 26.25];
const ACCENT = "#1f5c4d";

export default function MapView({ parcels, selected, onToggle, pieces, fitToken, fitIds }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const markers = useRef<maplibregl.Marker[]>([]);
  const pending = useRef<(() => void)[]>([]);
  const whenReady = (fn: () => void) => (ready.current ? fn() : pending.current.push(fn));
  const toggleRef = useRef(onToggle);
  useEffect(() => {
    toggleRef.current = onToggle;
  }, [onToggle]);

  // ---- init
  useEffect(() => {
    if (!el.current || map.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      bounds: QATAR,
      fitBoundsOptions: { padding: 20 },
      attributionControl: { compact: true },
      style: {
        version: 8,
        sources: {
          osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19, attribution: "© OpenStreetMap contributors" },
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#e9e7de" } },
          { id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.9, "raster-contrast": -0.15, "raster-brightness-min": 0.2, "raster-opacity": 0.9 } },
        ],
      },
    });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    m.on("load", () => {
      const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
      m.addSource("parcels", { type: "geojson", data: empty });
      m.addSource("parcel-pts", { type: "geojson", data: empty });
      m.addSource("layout", { type: "geojson", data: empty });
      m.addLayer({ id: "parcel-fill", type: "fill", source: "parcels", paint: { "fill-color": "#6d726c", "fill-opacity": 0.35 } });
      m.addLayer({ id: "parcel-line", type: "line", source: "parcels", paint: { "line-color": "#3c403c", "line-width": 1.2 } });
      m.addLayer({ id: "layout-fill", type: "fill", source: "layout", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.82 } });
      m.addLayer({ id: "layout-line", type: "line", source: "layout", paint: { "line-color": "#fbfaf6", "line-width": 1.4 } });
      m.addLayer({ id: "plot-outline", type: "line", source: "parcels", filter: ["==", ["get", "sel"], 1], paint: { "line-color": "#1b1e1c", "line-width": 2 } });
      m.addLayer({
        id: "parcel-pt", type: "circle", source: "parcel-pts",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 6, 12, 8, 14, 0],
          "circle-color": ["case", ["==", ["get", "sel"], 1], ACCENT, "#ffffff"],
          "circle-stroke-color": ["case", ["==", ["get", "sel"], 1], "#ffffff", "#3c403c"],
          "circle-stroke-width": 1.6,
          "circle-opacity": ["interpolate", ["linear"], ["zoom"], 13, 1, 14, 0],
          "circle-stroke-opacity": ["interpolate", ["linear"], ["zoom"], 13, 1, 14, 0],
        },
      });
      for (const layer of ["parcel-pt", "parcel-fill"]) {
        m.on("click", layer, (e: maplibregl.MapLayerMouseEvent) => {
          const id = e.features?.[0]?.properties?.id as string | undefined;
          if (id) toggleRef.current(id);
        });
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
      }
      const syncLabels = () => m.getContainer().classList.toggle("map-hide-labels", m.getZoom() < 15.2);
      m.on("zoom", syncLabels);
      syncLabels();
      ready.current = true;
      pending.current.splice(0).forEach((fn) => fn());
    });
    return () => {
      pending.current = [];
      markers.current.forEach((k) => k.remove());
      m.remove();
      map.current = null;
      ready.current = false;
    };
  }, []);

  // ---- data sync (parcels + selection)
  useEffect(() => {
    const m = map.current;
    if (!m || !parcels) return;
    const apply = () => {
      if (map.current !== m || !m.getSource("parcels")) return;
      const sel = new Set(selected);
      const fc: FeatureCollection = {
        type: "FeatureCollection",
        features: parcels.features.map((f) => ({ ...f, properties: { ...f.properties, sel: sel.has(f.properties.id) ? 1 : 0 } })),
      };
      const pts: FeatureCollection = {
        type: "FeatureCollection",
        features: parcels.features.map((f) => {
          const c = turf.centroid(f as Feature<Geometry>);
          return { ...c, properties: { id: f.properties.id, sel: sel.has(f.properties.id) ? 1 : 0 } };
        }),
      };
      (m.getSource("parcels") as maplibregl.GeoJSONSource).setData(fc);
      (m.getSource("parcel-pts") as maplibregl.GeoJSONSource).setData(pts);
      m.setPaintProperty("parcel-fill", "fill-color", ["case", ["==", ["get", "sel"], 1], ACCENT, "#6d726c"]);
      m.setPaintProperty("parcel-fill", "fill-opacity", pieces ? ["case", ["==", ["get", "sel"], 1], 0.0, 0.12] : ["case", ["==", ["get", "sel"], 1], 0.5, 0.3]);
    };
    whenReady(apply);
  }, [parcels, selected, pieces]);

  // ---- results layout
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      if (map.current !== m || !m.getSource("layout")) return;
      const fc: FeatureCollection = {
        type: "FeatureCollection",
        features: (pieces ?? []).map((p) => ({
          type: "Feature",
          geometry: p.geometry,
          properties: {
            color: p.kind === "access" ? ACCESS_COLOR : p.kind === "reserve" ? RESERVE_COLOR : TECH_COLOR[p.technique ?? ""] ?? "#555",
            label: p.label,
          },
        })),
      };
      (m.getSource("layout") as maplibregl.GeoJSONSource).setData(fc);
      markers.current.forEach((k) => k.remove());
      markers.current = [];
      for (const p of pieces ?? []) {
        if (p.kind === "reserve" && p.areaM2 < 30) continue;
        const f = turf.feature(p.geometry);
        const cen = turf.centroid(f);
        const c = (turf.booleanPointInPolygon(cen, f) ? cen : turf.pointOnFeature(f)).geometry.coordinates as [number, number];
        const div = document.createElement("div");
        div.className = `map-label${p.areaM2 < 400 || p.kind !== "block" ? " small" : ""}`;
        const title = p.kind === "block" ? `${p.cropName ?? p.crop} · ${p.techniqueName ?? p.technique}` : p.kind === "access" ? "Access" : "Unallocated";
        div.innerHTML = `<b>${title}</b><div class="sub">${n0(p.areaM2)} m²</div>`;
        markers.current.push(new maplibregl.Marker({ element: div }).setLngLat(c).addTo(m));
      }
    };
    whenReady(apply);
  }, [pieces]);

  // ---- fit
  useEffect(() => {
    const m = map.current;
    if (!m || !parcels || fitToken === 0) return;
    const feats = parcels.features.filter((f) => (fitIds ?? selected).includes(f.properties.id));
    if (!feats.length) return;
    const bb = turf.bbox(turf.featureCollection(feats as Feature<Geometry>[]));
    m.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 90, maxZoom: 17.4, duration: 700 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitToken]);

  return <div ref={el} className="h-full w-full" />;
}

export function Legend({ techniques, show }: { techniques: { id: string; name: string }[]; show: boolean }) {
  if (!show) return null;
  return (
    <div className="absolute bottom-7 left-3 border border-[var(--line-strong)] bg-[var(--panel)] px-3 py-2 text-[11.5px]">
      <div className="eyebrow mb-1">Layout key</div>
      {techniques.map((t) => (
        <div key={t.id} className="flex items-center gap-2">
          <span className="inline-block h-2.5 w-2.5" style={{ background: TECH_COLOR[t.id] }} />
          {t.name}
        </div>
      ))}
      <div className="flex items-center gap-2"><span className="inline-block h-2.5 w-2.5" style={{ background: ACCESS_COLOR }} />Access / infrastructure</div>
      <div className="flex items-center gap-2"><span className="inline-block h-2.5 w-2.5" style={{ background: RESERVE_COLOR }} />Unallocated</div>
      <div className="mt-1.5 max-w-[210px] text-[10.5px] leading-snug text-[var(--muted)]">
        Areas come from the optimizer. Geometry is a feasible blueprint, not a spatially optimised design.
      </div>
    </div>
  );
}
