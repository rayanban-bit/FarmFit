import { describe, expect, it } from "vitest";
import * as turf from "@turf/turf";
import type { MultiPolygon, Polygon } from "geojson";
import { layoutPlot, selectedAreaM2, type BlockSpec } from "./layout";

const R = 6_371_008.8;
/** Build a lon/lat polygon from local metre offsets (illustrative, same construction as the demo parcels). */
function poly(lon0: number, lat0: number, pts: [number, number][]): Polygon {
  const ring = pts.map(([x, y]) => [lon0 + ((x / (R * Math.cos((lat0 * Math.PI) / 180))) * 180) / Math.PI, lat0 + ((y / R) * 180) / Math.PI]);
  ring.push(ring[0]);
  return { type: "Polygon", coordinates: [ring] };
}

const RECT = poly(51.4, 25.43, [[0, 0], [110, -6], [135, 45], [60, 90], [-8, 55]]);
const L = poly(51.5, 25.7, [[0, 0], [160, 0], [160, 45], [60, 45], [60, 120], [0, 120]]);

const A = (g: Polygon | MultiPolygon) => turf.area(g);
const blocksFor = (g: Polygon, shares: number[], access = 0.08): { blocks: BlockSpec[]; access: number } => {
  const total = A(g);
  const usable = total * (1 - access);
  const techs = ["greenhouse", "hydroponic_greenhouse", "open_field", "vertical_hydroponics"];
  const crops = ["tomato", "lettuce", "cucumber", "lettuce"];
  return {
    access: total * access,
    blocks: shares.map((s, i) => ({ id: `b${i}`, label: `${crops[i]} ${techs[i]}`, crop: crops[i], technique: techs[i], areaM2: usable * s })),
  };
};

describe("selected-area calculation", () => {
  it("matches the spherical area of a 0.001 x 0.001 degree cell", () => {
    const g: Polygon = { type: "Polygon", coordinates: [[[51.4, 25.3], [51.401, 25.3], [51.401, 25.301], [51.4, 25.301], [51.4, 25.3]]] };
    const expected = 111_195 * 0.001 * 111_195 * 0.001 * Math.cos((25.3005 * Math.PI) / 180);
    expect(selectedAreaM2([{ geometry: g }])).toBeCloseTo(expected, -2);
  });
  it("sums several plots", () => {
    const s = selectedAreaM2([{ geometry: RECT }, { geometry: L }]);
    expect(s).toBeCloseTo(A(RECT) + A(L), 6);
  });
});

for (const [name, plot, shares] of [
  ["irregular pentagon", RECT, [0.3, 0.2, 0.25]],
  ["concave L-shaped plot", L, [0.35, 0.15, 0.3, 0.1]],
] as const) {
  describe(`layout: ${name}`, () => {
    const { blocks, access } = blocksFor(plot, [...shares]);
    const res = layoutPlot(plot, blocks, access);
    const total = A(plot);

    it("conserves total area (blocks + access + reserve = plot)", () => {
      const sum = res.pieces.reduce((s, p) => s + A(p.geometry), 0);
      expect(Math.abs(sum - total) / total).toBeLessThan(2e-4);
    });

    it("preserves every requested block area", () => {
      for (const b of blocks) {
        const p = res.pieces.find((x) => x.id === b.id)!;
        expect(Math.abs(A(p.geometry) - b.areaM2) / b.areaM2).toBeLessThan(2e-4);
      }
      const acc = res.pieces.find((p) => p.kind === "access")!;
      expect(Math.abs(A(acc.geometry) - access) / access).toBeLessThan(2e-4);
    });

    it("has no overlapping production zones", () => {
      for (let i = 0; i < res.pieces.length; i++) for (let j = i + 1; j < res.pieces.length; j++) {
        const inter = turf.intersect(turf.featureCollection([turf.feature(res.pieces[i].geometry), turf.feature(res.pieces[j].geometry)]));
        expect(inter ? A(inter.geometry as Polygon) : 0).toBeLessThan(0.5); // < 0.5 m2 numerical slack
      }
    });

    it("keeps every polygon inside the plot boundary", () => {
      for (const p of res.pieces) {
        const outside = turf.difference(turf.featureCollection([turf.feature(p.geometry), turf.feature(plot)]));
        expect(outside ? A(outside.geometry as Polygon) : 0).toBeLessThan(0.5);
      }
    });

    it("is deterministic and reproducible", () => {
      const again = layoutPlot(plot, blocks, access);
      expect(JSON.stringify(again.pieces.map((p) => p.geometry))).toBe(JSON.stringify(res.pieces.map((p) => p.geometry)));
    });

    it("labels every production block with crop + technique and never drops one", () => {
      const ids = res.pieces.filter((p) => p.kind === "block").map((p) => p.id).sort();
      expect(ids).toEqual(blocks.map((b) => b.id).sort());
      for (const p of res.pieces.filter((x) => x.kind === "block")) {
        expect(p.crop).toBeTruthy();
        expect(p.technique).toBeTruthy();
      }
    });
  });
}

describe("layout edge cases", () => {
  it("returns access + reserve only when there is no allocation", () => {
    const res = layoutPlot(RECT, [], A(RECT) * 0.08);
    expect(res.pieces.map((p) => p.kind)).toEqual(["access", "reserve"]);
  });
  it("scales down over-allocated requests instead of overflowing the plot", () => {
    const total = A(RECT);
    const res = layoutPlot(RECT, [{ id: "x", label: "x", crop: "tomato", technique: "greenhouse", areaM2: total * 2 }], 0);
    const sum = res.pieces.reduce((s, p) => s + A(p.geometry), 0);
    expect(sum).toBeLessThanOrEqual(total * 1.0005);
  });
});
