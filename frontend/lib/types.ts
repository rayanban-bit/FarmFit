import type { Feature, FeatureCollection, MultiPolygon, Polygon } from "geojson";

export type SourceType =
  | "official_qatar"
  | "official_dataset"
  | "scientific_model"
  | "peer_reviewed"
  | "open_dataset"
  | "vendor_data"
  | "user_supplied"
  | "unverified";

export type InputTier = "essential" | "advanced";

export interface MissingInput {
  kind: "crops" | "techniques" | "infrastructure" | "defaults" | "yields";
  owner: string;
  field: string;
  label: string;
  unit: string;
  has_profile_value: boolean;
  profile_value: number | null;
  tier: InputTier;
  note: string;
}

/** A fact FarmFit determined by itself from the selected plots. */
export type FactState = "verified" | "estimate" | "unavailable";

export interface SiteFact {
  key: string;
  label: string;
  value: string | number | null;
  unit: string;
  state: FactState;
  source: string;
  url: string;
  date: string;
  note: string;
}

export interface SiteYield {
  crop: string;
  crop_name: string;
  technique: string;
  technique_name: string;
  state: FactState;
  value: number | null;
  unit: string;
  source: string;
  url: string;
  date: string;
  note: string;
}

export interface SiteSummary {
  plots: { plot_id: string; name: string; area_m2: number; registered_area_m2: number | null; centroid: [number, number]; geometry_source: string; facts: SiteFact[] }[];
  yields: SiteYield[];
  total_area_m2: number;
}

export interface Leaf<T = number> {
  value: T | null;
  unit: string;
  src: string;
  required_input?: boolean;
  label?: string;
  profile_value?: number | null;
  profile_note?: string;
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
  priority: number;
  evidence: string;
  seedlings_qar_m2_cycle: Leaf;
  nutrients_qar_m2_cycle: Leaf;
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
  opex_components: Record<string, Leaf>;
  no_profile_reason?: string;
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
export interface ParcelProps {
  id: string;
  name: string;
  plot_pin: number | null;
  object_id: number | null;
  area_m2: number;
  registered_area_m2: number | null;
  geodesic_area_m2: number;
  centroid: [number, number];
  data_status: string;
  PD_NO?: string | null;
  REF_NUMBER?: string | null;
  [k: string]: unknown;
}
export type ParcelFC = FeatureCollection<Geo, ParcelProps>;
export type ParcelFeature = Feature<Geo, ParcelFC["features"][number]["properties"]>;

export interface Constraints {
  budget_qar: number;
  water_m3_year: number;
  energy_kwh_year: number;
  soil_ec_ds_m: number | null;
  access_fraction: number;
  min_land_utilisation: number;
  water_peak_m3_month: number | null;
  energy_peak_kwh_month: number | null;
  min_block_m2: number;
  max_crop_share: number;
  objective: "roi" | "net_profit";
  horizon_years: number;
}

export interface OptimizeRequest {
  plots: { id: string; name?: string; geometry: Geo; source?: string; registered_area_m2?: number | null }[];
  crops: string[];
  techniques: string[];
  constraints: Constraints;
  prices: Record<string, number>;
  electricity_qar_kwh?: number | null;
  water_qar_m3?: number | null;
  scenario: string;
  overrides: Record<string, unknown>;
  accept_planning_profile: boolean;
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
  registered_area_m2: number | null;
  geodesic_area_m2: number;
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
  solver: { backend: string; method: string; iterations: IterationRec[]; n_binary: number; n_vars: number; n_constraints: number; wall_ms: number; utilisation_floor_requested: number; utilisation_floor_used: number; ratio_outcome: string };
  summary: Summary;
  portfolio: PortfolioRow[];
  plots: PlotResult[];
  baseline: BaselineOut | null;
  comparison: ComparisonRow[] | null;
  baseline_free: BaselineOut | null;
  comparison_free: ComparisonRow[] | null;
  monthly: { months: string[]; water_m3: number[]; energy_kwh: number[]; water_cap_m3: number | null; energy_cap_kwh: number | null };
  limits: { budget_qar: number; water_m3_year: number; energy_kwh_year: number; usable_m2: number; total_m2: number; water_peak_m3_month: number | null; energy_peak_kwh_month: number | null };
  limiting: {
    usable_m2: number;
    allocated_m2: number;
    unallocated_m2: number;
    unallocated_share: number;
    limiting_factor: string | null;
    headline: string;
    land_supported_m2: number | null;
    limits: { key: string; label: string; used: number; limit: number | null; utilisation: number | null; land_supported_m2: number | null; binding: boolean; note: string }[];
  };
  options: { plot_id: string; crop: string; technique: string; marginal_roi: number | null; profit_m2_year: number }[];
  excluded: { plot: string; crop: string; technique: string; reason: string; kind?: string; missing?: { label: string; unit: string }[] }[];
  missing_inputs: MissingInput[];
  accepted_planning_profile: boolean;
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

/** Where the map opens: the best agricultural cluster found in the live cadastre. */
export interface ExplorationArea {
  bbox: [number, number, number, number];
  centre: [number, number];
  window: string;
  label: string;
  plot_count: number;
  min_area_m2: number;
  max_area_m2: number;
  median_area_m2: number;
  radius_m: number;
  score: number;
  reasons: string[];
  criteria: Record<string, number>;
  criteria_used: string[];
  criteria_uninformative: string[];
  weights: Record<string, number>;
  windows_searched: { window: string; plots_found: number; candidate_clusters: number; status?: string; error?: string }[];
  runners_up: { window: string; centre: [number, number]; plots: number; score: number }[];
  method: string;
  status: string;
  retrieved_at?: string;
}
