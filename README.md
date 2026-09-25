# FarmFit — farm portfolio optimizer for real cadastral plots in Qatar

FarmFit decides **how the land of one or more real Qatar cadastral plots should be divided between
crop × production-technique blocks**, by solving a genuine mixed-integer optimization problem (OR-Tools,
exact Dinkelbach ROI maximisation) on live government, scientific and open data, and drawing the answer as a
labelled 2D management plan inside the actual plot boundary.

The portfolio percentages come from the solver at run time. There is no demo result, no recommendation score
and no LLM anywhere in the calculation path.

```
Next.js (MapLibre, Turf)
   │
   ▼
FastAPI ──► Qatar cadastral FeatureServer (plot boundaries, registered areas)
        ──► Qatar Open Data (crop yields)     ──► NASA POWER (weather) ──► FAO-56 ET0
        ──► ISRIC SoilGrids WCS (soil)        ──► FAO AquaCrop (open-field tomato)
        ──► crop × technique model  ──►  OR-Tools MIP + Dinkelbach  ──►  portfolio + finance
```

## How the flow works: select land → essentials → recommendations

Selecting cadastral plots determines most of the model by itself. Step 3 shows exactly what was worked out and
from where, then asks only for what a grower alone can know:

| | |
|---|---|
| **Determined automatically** (you never type it) | plot area and location from the cadastre; ET0, temperatures and rainfall from NASA POWER; soil texture and pH from SoilGrids; open-field and greenhouse yields from Qatar Open Data. Each fact shows its **source and retrieval date** and is marked **Verified**. |
| **You provide** | budget, water, electricity, expected selling prices, and optionally a measured soil EC. Five prices, three numbers. |
| **Advanced assumptions** (collapsed) | construction cost, labour, maintenance, energy and water coefficients, infrastructure, tariffs. Pre-filled with clearly labelled **Estimate** values, all editable. |
| **Unavailable** | no parcel-level soil EC exists for Qatar, and vertical-farming costs have no published figure. These are marked **Unavailable**; anything depending on them is excluded from the optimization rather than guessed. |

`GET /api/site-summary` returns those automatic facts with their provenance, so the distinction between
verified, estimated and unavailable is visible before anything is optimised.

## The core principle: refuse rather than invent

Every parameter is either **sourced** or **required from you**. A parameter with no defensible source has
`value: null` and `required_input: true`, and the optimizer **excludes every crop × technique that depends on
it**, naming the exact missing input, instead of quietly substituting a number.

So that the tool is usable without a procurement exercise, the technical assumptions are pre-filled from an
explicit estimate profile, controlled by a checkbox in **Advanced assumptions**. Values it fills are tagged
**Estimate** everywhere they appear, are never described as sourced, and can be replaced field by field. Vertical farming has no such default on purpose —
it needs a real vendor quotation, so it stays excluded until you enter one.

## Quick start (no API keys — none of the integrated sources needs one)

```powershell
cd backend
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# second terminal
cd frontend
npm install --legacy-peer-deps
npm run dev          # http://localhost:3000
```

Tests: `cd backend && .venv\Scripts\python -m pytest` (96) and `cd frontend && npm test` (16).
`data/cache/` ships with real API responses so everything works offline; with a network the adapters refresh it.

## 1. Cadastral map — live, official

| | |
|---|---|
| **Endpoint** | `https://services.gisqatar.org.qa/server/rest/services/Vector/CadastrePlots/FeatureServer/0` |
| **Layer** | حدود الأراضي المساحية المعتمدة (approved cadastral land boundaries) |
| **Auth** | none — public, `Query` capability only |
| **Features** | 254,289 polygons |
| **Native SR** | EPSG:2932 (QND 1995 / Qatar National Grid) |
| **Query** | `/query` with `geometryType=esriGeometryEnvelope`, `inSR=4326`, `spatialRel=esriSpatialRelIntersects`, `outSR=4326`, `f=geojson` |
| **Verified** | 2026-09-25, live |

The server reprojects to WGS84 for us (`outSR=4326`), so no client-side datum maths is involved. Plots load for
the current map view as you pan, are clickable and multi-selectable, and a selection survives panning away.
`PDAREA` — the officially registered area — is treated as authoritative; a geodesic area is independently
recomputed from the returned ring and agrees to **about +0.2 %** (a projection/datum difference), and both are
shown in the data panel. Layer metadata is read at run time, so a field change adapts rather than breaks.
Service errors surface as a message, never as substituted geometry. **No demo geometry remains in the repo.**

