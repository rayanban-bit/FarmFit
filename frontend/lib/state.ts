import type { Catalog, MissingInput, OptimizeRequest, ParcelFC } from "./types";

/** overrides[kind][ownerId][field] = number. kind: crops | techniques | infrastructure | defaults | yields */
export type Overrides = Record<string, Record<string, Record<string, number>>>;

export interface PlanState {
  selected: string[];
  crops: string[];
  techniques: string[];
  budget: number;
  water: number;
  energy: number;
  ec: string;
  access: number;
  floor: number;
  waterPeak: string;
  energyPeak: string;
  objective: "roi" | "net_profit";
  /** raw text per required input, keyed "kind|owner|field" so empty string means "still unresolved" */
  inputs: Record<string, string>;
  acceptProfile: boolean;
  minPlotArea: number;
}

export const inputKey = (m: { kind: string; owner: string; field: string }) => `${m.kind}|${m.owner}|${m.field}`;

export function initialState(cat: Catalog): PlanState {
  const d = cat.defaults;
  return {
    selected: [],
    crops: Object.keys(cat.crops),
    techniques: Object.keys(cat.techniques),
    budget: d.budget_qar.value ?? 1_200_000,
    water: d.water_m3_year.value ?? 16_000,
    energy: d.energy_kwh_year.value ?? 400_000,
    ec: "",
    access: d.access_fraction.value ?? 0.08,
    floor: d.min_land_utilisation.value ?? 0.8,
    waterPeak: "",
    energyPeak: "",
    objective: "roi",
    inputs: {},
    acceptProfile: true,
    minPlotArea: 2000,
  };
}

const num = (s: string | undefined): number | null => {
  if (s == null || s.trim() === "") return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : null;
};

/** Turn the flat input map into the nested overrides the API expects. */
export function buildOverrides(s: PlanState): Overrides {
  const ov: Overrides = {};
  for (const [k, raw] of Object.entries(s.inputs)) {
    const v = num(raw);
    if (v == null) continue;
    const [kind, owner, field] = k.split("|");
    ((ov[kind] ??= {})[owner] ??= {})[field] = v;
  }
  return ov;
}

/** Required inputs the user has NOT resolved, given the current typed values and profile choice. */
export function unresolved(missing: MissingInput[], s: PlanState): MissingInput[] {
  return missing.filter((m) => {
    if (num(s.inputs[inputKey(m)]) != null) return false;
    return !(s.acceptProfile && m.has_profile_value);
  });
}

export function buildRequest(s: PlanState, parcels: ParcelFC, scenario: string): OptimizeRequest {
  const plots = parcels.features
    .filter((f) => s.selected.includes(f.properties.id))
    .map((f) => ({
      id: f.properties.id,
      name: f.properties.name,
      geometry: f.geometry,
      source: f.properties.data_status,
      registered_area_m2: f.properties.registered_area_m2,
    }));
  const ov = buildOverrides(s);
  // crop prices live in the same required-input map; the API also accepts them as `prices`
  const prices: Record<string, number> = {};
  for (const [cid, fields] of Object.entries(ov.crops ?? {})) {
    if (typeof fields.price_qar_kg === "number") prices[cid] = fields.price_qar_kg;
  }
  return {
    plots,
    crops: s.crops,
    techniques: s.techniques,
    constraints: {
      budget_qar: s.budget,
      water_m3_year: s.water,
      energy_kwh_year: s.energy,
      soil_ec_ds_m: num(s.ec),
      access_fraction: s.access,
      min_land_utilisation: s.floor,
      water_peak_m3_month: num(s.waterPeak),
      energy_peak_kwh_month: num(s.energyPeak),
      min_block_m2: 100,
      max_crop_share: 1,
      objective: s.objective,
      horizon_years: 5,
    },
    prices,
    electricity_qar_kwh: num(s.inputs["defaults|defaults|electricity_qar_kwh"]),
    water_qar_m3: num(s.inputs["defaults|defaults|water_qar_m3"]),
    scenario,
    overrides: ov,
    accept_planning_profile: s.acceptProfile,
  };
}
