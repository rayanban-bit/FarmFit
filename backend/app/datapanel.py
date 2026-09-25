"""The 'Data & assumptions' panel: one traceable row per input that reached the model.

Each row is Value | Unit | Source | Date | Type. Inputs that have no defensible source appear with
value None and status 'missing', rendered by the UI as "Required input unavailable - enter value" -
they are never filled with a guess.
"""
from __future__ import annotations

from .provenance import Row, missing_row, row_from_param, source, today

CAD = "qatar_cadastre"


def _grouped(row: Row, group: str) -> Row:
    row.note = (f"[{group}] " + (row.note or "")).strip()
    return row


def build_data_panel(ctx, problem, detail: dict, scenario_id: str, sol, tariffs) -> list[Row]:
    cat, req = ctx.cat, ctx.req
    c = req.constraints
    rows: list[Row] = []

    def add(key, label, leaf, group, value=None):
        rows.append(_grouped(row_from_param(key, label, leaf, value), group))

    def miss(key, label, unit, why, group, src_id="required"):
        rows.append(_grouped(missing_row(key, label, unit, why, src_id), group))

    # ---------------- Land (live cadastre)
    s_cad = source(CAD)
    for pc in ctx.plots:
        live = "Live cadastral" in (pc.geometry_source or "")
        rows.append(_grouped(Row(f"plot.{pc.id}.geometry", f"Plot {pc.id} boundary", pc.geometry_source, "",
                                 s_cad["name"] if live else "User supplied geometry", s_cad["url"] if live else "",
                                 s_cad["retrieved"] if live else "n/a", s_cad["type"] if live else "user_supplied",
                                 "live" if live else "user",
                                 "Polygon returned by the ArcGIS Query operation, reprojected by the server to EPSG:4326."
                                 if live else ""), "Land"))
        reg = pc.registered_area_m2
        rows.append(_grouped(Row(f"plot.{pc.id}.area", f"Plot {pc.id} area", round(pc.area_m2, 1), "m2",
                                 s_cad["name"] if reg else "Computed from the supplied boundary",
                                 s_cad["url"] if reg else "", today(),
                                 "official_qatar" if reg else "scientific_model", "live" if reg else "computed",
                                 f"Officially registered area (PDAREA). Geodesic area recomputed from the returned "
                                 f"boundary: {pc.geodesic_area_m2:,.0f} m2." if reg else
                                 "Spherical (geodesic) area of the supplied polygon."), "Land"))
    add("access_fraction", "Access / infrastructure share of plot", cat["defaults"]["access_fraction"], "Land", c.access_fraction)

    # ---------------- Climate and soil
    for pc in ctx.plots:
        if pc.clim is not None:
            m, s_np = pc.weather_meta, source("nasa_power")
            rows.append(_grouped(Row(f"climate.{pc.id}", f"Plot {pc.id} daily weather",
                                     f"{m['n_days']} days, {pc.df.index.min().date()} to {pc.df.index.max().date()}",
                                     "deg C, MJ/m2/d, %, m/s, mm/d", s_np["name"], m["source_url"], m["retrieved_at"],
                                     s_np["type"], m["status"],
                                     f"Query snapped to the native reanalysis cell {pc.cell}; plot centroid "
                                     f"{pc.lon:.4f},{pc.lat:.4f}. Gridded reanalysis, not plot-level sensor data."), "Climate"))
            rows.append(_grouped(Row(f"et0.{pc.id}", f"Plot {pc.id} reference ET0 (annual)",
                                     round(sum(a * b for a, b in zip(pc.clim["et0_mm_day"], pc.clim["days"])), 0), "mm/year",
                                     "FAO-56 Penman-Monteith computed from the NASA POWER series", source("fao56")["url"],
                                     today(), "scientific_model", "computed", ""), "Climate"))
        else:
            miss(f"climate.{pc.id}", f"Plot {pc.id} daily weather", "", pc.weather_error or "not retrieved", "Climate", "user")
        if pc.soil:
            sm, s_sg = pc.soil_meta, source("soilgrids")
            for k, unit in (("phh2o", "pH"), ("sand", "%"), ("silt", "%"), ("clay", "%")):
                v = pc.soil.get(k)
                rows.append(_grouped(Row(f"soil.{pc.id}.{k}", f"Plot {pc.id} soil {k} (0-100 cm)",
                                         None if v is None else round(v, 2), unit, s_sg["name"], sm["source_url"],
                                         sm["retrieved_at"], s_sg["type"], "missing" if v is None else sm["status"],
                                         "Median of the 250 m pixels around the plot centroid, depth-weighted."), "Soil"))
            rows.append(_grouped(Row(f"soil.{pc.id}.texture", f"Plot {pc.id} USDA texture class", pc.soil.get("texture_class"),
                                     "", "Derived from the SoilGrids sand/silt/clay fractions", "", today(),
                                     "scientific_model", "computed", "Selects which AquaCrop soil file is used."), "Soil"))
        else:
            miss(f"soil.{pc.id}", f"Plot {pc.id} SoilGrids properties", "", pc.soil_error or "not retrieved", "Soil", "user")
    if c.soil_ec_ds_m is None:
        miss("soil.ec", "Measured soil salinity (ECe)", "dS/m",
             "Not provided. SoilGrids publishes no salinity layer and no verified Qatar EC dataset was located, "
             "so NO salinity yield penalty was applied to soil-based systems.", "Soil", "user")
    else:
        add("soil.ec", "Measured soil salinity (ECe)", {"value": c.soil_ec_ds_m, "unit": "dS/m", "src": "user"}, "Soil")

    # ---------------- Constraints and tariffs
    add("budget", "Budget (maximum CapEx)", {"value": c.budget_qar, "unit": "QAR", "src": "user"}, "Constraints")
    add("water", "Available water (after scenario factor)", {"value": problem.limits.water_year, "unit": "m3/year", "src": "user"}, "Constraints")
    add("energy", "Available energy", {"value": c.energy_kwh_year, "unit": "kWh/year", "src": "user"}, "Constraints")
    d = cat["defaults"]
    e_price, w_price, e_src, w_src = tariffs
    for key, label, val, src_id, leaf in (("electricity", "Electricity unit price (after scenario factor)", e_price, e_src, d["electricity_qar_kwh"]),
                                          ("water_price", "Water unit price", w_price, w_src, d["water_qar_m3"])):
        if val is None:
            miss(key, label, leaf["unit"],
                 "Kahramaa publishes a 'Productive Farms' category but no machine-readable rate; enter the price from your bill.",
                 "Constraints")
        else:
            add(key, label, {"value": round(val, 4), "unit": leaf["unit"], "src": src_id}, "Constraints")
    for key, label, val, unit in (("water_peak", "Water delivery capacity (one month)", c.water_peak_m3_month, "m3/month"),
                                  ("energy_peak", "Electricity delivery capacity (one month)", c.energy_peak_kwh_month, "kWh/month")):
        if val is None:
            miss(key, label, unit, "Not stated, so only the annual volume limits use. Enter a pump, well or "
                                   "contract capacity if a single month is physically capped.", "Constraints", "user")
        else:
            add(key, label, {"value": val, "unit": unit, "src": "user"}, "Constraints")
    for k, label, val in (("min_land_utilisation", "Minimum land utilisation", c.min_land_utilisation),
                          ("min_block_m2", "Minimum block area", c.min_block_m2),
                          ("horizon_years", "Planning horizon", c.horizon_years),
                          ("effective_rain_fraction", "Effective rain fraction", d["effective_rain_fraction"]["value"])):
        add(k, label, {"value": val, "unit": d[k]["unit"], "src": d[k]["src"] if val == d[k]["value"] else "user"}, "Constraints")

    # ---------------- Crop economics and agronomy
    for cid in req.crops:
        crop = cat["crops"][cid]
        nm = crop["name"]
        price = req.prices.get(cid)
        if price is not None:
            add(f"crop.{cid}.price", f"{nm} selling price", {"value": price, "unit": "QAR/kg", "src": "user"}, "Crop economics")
        elif crop["price_qar_kg"]["value"] is None:
            miss(f"crop.{cid}.price", f"{nm} selling price", "QAR/kg",
                 "No machine-readable official Qatar farm-gate price dataset exists (the open-data portal publishes only "
                 "GDP and CPI price series), so a price must be entered.", "Crop economics")
        else:
            add(f"crop.{cid}.price", f"{nm} selling price", crop["price_qar_kg"], "Crop economics")
        for f, label in (("seedlings_qar_m2_cycle", "seedlings / planting material"), ("nutrients_qar_m2_cycle", "fertiliser / nutrients")):
            leaf = crop[f]
            if leaf["value"] is None:
                miss(f"crop.{cid}.{f}", f"{nm} - {label}", leaf["unit"], "No sourced Qatar figure located.", "Crop economics")
            else:
                add(f"crop.{cid}.{f}", f"{nm} - {label}", leaf, "Crop economics")
        for f, label in (("cycle_days", "crop cycle"), ("stage_days", "stage lengths"), ("kc", "Kc (ini, mid, end)"),
                         ("temp_limits_c", "temperature limits"), ("salinity", "salinity tolerance (Maas-Hoffman)")):
            add(f"crop.{cid}.{f}", f"{nm} - {label}", crop[f], "Crop agronomy")

    # ---------------- Yields actually used by the solver
    seen = set()
    for (_pid, cid, tid), dd in detail.items():
        key = (cid, tid, dd["yield_kind"])
        if key in seen:
            continue
        seen.add(key)
        crop, tech = cat["crops"][cid], cat["techniques"][tid]
        label = f"{crop['name']} x {tech['name']} - yield per cycle"
        if dd["yield_kind"] == "aquacrop":
            aq, s_aq = dd["y"]["aquacrop"], source("aquacrop")
            note = (f"AquaCrop attainable {aq['yield_t_ha_uncalibrated']:.0f} t/ha scaled by the national calibration factor "
                    f"{aq['calibration_factor']:.3f} (Qatar median {dd['y']['stat']['t_ha']:.1f} t/ha divided by AquaCrop at the "
                    f"reference site). Soil file {aq['soil_class_used']}"
                    f"{' (fallback - SoilGrids missing)' if aq['soil_is_fallback'] else ''}; {aq['plot']['n_seasons']} simulated seasons.")
            rows.append(_grouped(Row(f"yield.{cid}.{tid}", label, round(dd["yield_kg_m2_cycle"], 3), "kg/m2/cycle",
                                     s_aq["name"], s_aq["url"], today(), "scientific_model", "live", note), "Yields"))
        elif dd["yield_kind"] == "official":
            st, s_od = dd["y"]["stat"], source(dd["yield_src"])
            rej = f"; {len(st['rejected'])} record(s) rejected as inconsistent" if st["rejected"] else ""
            rows.append(_grouped(Row(f"yield.{cid}.{tid}", label, round(dd["yield_kg_m2_cycle"], 3), "kg/m2/cycle",
                                     s_od["name"], s_od["url"], dd["y"]["stat_meta"]["retrieved_at"], s_od["type"],
                                     dd["y"]["stat_meta"]["status"],
                                     f"Median of {st['n']} year(s) {st['years_used'][0]}-{st['years_used'][-1]} = {st['t_ha']:.1f} t/ha, "
                                     f"converted at 1 t/ha = 0.1 kg/m2{rej}. {dd['yield_note']}"), "Yields"))
        else:
            leaf = crop["yields"][tid]
            s_y = source(leaf["src"])
            rows.append(_grouped(Row(f"yield.{cid}.{tid}", label, dd["yield_kg_m2_cycle"], "kg/m2/cycle", s_y["name"],
                                     s_y.get("url", ""), s_y.get("retrieved", "n/a"), s_y["type"], s_y.get("status", ""),
                                     "Empirical model - AquaCrop is NOT applied to this production system. "
                                     + (leaf.get("profile_note") or "")), "Yields"))

    # ---------------- Technique CapEx, resources and OpEx components
    used_techs = sorted({t for (_, _, t) in detail})
    for tid in used_techs:
        tech = cat["techniques"][tid]
        nm = tech["name"]
        for f, label, group in (("capex_qar_m2", "CapEx per m2", "CapEx"),
                                ("fixed_capex_qar", "fixed CapEx per plot", "CapEx"),
                                ("water_coefficient", "water coefficient", "Technique resources"),
                                ("irrigation_efficiency", "irrigation efficiency", "Technique resources"),
                                ("extra_water_m3_m2_year", "evaporative cooling water", "Technique resources"),
                                ("energy_kwh_m2_year", "electricity use", "Technique resources"),
                                ("cooling_delta_c", "cooling effect on daily maximum", "Technique resources"),
                                ("min_area_m2", "minimum viable area", "Technique resources")):
            leaf = tech[f]
            row = row_from_param(f"tech.{tid}.{f}", f"{nm} - {label}", leaf)
            if leaf.get("profile_note"):
                row.note = (row.note + " " + leaf["profile_note"]).strip()
            rows.append(_grouped(row, group))
        for f, label in (("labour_qar_m2_year", "labour"), ("maintenance_qar_m2_year", "maintenance")):
            add(f"tech.{tid}.{f}", f"{nm} - OpEx component: {label}", tech["opex_components"][f], "OpEx components")

    # realised OpEx split per selected block (computed, not assumed)
    for (pid, cid, tid), dd in detail.items():
        br = dd.get("opex_breakdown")
        if not br:
            continue
        txt = ", ".join(f"{k} {v:.2f}" for k, v in br.items())
        rows.append(_grouped(Row(f"opex.{pid}.{cid}.{tid}", f"{cat['crops'][cid]['name']} x {cat['techniques'][tid]['name']} "
                                 f"on {pid} - OpEx split", round(sum(br.values()), 2), "QAR/m2/year",
                                 "Computed from the OpEx components and metered water/electricity use", "", today(),
                                 "scientific_model", "computed", f"QAR/m2/year: {txt}."), "OpEx components"))

    for gid in sorted({g for tid in used_techs for g in cat["techniques"][tid]["requires"]}):
        g = cat["groups"][gid]
        add(f"infra.{gid}.capex", f"{g['name']} - fixed CapEx (charged once per plot)", g["fixed_capex_qar"], "Shared infrastructure")
        add(f"infra.{gid}.opex", f"{g['name']} - fixed annual OpEx", g["fixed_opex_qar_year"], "Shared infrastructure")

    # ---------------- The honest gaps
    for m in ctx.missing_inputs:
        miss(f"required.{m['kind']}.{m['owner']}.{m['field']}", m["label"], m["unit"],
             "Required input unavailable - enter value."
             + (" An unverified planning figure is available for it." if m["has_profile_value"]
                else " No planning figure exists; a real quotation or measurement is needed."), "Required inputs")

    sc = cat["scenarios"][scenario_id]
    if scenario_id != "normal":
        rows.append(_grouped(Row("scenario", f"Scenario: {sc['name']}",
                                 f"water x{sc['water_factor']}, electricity price x{sc['electricity_price_factor']}", "",
                                 source(sc["src"])["name"], "", "n/a", "scientific_model", "modelling_choice",
                                 sc["description"]), "Scenario"))
    rows.append(_grouped(Row("solver", "Optimization method", sol.solver.get("method", ""), "",
                             "OR-Tools pywraplp / SCIP MIP with Dinkelbach fractional programming",
                             "https://developers.google.com/optimization", today(), "scientific_model", "computed", ""), "Method"))
    return rows