## Where the map opens: chosen from live data, not hardcoded

The startup viewport is derived at run time by `app/exploration.py` (`GET /api/exploration-area`). The only
fixed geography is a list of **search windows** over Qatar's named farming municipalities — where to look.
What you see is decided by the data:

1. Page through the cadastre in each window with `returnCentroid=true`, keeping plots whose registered area
   falls in an agricultural band (5,000–1,000,000 m²; the layer carries no land-use field, and residential
   plots are a few hundred m²). No polygon geometry is downloaded.
2. Bin the centroids onto a ~780 m grid, form a candidate cluster around each populated cell, suppress
   overlaps.
3. Rank on measurable criteria: **size diversity** (log-spread of plot areas), **farmland context** (OSM
   `landuse=farmland|farmyard|orchard|greenhouse_horticulture` within 3 km), **plot count** (scored against a
   10–30 band — comfortable to compare, not the densest block), **compactness**, **road access** and
   **market-distance spread**.
4. Fit the map to the winner and label it *“Suggested exploration area — real Qatar cadastral data”*, with the
   reasons available behind “why here”. **No plot is preselected.**

A criterion that does not vary between candidates is **dropped and its weight redistributed**, rather than
scoring every candidate 1.0 — an earlier version did the latter and silently gave full marks for a signal that
was absent. Overpass is flaky, so OSM enrichment runs only on the finalists and the result records which
criteria actually contributed.

At the time of writing this picks a cluster in the Al Rayyan outskirts: **9 plots from 10,000 to 972,134 m²**
(57× between the 10th and 90th percentile) within a 619 m radius, selected after screening **6,632 plots across
6 municipalities**. The result is cached, so startup is instant; the ranking is deterministic, so the same data
gives the same viewport.

## 2–5. Data sources

| Source | Used for | Access | Status |
|---|---|---|---|
| **Qatar cadastral FeatureServer** | plot boundaries, registered areas, PIN, planning-decision number | public, no key | **Live** |
| **Qatar Open Data** — *Production, Area and Average Yield of Crops* and *Cropped area & production of crops in greenhouses* (Opendatasoft v2.1) | open-field and greenhouse yield baselines | public, no key | **Live.** Yield is recomputed as production ÷ area; records disagreeing with the reported yield by >10 % or that are robust outliers are rejected with the reason kept (the 2023 tomato record is a genuine example). ≥3 usable years required, else the option is excluded — this is why open-field strawberry (2 years) is refused. |
| **NASA POWER** daily point API (AG) | T2M / T2M_MAX / T2M_MIN, ALLSKY_SFC_SW_DWN, RH2M, WS2M, PRECTOTCORR, 2019–2024 | public, no key | **Live.** Queries are snapped to the native MERRA-2 0.5°×0.625° cell centre — this is gridded reanalysis and the UI says so, not plot-level sensing. |
| **ISRIC SoilGrids 2.0** via **WCS** (the paused REST API is deliberately unused) | pH, sand, silt, clay 0–100 cm → USDA texture → AquaCrop soil file | public, no key | **Live** (GeoTIFF). |
| **OpenStreetMap / Overpass** | nearest market and main road, informational only | public, cached, identifying UA | **Live but flaky**; shown as unavailable when it times out. Never an optimizer input. |
| **Soil salinity / EC** | Maas-Hoffman yield penalty | — | **Not available.** SoilGrids has no salinity layer and no verified Qatar EC dataset was found. It is a user input; left blank, **no penalty is applied and the result says so.** |
| **Crop prices** | revenue | — | **No machine-readable official source exists.** The Qatar open-data portal's 36 "price" datasets are all GDP/CPI. Prices are therefore required user inputs labelled *User supplied*. |
| **Kahramaa tariffs** | electricity and water unit prices | — | Kahramaa publishes a distinct **“Productive Farms”** category (confirmed on the official tariff page) but the rates live only in an interactive calculator. Required user input — take it from your own bill. |

**No integrated source requires a credential**, so no API key was ever requested or invented. Optional
environment variables (`QATAR_PARCEL_LAYER_URL`, `QATAR_GIS_TOKEN`) exist only to repoint or authenticate a
different deployment; see `.env.example`.

