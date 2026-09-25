"use client";

import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import * as turf from "@turf/turf";
import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { ParcelFC } from "@/lib/types";
import { ACCESS_COLOR, RESERVE_COLOR, TECH_COLOR, n0 } from "@/lib/format";
import type { LayoutPiece } from "@/lib/layout";

maplibregl.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

export interface MapPiece extends LayoutPiece {
  plotId: string;
  cropName?: string;
  techniqueName?: string;
}

interface Props {
  parcels: ParcelFC | null;
  selected: string[];
  onToggle: (id: string) => void;
  /** Called (debounced) when the view settles, so the page can fetch live cadastral plots for it. */
  onViewChange: (bbox: [number, number, number, number], zoom: number) => void;
  pieces: MapPiece[] | null;
  fitToken: number;
  fitIds: string[] | null;
  /** Opening viewport, derived from the live cadastre. */
  initialBounds?: [number, number, number, number] | null;
}

/** Fallback only, used when the live cadastral service cannot be reached to choose an opening view. */
const FALLBACK_BOUNDS: [number, number, number, number] = [51.17, 25.36, 51.27, 25.43];
const ACCENT = "#1f5c4d";
export const MIN_PARCEL_ZOOM = 12.5;

export default function MapView({ parcels, selected, onToggle, onViewChange, pieces, fitToken, fitIds, initialBounds }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const ready = useRef(false);
  const pending = useRef<(() => void)[]>([]);
  const markers = useRef<maplibregl.Marker[]>([]);
  const toggleRef = useRef(onToggle);
  const viewRef = useRef(onViewChange);
  useEffect(() => {
    toggleRef.current = onToggle;
    viewRef.current = onViewChange;
  }, [onToggle, onViewChange]);
  const whenReady = (fn: () => void) => (ready.current ? fn() : pending.current.push(fn));

  useEffect(() => {
    if (!el.current || map.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      bounds: initialBounds ?? FALLBACK_BOUNDS,
      fitBoundsOptions: { padding: 30 },
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
      m.addSource("layout", { type: "geojson", data: empty });
      m.addLayer({
        id: "parcel-fill", type: "fill", source: "parcels",
        paint: { "fill-color": ["case", ["==", ["get", "sel"], 1], ACCENT, "#6d726c"], "fill-opacity": ["case", ["==", ["get", "sel"], 1], 0.45, 0.13] },
      });
      m.addLayer({
        id: "parcel-line", type: "line", source: "parcels",
        paint: { "line-color": ["case", ["==", ["get", "sel"], 1], "#12352c", "#5d625c"], "line-width": ["case", ["==", ["get", "sel"], 1], 2, 0.8] },
      });
      m.addLayer({ id: "layout-fill", type: "fill", source: "layout", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.85 } });
      m.addLayer({ id: "layout-line", type: "line", source: "layout", paint: { "line-color": "#fbfaf6", "line-width": 1.4 } });

      m.on("click", "parcel-fill", (e: maplibregl.MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties?.id as string | undefined;
        if (id) toggleRef.current(id);
      });
      m.on("mouseenter", "parcel-fill", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "parcel-fill", () => (m.getCanvas().style.cursor = ""));

      const syncLabels = () => m.getContainer().classList.toggle("map-hide-labels", m.getZoom() < 15.2);
      m.on("zoom", syncLabels);
      syncLabels();

      let t: ReturnType<typeof setTimeout> | null = null;
      const report = () => {
        if (t) clearTimeout(t);
        t = setTimeout(() => {
          const b = m.getBounds();
          viewRef.current([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], m.getZoom());
        }, 400);
      };
      m.on("moveend", report);
      // The map lives in a flex column, so the container can still be sizing when "load" fires and
      // getBounds()/getZoom() would then describe the wrong view. Re-measure once the map is idle.
      m.resize();
      m.once("idle", () => {
        m.resize();
        report();
      });
      report();

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
  }, [initialBounds]);

  // live parcels + selection
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const apply = () => {
      if (map.current !== m || !m.getSource("parcels")) return;
      const sel = new Set(selected);
      const fc: FeatureCollection = {
        type: "FeatureCollection",
        features: (parcels?.features ?? []).map((f) => ({ ...f, properties: { ...f.properties, sel: sel.has(f.properties.id) ? 1 : 0 } })),
      };
      (m.getSource("parcels") as maplibregl.GeoJSONSource).setData(fc);
      // once a layout is drawn, fade the raw parcel fill so the management blocks read clearly
      m.setPaintProperty("parcel-fill", "fill-opacity", pieces ? ["case", ["==", ["get", "sel"], 1], 0.0, 0.08] : ["case", ["==", ["get", "sel"], 1], 0.45, 0.13]);
    };
    whenReady(apply);
  }, [parcels, selected, pieces]);

  // optimized layout
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
          properties: { color: p.kind === "access" ? ACCESS_COLOR : p.kind === "reserve" ? RESERVE_COLOR : TECH_COLOR[p.technique ?? ""] ?? "#555" },
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

  // fit to selection / focus
  useEffect(() => {
    const m = map.current;
    if (!m || !parcels || fitToken === 0) return;
    const want = fitIds ?? selected;
    const feats = parcels.features.filter((f) => want.includes(f.properties.id));
    if (!feats.length) return;
    const bb = turf.bbox(turf.featureCollection(feats as Feature<Geometry>[]));
    m.fitBounds([[bb[0], bb[1]], [bb[2], bb[3]]], { padding: 90, maxZoom: 17.6, duration: 700 });
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
      <div className="mt-1.5 max-w-[215px] text-[10.5px] leading-snug text-[var(--muted)]">
        Blocks are drawn inside the real cadastral boundary. Areas come from the solver; the arrangement is a feasible blueprint, not a spatially optimised design.
      </div>
    </div>
  );
}
