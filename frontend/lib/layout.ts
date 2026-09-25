/**
 * Deterministic 2D management layout for one plot.
 *
 * IMPORTANT (scientific honesty): the MIP decides HOW MUCH area each crop x technique block gets. This module
 * only turns those areas into a feasible plan (a "blueprint"): it does NOT optimise the spatial arrangement and
 * makes no claim of spatial optimality (no adjacency, drainage, sun-path or road-network optimisation).
 *
 * Method: the plot polygon is projected to a local metric plane. For a small set of candidate axes (directions of
 * the plot's longest edges and their perpendiculars) the polygon is cut into consecutive strips perpendicular to
 * the axis. The cut position of every strip is found by bisection so that the strip's intersection with the plot has
 * EXACTLY the requested area. Strips are disjoint by construction (no overlaps), are intersections with the plot
 * (so they stay inside the boundary) and their areas sum to the plot area (conservation). The axis that yields the
 * fewest disconnected pieces (then the shortest total perimeter) is kept; ties are broken by the smaller angle,
 * so the result is fully reproducible.
 */
import * as turf from "@turf/turf";
import type { Feature, MultiPolygon, Polygon, Position } from "geojson";
import { TECH_ORDER } from "./format";

export interface BlockSpec {
  id: string;
  label: string;
  crop: string;
  technique: string;
  areaM2: number;
}

export type PieceKind = "block" | "access" | "reserve";

export interface LayoutPiece {
  kind: PieceKind;
  id: string;
  label: string;
  crop?: string;
  technique?: string;
  targetM2: number;
  areaM2: number;
  geometry: Polygon | MultiPolygon;
}

export interface LayoutResult {
  pieces: LayoutPiece[];
  axisDeg: number;
  components: number;
  plotAreaM2: number;
}

type Geo = Polygon | MultiPolygon;
const R = 6_371_008.8;
const RAD = Math.PI / 180;

interface Frame {
  lon0: number;
  lat0: number;
  kx: number; // metres per degree lon
  ky: number; // metres per degree lat
}

function frameFor(g: Geo): Frame {
  const ring = (g.type === "Polygon" ? g.coordinates[0] : g.coordinates[0][0]) as Position[];
  const lon0 = ring.reduce((s, p) => s + p[0], 0) / ring.length;
  const lat0 = ring.reduce((s, p) => s + p[1], 0) / ring.length;
  return { lon0, lat0, kx: R * RAD * Math.cos(lat0 * RAD), ky: R * RAD };
}

const toLocal = (f: Frame, p: Position): Position => [(p[0] - f.lon0) * f.kx, (p[1] - f.lat0) * f.ky];
const fromLocal = (f: Frame, p: Position): Position => [p[0] / f.kx + f.lon0, p[1] / f.ky + f.lat0];

function mapGeo(g: Geo, fn: (p: Position) => Position): Geo {
  if (g.type === "Polygon") return { type: "Polygon", coordinates: g.coordinates.map((r) => r.map(fn)) };
  return { type: "MultiPolygon", coordinates: g.coordinates.map((poly) => poly.map((r) => r.map(fn))) };
}

function ringArea(r: Position[]): number {
  let s = 0;
  for (let i = 0; i < r.length - 1; i++) s += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1];
  return s / 2;
}

/** Planar area (local metres) of a Polygon / MultiPolygon: outer rings minus holes. */
export function planarArea(g: Geo | null): number {
  if (!g) return 0;
  const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  let a = 0;
  for (const poly of polys) {
    a += Math.abs(ringArea(poly[0]));
    for (let i = 1; i < poly.length; i++) a -= Math.abs(ringArea(poly[i]));
  }
  return a;
}

function feat(g: Geo): Feature<Geo> {
  return { type: "Feature", properties: {}, geometry: g };
}

function intersect(a: Geo, b: Geo): Geo | null {
  const r = turf.intersect(turf.featureCollection([feat(a) as Feature<Polygon | MultiPolygon>, feat(b) as Feature<Polygon | MultiPolygon>]));
  return r ? (r.geometry as Geo) : null;
}

function rect(x0: number, x1: number, y0: number, y1: number): Polygon {
  return { type: "Polygon", coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]] };
}

function rotate(g: Geo, theta: number): Geo {
  const c = Math.cos(theta);
  const s = Math.sin(theta);
  return mapGeo(g, (p) => [p[0] * c - p[1] * s, p[0] * s + p[1] * c]);
}

function bbox(g: Geo): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  for (const poly of polys) for (const p of poly[0]) {
    x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); y0 = Math.min(y0, p[1]); y1 = Math.max(y1, p[1]);
  }
  return [x0, y0, x1, y1];
}

function pieceCount(g: Geo): number {
  return g.type === "Polygon" ? 1 : g.coordinates.length;
}

function perimeter(g: Geo): number {
  const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  let l = 0;
  for (const poly of polys) for (const r of poly) for (let i = 0; i < r.length - 1; i++) l += Math.hypot(r[i + 1][0] - r[i][0], r[i + 1][1] - r[i][1]);
  return l;
}

/** Candidate strip directions (radians): longest plot edges and their perpendiculars, de-duplicated, deterministic. */
function candidateAngles(g: Geo): number[] {
  const ring = (g.type === "Polygon" ? g.coordinates[0] : g.coordinates[0][0]) as Position[];
  const edges: { len: number; ang: number }[] = [];
  for (let i = 0; i < ring.length - 1; i++) {
    const dx = ring[i + 1][0] - ring[i][0];
    const dy = ring[i + 1][1] - ring[i][1];
    let ang = Math.atan2(dy, dx) % Math.PI;
    if (ang < 0) ang += Math.PI;
    edges.push({ len: Math.hypot(dx, dy), ang });
  }
  edges.sort((a, b) => b.len - a.len || a.ang - b.ang);
  const out: number[] = [];
  for (const e of edges.slice(0, 4)) {
    for (const a of [e.ang, (e.ang + Math.PI / 2) % Math.PI]) {
      if (!out.some((o) => Math.abs(o - a) < (1 * Math.PI) / 180)) out.push(a);
    }
  }
  return out.sort((a, b) => a - b);
}