## 6. Scientific yield model

**FAO AquaCrop** (`aquacrop` 3.1.0) is applied **only to open-field tomato** — the one MVP crop with a
calibrated crop file in the package:

`NASA POWER weather → FAO-56 ET0 → SoilGrids texture class → AquaCrop (5 seasons, soil-moisture-triggered
irrigation, planting date from the thermal window) → attainable yield + daily irrigation → optimizer`

AquaCrop's **daily irrigation series** drives tomato's monthly water demand. Its uncalibrated yield (~175 t/ha)
is a well-managed attainable yield, ~3.4× the Qatar statistic (~51 t/ha), so one **national calibration factor**
*k = Qatar median ÷ AquaCrop at a fixed reference site* is applied and both numbers plus *k* are shown in the
data panel. Absolute level comes from official statistics; climate and soil response from the process model.

AquaCrop is **not** applied to greenhouse, hydroponic or vertical systems, nor to cucumber, lettuce, pepper or
strawberry (no crop files — parameters are not invented). Those use an explicit empirical model whose every
parameter is sourced, user-supplied or refused. The UI labels each yield *AquaCrop*, *Official Qatar data* or
*Unverified*.

## 7. Defensible crop × technique set

Priority 1 (**official Qatar yield data for both systems**): **tomato** and **cucumber**, open field and
greenhouse. Priority 2: **bell pepper** (open-field + greenhouse Qatar data), **lettuce** (open-field only).
Priority 3: **strawberry** — every yield is a required input. All soilless yields are required inputs.
Five combinations are fully backed by official data; the rest are gated rather than faked.

## 8–9. CapEx and component-based OpEx

**The CapEx figures supplied for this task (≈194 / 624 / 534 / 227 QAR/m²) could not be verified.** The Qatar
paper retrieved and read during implementation (Karanisa et al. 2021, *Sustainability* 13:4059, open access)
contains no per-m² costs, and the likely source (Lahlou, Mahmood & Al-Ansari 2025, *Cleaner and Circular
Bioeconomy*) is paywalled. They are therefore **not presented as sourced**: they appear only as unverified
planning-profile values, each carrying a note saying the publication could not be located. Replace them with a
supplier quotation.

OpEx is **never** a single unsourced QAR/m²/year figure. It is assembled per block from components:

```
OpEx = labour + maintenance + seedlings×cycles + nutrients×cycles + water_m3×water_tariff + kWh×electricity_tariff
```

water and electricity are priced from the *modelled metered use*, and the realised split per block is reported
in the data panel. Every monetary parameter carries value + unit + source + date + status.

## 10–12. The optimization

Sets: plots *p*, options *o* = (crop *c*, technique *t*) that are compatible, thermally feasible **and fully
specified**, months *m*, shared-infrastructure groups *g*.

| Variable | Type | Meaning |
|---|---|---|
| `area[p,c,t]` | continuous ≥ 0 | m² allocated — **the portfolio** |
| `z[p,c,t]` | binary | block used (enforces the minimum block area) |
| `build[p,t]` | binary | technique built on the plot (fixed CapEx charged once) |
| `infra[p,g]` | binary | shared infrastructure built on the plot — **charged once** for all techniques needing it |

```
Profit P = Σ (rev_o − opex_o)·area − Σ F^op_t·build − Σ F^op_g·infra          [QAR/yr]
CapEx  C = Σ capex_o·area          + Σ F_t·build     + Σ F_g·infra            [QAR]
Net    N = H·P − C          (Year 0 = −C, Years 1..H = P;  H = 5)
ROI      = N / C                       payback = C / P  (a different quantity)

land          Σ_o area[p,o] ≤ U_p                                for each plot
linking       minblock·z ≤ area ≤ U_p·z ;  z[p,o] ≤ build[p,t(o)]
min scale     Σ_{o∈t} area[p,o] ≥ minarea_t·build[p,t]
shared infra  build[p,t] ≤ infra[p,g]  for every g required by t
budget        C ≤ Budget
water         Σ w[o,m]·area ≤ Wmax_month   for EVERY month m ;  Σ w_o·area ≤ W
energy        Σ e[o,m]·area ≤ Emax_month   for EVERY month m ;  Σ e_o·area ≤ E
utilisation   Σ area ≥ u·Σ U_p   (planning floor; relaxed with a visible warning if infeasible)
```

