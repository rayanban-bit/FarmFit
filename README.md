# FarmFit — farm portfolio optimizer for plots in Qatar

FarmFit decides **how the land of one or several plots should be divided between crop × production-technique
blocks** by solving a real mixed-integer optimization problem (OR-Tools, exact Dinkelbach ROI maximisation),
using real climate, soil and Qatar agricultural statistics, and then draws the result as a labelled 2D
management plan on the plot boundary.

Nothing in the result is a score, a rule of thumb or an LLM output. The portfolio percentages are produced by the
solver at runtime — including for the demo.

```
Next.js (MapLibre, Turf) ──►  FastAPI  ──►  adapters (NASA POWER, Qatar Open Data, SoilGrids, OSM)
                                         ──►  FAO-56 ET0 · AquaCrop (open-field tomato)
                                         ──►  crop/technique model ──► OR-Tools MIP + Dinkelbach ──► solution
```

## Quick start (Windows, no API keys)

```powershell
# 1. backend  (Python 3.11-3.13; 3.13 used here)
cd backend
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 2. frontend (Node 20+), second terminal
cd frontend
npm install --legacy-peer-deps
npm run dev            # http://localhost:3000   (or: npm run build && npm start)
```

Tests: `cd backend && .venv\Scripts\python -m pytest` and `cd frontend && npm test`.

The frontend expects the API at `http://127.0.0.1:8000` (override with `NEXT_PUBLIC_API_URL`).
`data/cache/` ships with real API responses, so the demo also works offline; with a network the adapters refresh
them (30-day TTL for Qatar Open Data/OSM, permanent for weather/soil/AquaCrop keys).

## 1. Problem

A landowner in Qatar can grow tomato, cucumber, lettuce, bell pepper or strawberry with open-field,
greenhouse, hydroponic-greenhouse or vertical-hydroponic systems, but has finite land, capital, water and
electricity. Systems differ in capital cost, yield, water and energy use, and *when* in the year they consume
resources. Choosing the best crop or the best technique in isolation ignores that they compete for the same monthly
water/energy limits and can share infrastructure. FarmFit optimises the whole portfolio jointly.

## 2. Product concept

1. **Land** — click one or several plots on the map (area, count and IDs are shown).
2. **Options** — tick the crops and techniques you can actually use.
3. **Constraints** — budget, water, energy, optional soil EC, selling prices; every field carries a provenance badge
   (*User supplied* / *Prototype assumption* / …). Cost and resource assumptions are editable.
4. **Optimize** — real solver progress (pipeline stages and every Dinkelbach MIP solve) streams from the service.

Results: 2D plan on the plot boundary, 5-year ROI, payback, profit, CapEx, OpEx, water, energy, portfolio table,
explanations generated **only from model outputs**, optimized-vs-baseline comparison, a scenario selector
(Normal / Water-constrained / Energy-expensive) that re-runs the *same* optimizer, monthly resource charts, and a
*Data & assumptions* panel (Value | Unit | Source | Date | Type) for every input.

## 3. Architecture

| Path | Role |
|---|---|
| `backend/app/optimizer.py` | MIP model, Dinkelbach loop, independent evaluator / feasibility checker |
| `backend/app/finance.py` | cash flows, ROI, payback |
| `backend/app/crop_model.py` | thermal windows, cycle schedule, monthly water & energy, salinity |
| `backend/app/climate.py` | FAO-56 Penman-Monteith ET0, monthly climatology |
| `backend/app/aquacrop_model.py` | AquaCrop integration + calibration |
| `backend/app/pipeline.py` | data → options → problem → solve → assemble results, data panel |
| `backend/app/baseline.py` | single crop × technique baselines |
| `backend/app/explain.py` | explanation sentences built from solved quantities |
| `backend/app/adapters/` | independent adapters: `nasa_power`, `qatar_open_data`, `soilgrids`, `osm`, `cadastre` (+ `base` cache) |
| `data/*.json` | `crops.json`, `techniques.json`, `infrastructure.json`, `scenarios.json`, `defaults.json`, **`sources.json` (provenance registry)**, `demo_parcels.geojson`, `cache/` |
| `frontend/lib/layout.ts` | deterministic Turf.js layout engine |
| `frontend/components/` | MapLibre view, wizard, results, data panel |

## 4. Data sources (what is live, what is not)