/** Cut consecutive strips (left to right in the rotated frame) with exact target areas. */
function sliceStrips(poly: Geo, targets: number[]): Geo[] {
  const [xmin, ymin, xmax, ymax] = bbox(poly);
  const pad = 1;
  const out: Geo[] = [];
  let x0 = xmin - pad;
  const total = planarArea(poly);
  let used = 0;
  for (let i = 0; i < targets.length; i++) {
    const last = i === targets.length - 1;
    let x1: number;
    if (last) {
      x1 = xmax + pad;
    } else {
      const want = targets[i];
      used += want;
      // bisection on cut position so that area(strip) == want (monotone in x1)
      let lo = x0;
      let hi = xmax + pad;
      const areaOf = (x: number) => planarArea(intersect(poly, rect(x0, x, ymin - pad, ymax + pad)));
      const tol = Math.max(1e-7 * total, 1e-9);
      for (let it = 0; it < 90; it++) {
        const mid = (lo + hi) / 2;
        const a = areaOf(mid);
        if (Math.abs(a - want) <= tol) { lo = hi = mid; break; }
        if (a < want) lo = mid; else hi = mid;
      }
      x1 = (lo + hi) / 2;
    }
    const strip = intersect(poly, rect(x0, x1, ymin - pad, ymax + pad));
    out.push(strip ?? ({ type: "Polygon", coordinates: [[[x0, ymin], [x0, ymin], [x0, ymin], [x0, ymin]]] } as Polygon));
    x0 = x1;
  }
  void used;
  return out;
}

const techRank = (t: string) => {
  const i = TECH_ORDER.indexOf(t);
  return i < 0 ? 99 : i;
};

/**
 * Lay out `blocks` inside `plot` (lon/lat polygon). Areas are in m2. `accessM2` is the access/infrastructure strip;
 * whatever remains after access and blocks becomes an explicit "reserve" piece, so the areas always sum to the plot.
 */
export function layoutPlot(plot: Geo, blocks: BlockSpec[], accessM2: number): LayoutResult {
  const frame = frameFor(plot);
  const local = mapGeo(plot, (p) => toLocal(frame, p));
  const plotArea = planarArea(local);

  const ordered = [...blocks].filter((b) => b.areaM2 > 0).sort((a, b) => techRank(a.technique) - techRank(b.technique) || a.crop.localeCompare(b.crop) || a.id.localeCompare(b.id));
  let sumBlocks = ordered.reduce((s, b) => s + b.areaM2, 0);
  const access = Math.max(0, Math.min(accessM2, plotArea));
  // never exceed the plot: scale blocks down proportionally if the request over-allocates (should not happen)
  const room = Math.max(0, plotArea - access);
  const scale = sumBlocks > room && sumBlocks > 0 ? room / sumBlocks : 1;
  const targets: { kind: PieceKind; spec?: BlockSpec; target: number }[] = [];
  if (access > 0) targets.push({ kind: "access", target: access });
  for (const b of ordered) targets.push({ kind: "block", spec: b, target: b.areaM2 * scale });
  sumBlocks *= scale;
  const reserve = Math.max(0, plotArea - access - sumBlocks);
  targets.push({ kind: "reserve", target: reserve });

  const centre = turf.centroid(feat(local)).geometry.coordinates;
  let best: { theta: number; strips: Geo[]; comps: number; per: number } | null = null;
  for (const theta of candidateAngles(local)) {
    const rot = rotate(mapGeo(local, (p) => [p[0] - centre[0], p[1] - centre[1]]), -theta);
    const strips = sliceStrips(rot, targets.map((t) => t.target));
    const comps = strips.reduce((s, g, i) => s + (planarArea(g) > 1e-6 ? pieceCount(g) : 0) * (targets[i].target > 0 ? 1 : 0), 0);
    const per = strips.reduce((s, g) => s + perimeter(g), 0);
    if (!best || comps < best.comps || (comps === best.comps && per < best.per - 1e-9)) best = { theta, strips, comps, per };
  }
  if (!best) throw new Error("plot has no usable edges");

  const pieces: LayoutPiece[] = [];
  best.strips.forEach((g, i) => {
    const t = targets[i];
    if (t.kind === "reserve" && t.target < 1e-6) return;
    const back = mapGeo(rotate(g, best!.theta), (p) => [p[0] + centre[0], p[1] + centre[1]]);
    const geo = mapGeo(back, (p) => fromLocal(frame, p));
    const a = planarArea(back);
    if (t.kind === "access") pieces.push({ kind: "access", id: "access", label: "Access / infrastructure", targetM2: t.target, areaM2: a, geometry: geo });
    else if (t.kind === "reserve") pieces.push({ kind: "reserve", id: "reserve", label: "Unallocated", targetM2: t.target, areaM2: a, geometry: geo });
    else pieces.push({ kind: "block", id: t.spec!.id, label: t.spec!.label, crop: t.spec!.crop, technique: t.spec!.technique, targetM2: t.target, areaM2: a, geometry: geo });
  });
  return { pieces, axisDeg: (best.theta * 180) / Math.PI, components: best.comps, plotAreaM2: plotArea };
}

/** Spherical area (m2) of a plot / selection - the number shown in the UI (matches the backend formula). */
export function selectedAreaM2(features: { geometry: Geo }[]): number {
  return features.reduce((s, f) => s + turf.area(feat(f.geometry)), 0);
}