Incompatible, thermally infeasible or under-specified combinations get **no variable at all**.

### Annual volume and delivery rate are different limits

`W` is the annual volume you may use; `Wmax_month` is the most that can physically be **delivered in one
month** (pump, well or contract capacity) and is **optional** — unset, it is infinite and a month may draw on
the whole annual allowance.

An earlier version derived the monthly cap as `W × factor / 12` with `factor = 2`. That invented a delivery
limit the user never stated, and for seasonal crops it dominated everything else: open-field cucumber in Qatar
grows November–February, so its whole year of irrigation lands in four months. On a 171 ha selection the
result was a farm of 27,858 m² with December water pinned at exactly 100 % of the derived cap, while 44 % of
the annual allowance went unused and the budget sat at 71 %. Removing the invented cap let the same solver
allocate 39,400 m² with the budget correctly binding at 100 %, raising annual profit from QAR 601,695 to
QAR 851,244 on identical data.

### Unallocated land is explained, not just drawn

`app/limiting.py` reports, from the solved model, which limit stopped expansion and how much land each limit
alone would support, so a large grey "Unallocated" area always carries its reason — for example *"98 % of the
selected land is unallocated because the budget is the binding limit: QAR 1,200,000 buys about 40,000 m² of
this system; developing all 1,712,413 m² the same way would cost roughly QAR 51,372,377."* Unallocated land is
a real economic result, never a gap in the cadastral data.

**Objective — maximise 5-year ROI.** ROI is a ratio of two linear functions, so it is solved exactly by
**Dinkelbach's algorithm**:

```
λ₀ = 0
repeat:  x_k = argmax_x  N(x) − λ_k·C(x)        (one MIP per iteration, solved to optimality, gap 1e-9)
         F_k = N(x_k) − λ_k·C(x_k)
         stop when F_k ≤ tol                     → x_k maximises N/C exactly
         λ_{k+1} = N(x_k)/C(x_k)
```

`F(λ) = max_x N − λC` is convex, piecewise-linear and decreasing, so this is Newton's method on `F(λ)=0` and
terminates finitely (typically 2–4 MIP solves).

### ROI when CapEx is zero — defined explicitly, not regularised

`λ = N / CapEx` is undefined when a plan costs nothing, which is reachable whenever every capital cost is
entered as zero. Earlier code dodged this by adding `CapEx ≥ 1` to the MIP; that is an arbitrary epsilon which
silently deletes every zero-investment plan from the feasible set, so it has been removed. The three cases are
now classified and reported instead, and the loop stops immediately in each:

| Case | Meaning | Result |
|---|---|---|
| `CapEx = 0`, no land allocated | maximising `N` preferred building nothing, i.e. no allowed farm has a positive 5-year net cash flow | status **`NO_VIABLE_INVESTMENT`**, ROI `null`, explicit message |
| `CapEx = 0`, land allocated, `N > 0` | production without capital; `N/0` is unbounded above, so the ratio has no finite maximum | status **`ZERO_CAPEX`**, the plan is still returned, ROI `null`, message says why |
| `CapEx = 0`, land allocated, `N = 0` | `0/0` | status **`ZERO_CAPEX`**, ROI `null`, reported as undefined |

`CAPEX_TOL = 1e-6` QAR and `AREA_TOL = 1e-6` m² are float-comparison tolerances only: they decide when a
quantity *is* zero and never enter the objective or a constraint.

One subtlety the tests pin down: at the root `F(λ) = 0`, the trivial "build nothing" point (`N = CapEx = 0`)
*ties* the optimal portfolio, so the solver may legitimately return it on the final iterate. That is
convergence, not a degenerate answer — the incumbent that produced λ is kept, and λ itself is the optimal ratio.

Inputs that would make the model divide by zero are rejected up front with a precise message rather than
propagated: an irrigation efficiency of 0 would demand infinite water, so `validate_values()` refuses it
(along with negative costs and prices, efficiencies above 1, and non-positive cycle lengths) and the API
returns 422. Every iteration — λ, N, C, F(λ), status, milliseconds — is
streamed to the UI and shown in the solver tab. A test enumerates a dense grid of feasible portfolios by brute
force and asserts the returned ROI equals the true maximum. A second objective, **5-year net cash flow**
(a single MIP), is selectable.