Every numeric leaf in `data/*.json` has a `src` id that resolves in `data/sources.json` (name, URL, retrieval date,
type, status, note). Missing data is shown as **MISSING**, never replaced by an invented value.

| Source | Use | Access | Status in this build |
|---|---|---|---|
| **NASA POWER** daily point API (AG community) | Tmax/Tmin/Tmean, solar radiation, RH, wind, precipitation (2019-2024) | public, no key | **Live.** Query point is snapped to the native MERRA-2 0.5°×0.625° cell centre (no fake precision) and cached. |
| **Qatar Open Data** (data.gov.qa, Opendatasoft API) — *Production Area and Average Yield of Crops* and *Cropped area & production of crops in greenhouses* | open-field and greenhouse yield baselines | public, no key | **Live.** Yield is recomputed as production/area; records disagreeing with the reported yield by >10 % or that are robust outliers are rejected with the reason shown (the 2023 tomato record is a real example). At least 3 usable years are required, otherwise the option is excluded (this removes open-field strawberry: n = 2). |
| **SoilGrids 2.0** via ISRIC **WCS** (REST API is paused and not used) | pH, sand, silt, clay (0–100 cm, depth-weighted) → USDA texture → AquaCrop soil file | public, no key | **Live** (GeoTIFF read with tifffile). SoilGrids has **no salinity layer**; *Measured soil salinity / EC* is a user input and is shown **missing** when blank. |
| **OpenStreetMap / Overpass** | nearest supermarket/market and main road (straight-line distance, informational, © OSM contributors, ODbL) | public, identifying User-Agent, cached | **Live but flaky** (public Overpass often times out; then shown as unavailable). Not an optimizer input. |
| **Qatar cadastral parcels** | plot boundaries | see §15 | **No public parcel service exists** on the Qatar GIS server we could reach → labelled **DEMO geometry**. |
| Prices, CapEx/OpEx, energy, non-Qatar yields, temperature limits, infrastructure costs | economics | — | **Prototype assumptions** (developer estimates, editable, labelled) — see §13. |

Credentials: **none of the integrated sources requires a key**, so no credential prompt was needed.

## 5. AquaCrop's role — and its limits

AquaCrop (FAO; the `aquacrop` Python package 3.1.0) is applied **only where it is applicable and calibrated**:
open-field **tomato**, the only MVP crop that has a crop file shipped with the package. Workflow:

`NASA POWER weather → FAO-56 ET0 → SoilGrids texture class → AquaCrop seasons (planting date from the thermal
window, soil-moisture-triggered irrigation, 5 seasons) → attainable yield + daily irrigation → optimizer`

* AquaCrop's **daily irrigation** series gives tomato's *monthly* water demand (the monthly constraints use it).
* Its uncalibrated yield (≈175 t/ha) describes well-managed attainable yield and is ~3.5× the Qatar statistic
  (≈51 t/ha). We compute **one national calibration factor** *k = Qatar median yield / AquaCrop yield at a fixed
  reference site (Doha-area POWER cell, sandy loam)* and use `k × AquaCrop(plot climate, plot soil)`. The factor and
  both numbers are shown in the data panel. Absolute level: official statistics; climate/soil response: process model.
* **Not** used for greenhouse, hydroponic or vertical systems, nor for cucumber/lettuce/pepper/strawberry (no crop
  files; we do not invent AquaCrop parameters). Those use the explicit **empirical model**
  `yield/m² · cycles + water/m² + energy/m² + CapEx/m² + OpEx/m²` with sourced (Qatar Open Data greenhouse dataset)
  or *Prototype assumption* / *User supplied* parameters. The UI marks each yield's origin (AquaCrop / Official data / Assumption).

## 6–9. Mathematical optimization formulation

Sets: plots *p* (usable area *U_p* = area·(1−access share)), options *o* = (crop *c*, technique *t*) that are
compatible **and** thermally feasible in the plot's climate, months *m*, shared-infrastructure groups *g*.
Per-m² parameters of option *o* on plot *p* (computed by `pipeline.build_options`):
revenue `r`, variable operating cost `k` (technique OpEx + inputs·cycles + water·price + energy·price),
CapEx `κ`, monthly water `w[o,m]` (m³/m²), monthly energy `e[o,m]` (kWh/m²), annual sums `w_o = Σ_m w[o,m]`, `e_o = Σ_m e[o,m]`.

**Decision variables**

