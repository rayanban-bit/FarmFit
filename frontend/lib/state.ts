import type { Catalog, OptimizeRequest, ParcelFC } from "./types";

export interface PlanState {
  selected: string[];
  crops: string[];
  techniques: string[];
  budget: number;
  water: number;
  energy: number;
  ec: string; // "" = unknown
  access: number;
  floor: number;
  peak: number;
  objective: "roi" | "net_profit";
  prices: Record<string, string>; // "" = catalog default
  electricity: string;
  waterPrice: string;
  overrides: Record<string, Record<string, Record<string, number>>>; // techniques|crops|infrastructure -> id -> field -> value
}

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
    peak: d.monthly_peak_factor.value ?? 2,
    objective: "roi",
    prices: {},
    electricity: "",
    waterPrice: "",
    overrides: {},
  };
}

const num = (s: string): number | null => {
  if (s.trim() === "") return null;
  const v = Number(s);
  return Number.isFinite(v) ? v : null;
};

export function buildRequest(s: PlanState, parcels: ParcelFC, scenario: string): OptimizeRequest {
  const plots = parcels.features
    .filter((f) => s.selected.includes(f.properties.id))
    .map((f) => ({ id: f.properties.id, name: f.properties.name, geometry: f.geometry, source: f.properties.source }));
  const prices: Record<string, number> = {};
  for (const [k, v] of Object.entries(s.prices)) {
    const n = num(v);
    if (n != null && n > 0) prices[k] = n;
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
      monthly_peak_factor: s.peak,
      min_block_m2: 100,
      max_crop_share: 1,
      objective: s.objective,
      horizon_years: 5,
    },
    prices,
    electricity_qar_kwh: num(s.electricity),
    water_qar_m3: num(s.waterPrice),
    scenario,
    overrides: s.overrides,
  };
}