## 13. Modelled interactions (each one an equation, never a "synergy score")

* **Shared infrastructure** — water network, cooling plant and nutrient dosing are `infra[p,g]` decisions whose
  fixed cost is charged once per plot, so `CapEx(shared) < Σ CapEx(standalone)`; the saving is reported per plot.
* **Shared water and energy** — one pool across all plots and systems, constrained **per month** as well as annually.
* **Crop calendar competition** — thermal windows come from NASA POWER, so open-field crops occupy the cool
  months only, greenhouses a longer window and controlled systems all year; options with different calendars can
  coexist under a cap that one crop alone would exhaust in its season.

## 14. Baselines

Two, both feasible points of the *same* problem (so `optimum ≥ baseline` is a tested invariant):
**whole plot** (one crop × one technique over all usable area, scaled only if constraints force it) and
**best single option** (best one-crop-one-technique farm found by the same MIP).

## 15. 2D management plan

`frontend/lib/layout.ts` (Turf.js): the real cadastral polygon is projected to a local metric plane and cut into
consecutive strips perpendicular to a candidate axis (the plot's longest edges and their perpendiculars). Each
cut is placed by bisection so the strip's intersection with the plot has **exactly** the requested area. Strips
are disjoint by construction, are intersections with the plot (so inside the boundary), and sum to the plot area
(access strip + production blocks + an explicit "unallocated" piece). The axis giving the fewest disconnected
pieces wins, ties broken deterministically → reproducible. Tested for area conservation, non-overlap and
containment. **The MIP optimises the portfolio; the layout only renders it as a feasible blueprint and is not
claimed to be spatially optimal.**

## 16. Data provenance UI

Every row is `Value | Unit | Source | Date | Type`, filterable by type and by "Missing", with an expandable
full-width table. Types: Official Qatar data · Scientific model · Peer-reviewed research · Open dataset ·
Vendor data · User supplied · Unverified. Unresolved inputs render as
**“Required input unavailable — enter value”**, and the results page lists every refused combination grouped by
reason.

## 17–18. Credentials and open source

No credential is required by any integrated source, so none was requested. `QATAR_GIS_TOKEN` is sent only if you
set it. Secrets live in environment variables and are git-ignored.

Open-source components: **OR-Tools** (Apache-2.0), **aquacrop** (FAO AquaCrop, see its repository for licence),
FastAPI, pandas, numpy, tifffile, httpx, **Next.js**, React, Tailwind CSS, **MapLibre GL JS** (BSD-3-Clause),
**Turf.js** (MIT), Recharts, vitest, pytest. Map tiles **© OpenStreetMap contributors** (ODbL); OSM data via
Overpass under ODbL; **ISRIC SoilGrids** CC-BY 4.0; **NASA POWER** freely available; **State of Qatar Open Data**
and the **Centre for GIS** cadastral service under their own terms.

## 19–20. What was removed

The demo parcel generator and `demo_parcels.geojson` are **deleted**. All `prototype_assumption` provenance ids
are gone. No hard-coded yield, price, CapEx or OpEx figure remains in application code — every number comes from
a live adapter, from `data/*.json` with a resolvable source id, or from the user. A repository-wide sweep for
mock/fake/placeholder/hard-coded/random leaves only comments describing what the code refuses to do, and HTML
input placeholders.

## 21. Limitations

* Economic realism is bounded by your inputs: with unverified defaults, absolute ROI and payback are
  illustrative. The provenance panel makes every such value visible.
* **ROI is a ratio**, so maximising it can prefer a small, cheap farm on a large plot. The utilisation floor and
  the net-cash-flow objective exist for that reason, and a relaxed floor is reported as a warning.
* AquaCrop covers open-field tomato only, with one national calibration factor and full irrigation; no deficit-
  irrigation response curve, and salinity uses Maas-Hoffman on user-entered ECe.
* One climate cell per plot from 2019–2024 monthly means: no inter-annual risk, price risk or discounting.
* Land is allocated in space, not in time — no rotations, and no reuse of the same m² by different systems in
  different months.
* The layout is a feasible blueprint, not a spatially optimised design; concave plots can split a block.
* Water quality and leaching, labour availability, market absorption and permits are not modelled.
* The cadastral layer gives geometry and registered area only — **no ownership or tenure information**, and
  selecting a plot in this tool implies no right to farm it.