| Variable | Type | Meaning |
|---|---|---|
| `area[p,c,t]` | continuous ≥ 0 | m² allocated (**the portfolio**) |
| `z[p,c,t]` | binary | block is used (enforces minimum block area) |
| `build[p,t]` | binary | technique *t* is built on plot *p* (pays its fixed CapEx once) |
| `infra[p,g]` | binary | shared infrastructure *g* built on plot *p* — **paid once** for all techniques requiring it |

**Expressions** (H = 5 years)

```
Profit  P = Σ (r_o − k_o)·area[p,o]  − Σ F^op_t·build[p,t] − Σ F^op_g·infra[p,g]        [QAR/yr]
CapEx   C = Σ κ_o·area[p,o]          + Σ F_t·build[p,t]     + Σ F_g·infra[p,g]          [QAR]
Net     N = H·P − C                  (cumulative undiscounted cash flow; Year 0 = −C, Years 1..H = P)
ROI     = N / C = (H·P − C)/C        (payback = C/P years is a different quantity)
```

**Constraints**

```
land            Σ_o area[p,o] ≤ U_p                                              for each plot
linking         minblock·z ≤ area[p,o] ≤ U_p·z ;   z[p,o] ≤ build[p,t(o)]
minimum scale   Σ_{o∈t} area[p,o] ≥ minarea_t · build[p,t]
shared infra    build[p,t] ≤ infra[p,g]  for every g required by t
budget          C ≤ Budget
water           Σ_{p,o} w[o,m]·area[p,o] ≤ (W_year/12)·peak      for EVERY month m ;   Σ_{p,o} w_o·area ≤ W_year
energy          Σ_{p,o} e[o,m]·area[p,o] ≤ (E_year/12)·peak      for EVERY month m ;   Σ_{p,o} e_o·area ≤ E_year
utilisation     Σ area ≥ u·Σ U_p    (optional planning floor; relaxed with a visible warning when infeasible)
compatibility   incompatible or thermally infeasible (crop, technique) pairs get no variable at all
```

**Objective** — maximise 5-year ROI. Because ROI = N/C is a ratio of linear functions, it is solved exactly with
**Dinkelbach's algorithm** (`optimizer.py`):

```
λ₀ = 0
repeat:  x_k = argmax_x  N(x) − λ_k·C(x)          (one MIP per iteration, solved to optimality, gap 1e-9)
         F_k = N(x_k) − λ_k·C(x_k)
         stop if F_k ≤ tol                          → x_k maximises N/C
         λ_{k+1} = N(x_k)/C(x_k)
```
F(λ) = max_x N − λC is convex, piecewise-linear and decreasing; the loop is Newton's method on F(λ)=0 and terminates
finitely (typically 2–4 solves). A brute-force enumeration test confirms the returned ROI equals the true maximum.
A second objective, **5-year net cash flow** (max N, a single MIP), is selectable in the UI.

**Interactions between farm components** (why this is not a ranking):
* *Shared infrastructure*: water network, climate/cooling plant and nutrient dosing are `infra[p,g]` decisions whose
  fixed cost is charged once per plot, so `CapEx(shared) < Σ CapEx(standalone)`; the saving is reported per plot.
* *Shared limits + crop calendar*: water/energy are constrained **per month**. Open-field crops only occupy the cool
  months (thermal window from NASA POWER), greenhouses a longer window, vertical farms all year, so options with
  different calendars can coexist under a limit that a single crop would exhaust in its season.
* *Portfolio*: multiple plots share one budget/water/energy pool; the solver decides which plot hosts what.

## 10. ROI and cash-flow calculation

`finance.summarise`: revenue = yield × price; profit = revenue − OpEx; cash flows `[−CapEx, P, P, P, P, P]`;
cumulative 5-year cash flow, ROI = net/CapEx, payback = CapEx/P (or "Never"). Revenue, OpEx, CapEx, water, energy,
payback and ROI are all recomputed from the allocation by `optimizer.evaluate` independently of the solver.

## 11. Baselines

Two, both feasible points of the *same* problem (so optimum ≥ baseline is a tested invariant):
1. **Whole plot** — one crop × one technique on every selected plot, using the whole usable area (scaled uniformly by
   the largest factor the constraints allow; the scale is shown).
2. **Best single option** — best one-crop-one-technique farm found by the same MIP (free plots/areas).

## 12. Spatial layout (2D management plan)

