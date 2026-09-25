import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";

export type SourceType =
  | "official_dataset"
  | "scientific_model"
  | "open_dataset"
  | "user_supplied"
  | "prototype_assumption";

export interface Leaf<T = number> {
  value: T | null;
  unit: string;
  src: string;
}

export interface SourceRec {
  name: string;
  url: string;
  type: SourceType;
  status: string;
  retrieved: string;
  note: string;
}

export interface CropDef {
  name: string;
  price_qar_kg: Leaf;
  cycle_days: Leaf;
  aquacrop: { supported: boolean; crop?: string };
  yields: Record<string, (Leaf & { dynamic?: string; max_cycles: number }) | null>;
}

export interface TechDef {
  name: string;
  model_class: "aquacrop_or_statistical" | "empirical";
  soil_based: boolean;
  compatible_crops: string[];
  capex_qar_m2: Leaf;
  fixed_capex_qar: Leaf;
  opex_qar_m2_year: Leaf;
  energy_kwh_m2_year: Leaf;
  water_coefficient: Leaf;
  min_area_m2: Leaf;
  requires: string[];
}

export interface Catalog {
  crops: Record<string, CropDef>;
  techniques: Record<string, TechDef>;
  groups: Record<string, { name: string; fixed_capex_qar: Leaf; fixed_opex_qar_year: Leaf }>;
  scenarios: Record<string, { name: string; description: string; water_factor: number; electricity_price_factor: number }>;
  defaults: Record<string, Leaf>;
  sources: Record<string, SourceRec>;
  types: Record<SourceType, string>;
  problems: string[];
}

export type Geo = Polygon | MultiPolygon;
export type ParcelFC = FeatureCollection<Geo, { id: string; name: string; district?: string; area_m2: number; source?: string; data_status?: string }>;
export type ParcelFeature = Feature<Geo, ParcelFC["features"][number]["properties"]>;

export interface Constraints {
  budget_qar: number;
  water_m3_year: number;
  energy_kwh_year: number;
  soil_ec_ds_m: number | null;
  access_fraction: number;
  min_land_utilisation: number;
  monthly_peak_factor: number;
  min_block_m2: number;
  max_crop_share: number;
  objective: "roi" | "net_profit";
  horizon_years: number;
}

export interface OptimizeRequest {
  plots: { id: string; name?: string; geometry: Geo; source?: string }[];
  crops: string[];
  techniques: string[];
  constraints: Constraints;
  prices: Record<string, number>;
  electricity_qar_kwh?: number | null;
  water_qar_m3?: number | null;
  scenario: string;
  overrides: Record<string, unknown>;
}

export interface Summary {
  revenue: number;
  opex: number;
  profit: number;
  capex: number;
  water_m3: number;
  energy_kwh: number;
  horizon_years: number;
  roi: number | null;
  payback_years: number | null;
  net_gain: number;
  cash_flows: number[];
  cumulative_cash_flow: number[];
  area_m2: number;
  yield_kg: number;
}

export interface PortfolioRow {
  plot_id: string;
  plot_name: string;
  crop: string;
  crop_name: string;
  technique: string;
  technique_name: string;
  area_m2: number;
  share_of_plot_usable: number;
  share_of_total_usable: number;
  yield_kg_year: number;
  yield_kg_m2_year: number;
  cycles_per_year: number;
  price_qar_kg: number;
  revenue: number;
  opex_variable: number;
  water_m3_year: number;
  energy_kwh_year: number;
  yield_source: "aquacrop" | "official" | "parameter";
  yield_note: string;
  salinity_factor: number;
  water_method: string;
}

export interface PlotResult {
  plot_id: string;
  name: string;
  area_m2: number;
  usable_m2: number;
  access_m2: number;
  allocated_m2: number;
  unallocated_m2: number;
  builds: string[];
  infrastructure: { group: string; name: string; fixed_capex: number; used_by: string[]; capex_saved_by_sharing: number }[];
  centroid: [number, number];
  geometry_source: string;
}

export interface BaselineOut {
  crop: string;
  crop_name: string;
  technique: string;
  technique_name: string;
  scale_of_usable_area: number;
  summary: Summary;
  definition: string;
  allocation: { plot_id: string; area_m2: number }[];
}

export interface ComparisonRow {
  metric: string;
  label: string;
  unit: string;
  optimized: number | null;
  baseline: number | null;
  delta: number | null;
  better: "high" | "low";
}

export interface DataRow {
  key: string;
  label: string;
  value: unknown;
  unit: string;
  source: string;
  url: string;
  date: string;
  type: SourceType;
  type_label: string;
  status: string;
  note: string;
}

export interface Explanation {
  kind: string;
  text: string;
  evidence: Record<string, unknown>;
}

export interface IterationRec {
  k: number;
  lambda: number;
  net_gain: number;
  capex: number;
  F: number;
  mip_status: string;
  mip_ms: number;
}

export interface OptimizeResult {
  scenario: { id: string; name: string; description: string; water_factor: number; electricity_price_factor: number };
  status: string;
  objective: "roi" | "net_profit";
  solver: { backend: string; method: string; iterations: IterationRec[]; n_binary: number; n_vars: number; n_constraints: number; wall_ms: number; utilisation_floor_requested: number; utilisation_floor_used: number };
  summary: Summary;
  portfolio: PortfolioRow[];
  plots: PlotResult[];
  baseline: BaselineOut | null;
  comparison: ComparisonRow[] | null;
  baseline_free: BaselineOut | null;
  comparison_free: ComparisonRow[] | null;
  monthly: { months: string[]; water_m3: number[]; energy_kwh: number[]; water_cap_m3: number | null; energy_cap_kwh: number | null };
  limits: { budget_qar: number; water_m3_year: number; energy_kwh_year: number; usable_m2: number; total_m2: number };
  options: { plot_id: string; crop: string; technique: string; marginal_roi: number | null; profit_m2_year: number }[];
  excluded: { plot: string; crop: string; technique: string; reason: string }[];
  warnings: string[];
  explanations: Explanation[];
  data_panel: DataRow[];
  timing_ms: number;
}

export type StreamEvent =
  | { event: "stage"; name: string; message: string }
  | ({ event: "iteration" } & { k: number; lambda: number; net_gain: number; capex: number; F: number; mip_status: string; mip_ms: number })
  | { event: "result"; data: OptimizeResult }
  | { event: "error"; message: string };
