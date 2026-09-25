import type { Catalog, ExplorationArea, MissingInput, OptimizeRequest, OptimizeResult, ParcelFC, SiteSummary, StreamEvent } from "./types";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const b = await res.json();
      detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const getCatalog = () => fetch(`${API}/api/catalog`).then((r) => j<Catalog & { missing_inputs: MissingInput[] }>(r));

export interface ParcelResponse {
  mode: "live";
  label: string;
  source_url: string;
  status: string;
  retrieved_at?: string;
  truncated: boolean;
  count: number;
  featureCollection: ParcelFC;
}

/** Live Qatar cadastral plots intersecting the current map view. */
export const getParcels = (bbox: [number, number, number, number], minAreaM2 = 0, signal?: AbortSignal) =>
  fetch(`${API}/api/parcels?bbox=${bbox.map((v) => v.toFixed(6)).join(",")}&min_area_m2=${Math.round(minAreaM2)}&limit=400`, { signal }).then((r) =>
    j<ParcelResponse>(r),
  );

export const describeParcelLayer = () =>
  fetch(`${API}/api/parcels/describe`).then((r) =>
    j<{ name: string; geometryType: string; native_wkid: number; capabilities: string; fields: { name: string; type: string }[]; source_url: string; status: string }>(r),
  );

/** What the app can work out by itself from the selected plots, with sources and dates. */
export const getSiteSummary = (plots: OptimizeRequest["plots"], crops: string[], signal?: AbortSignal) =>
  fetch(`${API}/api/site-summary`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plots, crops }), signal }).then((r) =>
    j<SiteSummary>(r),
  );

/** The opening viewport, chosen from live cadastral data rather than a hardcoded coordinate. */
export const getExplorationArea = () => fetch(`${API}/api/exploration-area`).then((r) => j<ExplorationArea>(r));

export const getSourceStatus = () =>
  fetch(`${API}/api/sources/status`).then((r) =>
    j<{ cadastre: Record<string, unknown>; keyless_public_apis: string[]; credentials_required: string[] }>(r),
  );

export const getContext = (lon: number, lat: number) =>
  fetch(`${API}/api/context?lon=${lon}&lat=${lat}`).then((r) =>
    j<{ available: boolean; error?: string; data?: { nearest_market: { name: string; distance_m: number } | null; nearest_main_road: { name: string; distance_m: number } | null; markets_within_radius: number; distance_type: string }; attribution?: string }>(r),
  );

export const compareScenarios = (req: OptimizeRequest) =>
  fetch(`${API}/api/scenarios/compare`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) }).then((r) =>
    j<{ scenarios: Record<string, OptimizeResult> }>(r),
  );

/** NDJSON stream of real pipeline stages and Dinkelbach solver iterations. */
export async function optimizeStream(req: OptimizeRequest, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<OptimizeResult> {
  const res = await fetch(`${API}/api/optimize/stream`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req), signal });
  if (!res.ok || !res.body) throw new Error(`Optimizer service error: ${res.status} ${res.statusText}`);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let result: OptimizeResult | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const ev = JSON.parse(line) as StreamEvent;
      if (ev.event === "error") throw new Error(ev.message);
      if (ev.event === "result") result = ev.data;
      onEvent(ev);
    }
  }
  if (!result) throw new Error("The optimizer finished without returning a result.");
  return result;
}