`frontend/lib/layout.ts` (Turf.js): the plot polygon is projected to a local metric plane and cut into consecutive
strips perpendicular to a candidate axis (longest plot edges and their perpendiculars). Each strip's cut position is
found by bisection so its intersection with the plot has **exactly** the requested area. Strips are disjoint by
construction, are intersections with the plot (inside the boundary), and sum to the plot area (access strip +
production blocks + explicit "unallocated"). The axis with the fewest disconnected pieces wins; ties break
deterministically → reproducible. **The MIP optimises the portfolio; the layout only converts it into a feasible
blueprint and is *not* claimed to be spatially optimal.**

## 13. Assumptions (be sceptical of these)

Everything labelled *Prototype assumption* is a developer estimate awaiting agronomist/supplier input:
selling prices, CapEx/OpEx, energy per m², water coefficients, cooling effect of greenhouses (8 °C max reduction,
4 °C min increase), infrastructure costs, temperature limits, cycle lengths of strawberry, controlled-environment
yields (hydroponic/vertical/greenhouse lettuce & strawberry), tariffs (0.12 QAR/kWh, 0.6 QAR/m³ — not checked against
Kahramaa). FAO-56 Kc/stage lengths and FAO-29 salinity coefficients were transcribed by the developer and are
flagged `transcribed_verify` in `sources.json`. Qatar's statistical yields are taken as *per crop cycle* on the
cropped area. All of these are editable in the UI; edited values are relabelled *User supplied*.

Demo defaults (budget 1.2 M QAR, 16 000 m³/yr, 400 000 kWh/yr, monthly peak factor 2, utilisation floor 80 %) are
illustrative user inputs, not data.

## 14. Open-source components

OR-Tools (Apache-2.0), the aquacrop Python package (FAO AquaCrop, open source - see its repository for the licence), FastAPI, pandas, numpy, tifffile, httpx,
Next.js, React, Tailwind CSS, MapLibre GL JS, Turf.js, Recharts, vitest, pytest. Map tiles © OpenStreetMap contributors
(ODbL) via the standard tile server at low volume; data from NASA POWER, ISRIC SoilGrids (CC-BY 4.0) and the State of
Qatar Open Data portal under their respective licences.

## 15. Connecting live Qatar GIS data

Investigation (25 Sep 2026): the public server `https://services.gisqatar.org.qa/server/rest/services` answers and
requires **no** authentication, but publishes only `Vector/Landmarks` (MapServer), geocoders, geometry/raster
utilities and a print service — **no cadastral parcel layer**. Other candidate hosts (`geoportal.gisqatar.org.qa/arcgis`,
`gis.psa.gov.qa`, `gisqatar.org.qa/arcgis`) returned 404/502 or no REST directory. No endpoint was invented; the
app therefore uses `data/demo_parcels.geojson` (illustrative polygons in farming districts) and labels it everywhere.
`GET /api/sources/status` re-probes the host.

If you obtain a real parcel layer, set (see `.env.example`):

```
QATAR_PARCEL_QUERY_URL=https://<host>/arcgis/rest/services/<folder>/<service>/FeatureServer/0/query
QATAR_GIS_TOKEN=<only if required>          QATAR_PARCEL_ID_FIELD=PARCEL_ID
```
and request `/api/parcels?bbox=minx,miny,maxx,maxy`; `adapters/cadastre.py` queries it (`f=geojson`), computes areas
and marks the data "Live cadastral service". The live adapter is optional — failure falls back to the labelled demo.

## 16. Limitations

* Demo geometry only; no ownership/legal boundary data.
* Economics are placeholders: absolute ROI/payback values are only as good as those assumptions (with the official
  open-field cucumber yield and placeholder costs, cheap open-field production dominates a pure-ROI ranking).
  **ROI is a ratio, so maximising it can favour a small cheap farm**; the utilisation floor and the *net cash flow*
  objective exist for that reason.
* AquaCrop covers open-field tomato only, with a single national calibration factor and full-irrigation management;
  no deficit-irrigation response curve or salinity module is used (salinity uses the Maas–Hoffman relation on ECe).
* One climate cell (2019–2024 monthly means) per plot; no inter-annual risk, price risk or discounting.
* Land is allocated in space, not time: no rotations or double use of the same m² by different systems in different months.
* The layout is a feasible blueprint, not a spatially optimised design; concave plots can split a block into several pieces.
* Water quality/leaching, labour availability, market absorption and permits are not modelled.
