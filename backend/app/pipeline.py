"""Orchestration: request -> real data -> physical/economic options -> MIP -> result.

    plot geometry -> centroid -> NASA POWER daily weather (cached) -> FAO-56 ET0 + monthly climatology
                  -> SoilGrids texture (WCS)      -> AquaCrop soil class
    crop x technique: thermal window + cycle schedule (crop_model) + yield source
                  (AquaCrop for open-field tomato | Qatar Open Data | sourced/prototype parameters)
    -> Option(plot, crop, technique) with per-m2 revenue, opex, capex and MONTHLY water / energy
    -> optimizer.solve (Dinkelbach + SCIP MIP) -> baseline -> explanations -> data panel
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from . import aquacrop_model, baseline as baseline_mod, catalog as catalog_mod, climate, crop_model, finance, optimizer
from .datapanel import build_data_panel
from .limiting import diagnose
from .adapters import nasa_power, osm, qatar_open_data as qod, soilgrids
from .adapters.base import AdapterUnavailable
from .optimizer import GroupIn, Limits, Option, PlotIn, Problem, TechIn
from .provenance import Row, missing_row, row_from_param, source, today
from .schemas import OptimizeRequest
from .units import geometry_area_m2, geometry_centroid

Emit = Callable[[dict], None]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _noop(_: dict) -> None:
    return None


@dataclass
class PlotCtx:
    id: str
    name: str
    geometry: dict
    geometry_source: str
    area_m2: float
    geodesic_area_m2: float
    registered_area_m2: float | None
    usable_m2: float
    lon: float
    lat: float
    cell: tuple[float, float] | None = None
    df: object | None = None
    clim: dict | None = None
    weather_meta: dict | None = None
    weather_error: str | None = None
    soil: dict | None = None
    soil_meta: dict | None = None
    soil_error: str | None = None
    access: dict | None = None
    access_meta: dict | None = None
    access_error: str | None = None


@dataclass
class Ctx:
    req: OptimizeRequest
    cat: dict
    plots: list[PlotCtx]
    stats_open: dict = field(default_factory=dict)  # crop id -> (result, meta) | error string
    stats_gh: dict = field(default_factory=dict)
    ref_df: object | None = None
    notes: list[str] = field(default_factory=list)
    missing_inputs: list[dict] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------
# 1. data preparation
# ------------------------------------------------------------------------------------------------
def prepare_context(req: OptimizeRequest, emit: Emit = _noop) -> Ctx:
    cat, missing = catalog_mod.resolve(catalog_mod.base_catalog(), req.overrides, req.accept_planning_profile)
    problems = catalog_mod.validate(cat)
    if problems:
        raise ValueError("Catalog inconsistent: " + "; ".join(problems))
    bad_values = catalog_mod.validate_values(cat)
    if bad_values:
        raise ValueError("Invalid input value(s): " + "; ".join(bad_values))
    for cid in req.crops:
        if cid not in cat["crops"]:
            raise ValueError(f"Unknown crop '{cid}'")
    for tid in req.techniques:
        if tid not in cat["techniques"]:
            raise ValueError(f"Unknown technique '{tid}'")

    plots: list[PlotCtx] = []
    access = req.constraints.access_fraction
    for p in req.plots:
        geodesic = geometry_area_m2(p.geometry)
        # The officially registered cadastral area (PDAREA) is authoritative when the plot came from the
        # live cadastre; the geodesic area recomputed from the boundary is kept alongside it for comparison.
        area = float(p.registered_area_m2) if p.registered_area_m2 else geodesic
        lon, lat = geometry_centroid(p.geometry)
        plots.append(PlotCtx(p.id, p.name or p.id, p.geometry, p.source or "user supplied geometry", area, geodesic,
                             p.registered_area_m2, area * (1 - access), lon, lat))
    emit({"event": "stage", "name": "plots", "message": f"{len(plots)} plot(s), {sum(p.area_m2 for p in plots):,.0f} m2 total (spherical area from geometry)"})
    ctx = Ctx(req, cat, plots, missing_inputs=missing)
    if missing:
        emit({"event": "stage", "name": "inputs", "message":
              f"{len(missing)} required input(s) still unresolved - any crop x technique that needs one will be excluded, not guessed"})

    # climate + soil (+ optional OSM context) per plot, in parallel
    def load_plot(pc: PlotCtx) -> None:
        try:
            df, meta = nasa_power.get_daily(pc.lon, pc.lat)
            pc.df, pc.weather_meta, pc.cell = df, meta, (meta["query_lon"], meta["query_lat"])
            pc.clim = climate.monthly_climatology(df, meta["query_lat"])
        except AdapterUnavailable as exc:
            pc.weather_error = str(exc)
        try:
            pc.soil, pc.soil_meta = soilgrids.get_soil(pc.lon, pc.lat)
        except AdapterUnavailable as exc:
            pc.soil_error = str(exc)
        if req.include_context:
            try:
                pc.access, pc.access_meta = osm.nearest_access(pc.lon, pc.lat)
            except AdapterUnavailable as exc:
                pc.access_error = str(exc)

    emit({"event": "stage", "name": "climate", "message": "Retrieving NASA POWER daily weather, SoilGrids soil and OSM context (cached when available)"})
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(plots)))) as ex:
        list(ex.map(load_plot, plots))
    for pc in plots:
        if pc.clim is not None:
            emit({"event": "stage", "name": "climate", "message": f"{pc.id}: climate cell {pc.cell}, {pc.weather_meta['n_days']} days ({pc.weather_meta['status']}); "
                  f"soil {'texture ' + pc.soil['texture_class'] if pc.soil and pc.soil.get('texture_class') else 'MISSING'}"})
        else:
            emit({"event": "stage", "name": "climate", "message": f"{pc.id}: NASA POWER unavailable - open-field/greenhouse windows cannot be computed for this plot"})

    # Qatar Open Data yields (global, per crop)
    emit({"event": "stage", "name": "qatar_open_data", "message": "Reading Qatar Open Data crop yield statistics"})
    for cid in req.crops:
        crop = cat["crops"][cid]
        for kind, store, fn in (("open_field", ctx.stats_open, qod.open_field_yield), ("greenhouse", ctx.stats_gh, qod.greenhouse_yield)):
            names = crop["qatar_names"].get(kind, [])
            if not names:
                store[cid] = "no Qatar Open Data series for this crop"
                continue
            try:
                store[cid] = fn(names)
            except AdapterUnavailable as exc:
                store[cid] = f"Qatar Open Data unavailable: {exc}"
    # reference weather for the AquaCrop calibration
    if "tomato" in req.crops and "open_field" in req.techniques:
        try:
            ctx.ref_df, _ = nasa_power.get_daily(*aquacrop_model.REF_CELL)
        except AdapterUnavailable as exc:
            ctx.notes.append(f"AquaCrop calibration reference weather unavailable: {exc}")
    return ctx


# ------------------------------------------------------------------------------------------------
# 2. options
# ------------------------------------------------------------------------------------------------
MIN_OBS = 3


def _tariffs(ctx: Ctx, scenario: dict) -> tuple[float | None, float | None, str, str]:
    """Electricity and water unit prices. None means the required input is unresolved."""
    d = ctx.cat["defaults"]
    e = ctx.req.electricity_qar_kwh
    w = ctx.req.water_qar_m3
    e_src = "user" if e is not None else d["electricity_qar_kwh"]["src"]
    w_src = "user" if w is not None else d["water_qar_m3"]["src"]
    e = e if e is not None else d["electricity_qar_kwh"]["value"]
    w = w if w is not None else d["water_qar_m3"]["value"]
    return (None if e is None else e * scenario["electricity_price_factor"]), w, e_src, w_src


def _yield_for(ctx: Ctx, pc: PlotCtx, cid: str, tid: str, sched: dict | None) -> dict | None | str:
    """Return {'kg_m2_cycle', 'src', 'kind', 'note', ...} or a string explaining why no yield exists."""
    crop = ctx.cat["crops"][cid]
    entry = crop["yields"].get(tid)
    if entry is None:
        return "crop is not compatible with this technique"
    dyn = entry.get("dynamic")
    if dyn is None:
        return {"kg_m2_cycle": entry["value"], "src": entry["src"], "kind": "parameter", "note": "", "max_cycles": entry["max_cycles"], "cycle_days": entry.get("cycle_days")}
    store = ctx.stats_open if dyn == "open_field" else ctx.stats_gh
    stat = store.get(cid)
    if isinstance(stat, str):
        return stat
    res, meta = stat
    if res["n"] < MIN_OBS or res["kg_m2"] is None:
        return f"only {res['n']} usable Qatar Open Data year(s) (need >= {MIN_OBS}); no value invented"
    base = {"src": entry["src"], "max_cycles": entry["max_cycles"], "cycle_days": entry.get("cycle_days"),
            "stat": res, "stat_meta": meta}
    if crop["aquacrop"].get("supported") and tid == "open_field" and pc.df is not None and ctx.ref_df is not None and sched is not None:
        try:
            soil_class = pc.soil.get("texture_class") if pc.soil else None
            plant_month = sched["start_month"] + 1
            aq = aquacrop_model.tomato_open_field(pc.cell, pc.df, plant_month, soil_class, res["t_ha"], ctx.ref_df)
            if aq["yield_t_ha_calibrated"]:
                return {**base, "kg_m2_cycle": aq["yield_t_ha_calibrated"] * 0.1, "src": "aquacrop", "kind": "aquacrop", "aquacrop": aq,
                        "plant_month": plant_month, "note": f"AquaCrop x calibration factor {aq['calibration_factor']:.3f}"}
        except Exception as exc:  # noqa: BLE001 - fall back openly
            base["note"] = f"AquaCrop failed ({str(exc)[:120]}); Qatar Open Data statistic used instead"
    return {**base, "kg_m2_cycle": res["kg_m2"], "kind": "official", "note": base.get("note", "")}


def build_options(ctx: Ctx, scenario_id: str) -> tuple[list[Option], list[dict], dict]:
    cat, req = ctx.cat, ctx.req
    scenario = cat["scenarios"][scenario_id]
    e_price, w_price, _, _ = _tariffs(ctx, scenario)
    ec = req.constraints.soil_ec_ds_m
    rain_frac = cat["defaults"]["effective_rain_fraction"]["value"]
    options: list[Option] = []
    excluded: list[dict] = []
    detail: dict = {}
    for pc in ctx.plots:
        for cid in req.crops:
            crop = cat["crops"][cid]
            for tid in req.techniques:
                tech = cat["techniques"][tid]
                label = {"plot": pc.id, "crop": cid, "technique": tid}
                if cid not in tech["compatible_crops"]:
                    excluded.append({**label, "kind": "incompatible", "reason": "incompatible crop x technique combination"})
                    continue
                if pc.clim is None:
                    excluded.append({**label, "kind": "data", "reason": "no climate data for this plot (NASA POWER unavailable and no cache)"})
                    continue
                # REQUIRED INPUTS: refuse the scenario rather than invent a number for it.
                need = catalog_mod.missing_for(cat, cid, tid)
                if need:
                    excluded.append({**label, "kind": "required_input",
                                     "reason": "Required input unavailable - enter value: " + "; ".join(n["label"] for n in need),
                                     "missing": need})
                    continue
                y0 = crop["yields"][tid]
                cycle_days = y0.get("cycle_days") or crop["cycle_days"]["value"]
                sched = crop_model.build_schedule(
                    pc.clim, crop["temp_limits_c"]["value"], tech["cooling_delta_c"]["value"], tech["heating_delta_c"]["value"],
                    tech["climate_controlled"], cycle_days, crop["turnaround_days"]["value"], y0["max_cycles"])
                if sched is None:
                    excluded.append({**label, "kind": "climate", "reason": "no thermally feasible growing window (monthly NASA POWER temperatures vs the crop's limits)"})
                    continue
                y = _yield_for(ctx, pc, cid, tid, sched)
                if isinstance(y, str):
                    excluded.append({**label, "kind": "data", "reason": y})
                    continue
                cycles = min(sched["cycles"], y["max_cycles"])
                sal = 1.0
                if tech["soil_based"]:
                    s = crop["salinity"]["value"]
                    sal = crop_model.salinity_factor(ec, s["threshold_ds_m"], s["slope_pct_per_ds_m"])
                yield_year = y["kg_m2_cycle"] * cycles * sal
                eff = tech["irrigation_efficiency"]["value"]
                coeff = tech["water_coefficient"]["value"]
                water_method = "FAO-56 Kc x ET0 (NASA POWER)"
                if y["kind"] == "aquacrop":
                    mm = y["aquacrop"]["plot"]["monthly_irrigation_mm"]
                    water = [m_mm / 1000.0 / eff * coeff for m_mm in mm]
                    extra = tech["extra_water_m3_m2_year"]["value"]
                    if extra:
                        for m in sched["run_months"]:
                            water[m] += extra * (sched["run_days"] / 365.0) * crop_model.MONTH_DAYS[m] / sched["run_days"]
                    water_method = "AquaCrop simulated irrigation"
                else:
                    water = crop_model.monthly_water_kc(pc.clim, sched, crop["stage_days"]["value"], crop["kc"]["value"], eff, coeff,
                                                        tech["extra_water_m3_m2_year"]["value"], bool(tech.get("rain_exposed")), rain_frac)
                energy = crop_model.monthly_energy(pc.clim, sched, tech["energy_kwh_m2_year"]["value"], tech["cooling_share"]["value"])
                price = req.prices.get(cid, crop["price_qar_kg"]["value"])
                # --- OpEx built from components, never a single unsourced QAR/m2/year figure
                comp = tech["opex_components"]
                labour = comp["labour_qar_m2_year"]["value"]
                maintenance = comp["maintenance_qar_m2_year"]["value"]
                seedlings = crop["seedlings_qar_m2_cycle"]["value"] * cycles
                nutrients = crop["nutrients_qar_m2_cycle"]["value"] * cycles
                water_cost = sum(water) * w_price
                energy_cost = sum(energy) * e_price
                opex_breakdown = {"labour": labour, "maintenance": maintenance, "seedlings": seedlings,
                                  "nutrients": nutrients, "water": water_cost, "electricity": energy_cost}
                opex = sum(opex_breakdown.values())
                opt = Option(cid, tid, rev_m2=yield_year * price, opex_m2=opex, capex_m2=tech["capex_qar_m2"]["value"], water_m=water, energy_m=energy,
                             yield_kg_m2=yield_year, water_cost_m2=water_cost, energy_cost_m2=energy_cost, plot=pc.id)
                options.append(opt)
                detail[(pc.id, cid, tid)] = {"cycles": cycles, "salinity_factor": sal, "price": price, "yield_kg_m2_cycle": y["kg_m2_cycle"],
                                             "yield_kind": y["kind"], "yield_src": y["src"], "yield_note": y.get("note", ""), "sched": sched,
                                             "water_method": water_method, "y": y, "opex_breakdown": opex_breakdown,
                                             "capex_m2": tech["capex_qar_m2"]["value"]}
    return options, excluded, detail


def build_problem(ctx: Ctx, scenario_id: str) -> tuple[Problem, list[dict], dict]:
    cat, req = ctx.cat, ctx.req
    c = req.constraints
    scenario = cat["scenarios"][scenario_id]
    options, excluded, detail = build_options(ctx, scenario_id)
    # Only techniques that actually produced an option are modelled: the rest were excluded for a stated
    # reason (incompatible, no growing window, or a required input with no defensible source).
    used_techs = sorted({o.technique for o in options})
    techs = {tid: TechIn(tid, cat["techniques"][tid]["min_area_m2"]["value"], cat["techniques"][tid]["fixed_capex_qar"]["value"], 0.0,
                         list(cat["techniques"][tid]["requires"])) for tid in used_techs}
    used_groups = sorted({g for tid in used_techs for g in cat["techniques"][tid]["requires"]})
    groups = {gid: GroupIn(gid, cat["groups"][gid]["fixed_capex_qar"]["value"], cat["groups"][gid]["fixed_opex_qar_year"]["value"])
              for gid in used_groups}
    lim = Limits(budget=c.budget_qar, water_year=c.water_m3_year * scenario["water_factor"], energy_year=c.energy_kwh_year,
                 water_month_max=c.water_peak_m3_month if c.water_peak_m3_month else float("inf"),
                 energy_month_max=c.energy_peak_kwh_month if c.energy_peak_kwh_month else float("inf"),
                 min_utilisation=c.min_land_utilisation, min_block_m2=c.min_block_m2,
                 horizon_years=c.horizon_years, objective=c.objective, max_crop_share=c.max_crop_share)
    problem = Problem([PlotIn(p.id, p.usable_m2) for p in ctx.plots], options, techs, groups, lim)
    return problem, excluded, detail


# ------------------------------------------------------------------------------------------------
# 3. solve + assemble
# ------------------------------------------------------------------------------------------------
def _summary(problem: Problem, metrics: dict) -> dict:
    s = finance.summarise(metrics["revenue"], metrics["opex"], metrics["capex"], metrics["water_m3"], metrics["energy_kwh"], problem.limits.horizon_years)
    d = s.to_dict()
    d["area_m2"] = metrics["area_m2"]
    d["yield_kg"] = metrics["yield_kg"]
    return d


def solve_scenario(ctx: Ctx, scenario_id: str, emit: Emit = _noop, with_context: bool = True) -> dict:
    t0 = time.perf_counter()
    cat = ctx.cat
    if scenario_id not in cat["scenarios"]:
        raise ValueError(f"Unknown scenario '{scenario_id}'")
    problem, excluded, detail = build_problem(ctx, scenario_id)
    emit({"event": "stage", "name": "model", "message": f"{len(problem.options)} plot x crop x technique options built, {len(excluded)} excluded (reasons kept)"})
    emit({"event": "stage", "name": "solver", "message": "Solving mixed-integer program (OR-Tools SCIP) with Dinkelbach iterations"})

    def on_iter(it: optimizer.Iteration) -> None:
        emit({"event": "iteration", **it.to_dict()})

    sol = optimizer.solve(problem, on_progress=on_iter)
    base = baseline_mod.best_baseline(problem, sol.utilisation_floor_used) if sol.alloc else None
    base_free = baseline_mod.best_single_option_free(problem, sol.utilisation_floor_used) if sol.alloc else None
    result = assemble(ctx, scenario_id, problem, sol, base, excluded, detail, with_context, base_free)
    result["timing_ms"] = round((time.perf_counter() - t0) * 1000)
    return result


def _baseline_out(cat: dict, problem: Problem, b: dict, definition: str) -> dict:
    return {"crop": b["crop"], "crop_name": cat["crops"][b["crop"]]["name"], "technique": b["technique"],
            "technique_name": cat["techniques"][b["technique"]]["name"], "scale_of_usable_area": b["scale"],
            "summary": _summary(problem, b["metrics"]), "definition": definition,
            "allocation": [{"plot_id": k[0], "area_m2": a} for k, a in b["alloc"].items()]}


def _comparison(summary: dict, bs: dict) -> list[dict]:
    rows = []
    for key, label, unit, better in (("roi", "5-year ROI", "%", "high"), ("revenue", "Annual revenue", "QAR", "high"), ("profit", "Annual profit", "QAR", "high"),
                                     ("capex", "CapEx", "QAR", "low"), ("opex", "Annual OpEx", "QAR", "low"), ("water_m3", "Water", "m3/year", "low"),
                                     ("energy_kwh", "Energy", "kWh/year", "low"), ("payback_years", "Payback", "years", "low"), ("net_gain", "5-year net cash flow", "QAR", "high")):
        a_v, b_v = summary.get(key), bs.get(key)
        rows.append({"metric": key, "label": label, "unit": unit, "optimized": a_v, "baseline": b_v,
                     "delta": (a_v - b_v) if (a_v is not None and b_v is not None) else None, "better": better})
    return rows


def assemble(ctx: Ctx, scenario_id: str, problem: Problem, sol: optimizer.Solution, base: dict | None, excluded: list[dict], detail: dict, with_context: bool,
             base_free: dict | None = None) -> dict:
    from .explain import explain
    cat = ctx.cat
    plots = {p.id: p for p in ctx.plots}
    H = problem.limits.horizon_years
    e_price, w_price, _, _ = _tariffs(ctx, cat["scenarios"][scenario_id])
    portfolio = []
    for (pid, cid, tid), a in sorted(sol.alloc.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1])):
        o = problem.option_for(pid, cid, tid)
        d = detail[(pid, cid, tid)]
        portfolio.append({
            "plot_id": pid, "plot_name": plots[pid].name, "crop": cid, "crop_name": cat["crops"][cid]["name"],
            "technique": tid, "technique_name": cat["techniques"][tid]["name"], "area_m2": a,
            "share_of_plot_usable": a / plots[pid].usable_m2, "share_of_total_usable": a / sum(p.usable_m2 for p in ctx.plots),
            "yield_kg_year": a * o.yield_kg_m2, "yield_kg_m2_year": o.yield_kg_m2, "cycles_per_year": d["cycles"],
            "price_qar_kg": d["price"], "revenue": a * o.rev_m2, "opex_variable": a * o.opex_m2, "capex_variable": a * o.capex_m2,
            "profit_contribution": a * (o.rev_m2 - o.opex_m2), "water_m3_year": a * o.water_year, "energy_kwh_year": a * o.energy_year,
            "yield_source": d["yield_kind"], "yield_src_id": d["yield_src"], "yield_note": d["yield_note"],
            "salinity_factor": d["salinity_factor"], "water_method": d["water_method"],
        })
    plot_rows = []
    for pc in ctx.plots:
        allocated = sum(a for (pid, _, _), a in sol.alloc.items() if pid == pc.id)
        infra = sorted(g for (pid, g) in sol.infra if pid == pc.id)
        builds = sorted(t for (pid, t) in sol.builds if pid == pc.id)
        shared = []
        for g in infra:
            users = [t for t in builds if g in problem.techs[t].requires]
            fg = problem.groups[g].fixed_capex
            shared.append({"group": g, "name": cat["groups"][g]["name"], "fixed_capex": fg, "used_by": users,
                           "capex_saved_by_sharing": fg * (len(users) - 1) if len(users) > 1 else 0.0})
        plot_rows.append({"plot_id": pc.id, "name": pc.name, "area_m2": pc.area_m2, "usable_m2": pc.usable_m2, "access_m2": pc.area_m2 - pc.usable_m2,
                          "allocated_m2": allocated, "unallocated_m2": pc.usable_m2 - allocated, "builds": builds, "infrastructure": shared,
                          "centroid": [pc.lon, pc.lat], "geometry_source": pc.geometry_source,
                          "registered_area_m2": pc.registered_area_m2, "geodesic_area_m2": pc.geodesic_area_m2})
    summary = _summary(problem, sol.metrics)
    baseline_out = comparison = None
    baseline_free_out = comparison_free = None
    if base is not None:
        baseline_out = _baseline_out(cat, problem, base, "One crop x one technique on every selected plot, using the whole usable area (scaled down uniformly only if the constraints force it)")
        comparison = _comparison(summary, baseline_out["summary"])
    if base_free is not None:
        baseline_free_out = _baseline_out(cat, problem, base_free, "Best farm with ONE crop x ONE technique, solved by the same MIP (free choice of plots and area)")
        comparison_free = _comparison(summary, baseline_free_out["summary"])
    ev = sol.metrics
    lim = problem.limits
    monthly = {"months": MONTH_NAMES, "water_m3": ev["water_month"], "energy_kwh": ev["energy_month"],
               "water_cap_m3": lim.water_cap_month() if lim.has_water_rate_limit() else None,
               "energy_cap_kwh": lim.energy_cap_month() if lim.has_energy_rate_limit() else None}
    opt_table = []
    for o in problem.options:
        profit_m2 = o.rev_m2 - o.opex_m2
        opt_table.append({"plot_id": o.plot, "crop": o.crop, "technique": o.technique, "profit_m2_year": profit_m2, "capex_m2": o.capex_m2,
                          "water_m3_m2_year": o.water_year, "energy_kwh_m2_year": o.energy_year, "yield_kg_m2_year": o.yield_kg_m2,
                          "marginal_roi": (H * profit_m2 - o.capex_m2) / o.capex_m2 if o.capex_m2 else None,
                          "profit_per_m3_water": profit_m2 / o.water_year if o.water_year > 1e-9 else None})
    out = {
        "scenario": {"id": scenario_id, **{k: v for k, v in cat["scenarios"][scenario_id].items() if k != "src"}},
        "status": sol.status,
        "objective": lim.objective,
        "solver": {**sol.solver, "iterations": [it.to_dict() for it in sol.iterations], "utilisation_floor_requested": lim.min_utilisation,
                   "utilisation_floor_used": sol.utilisation_floor_used, "ratio_outcome": sol.ratio_outcome},
        "summary": summary,
        "portfolio": portfolio,
        "plots": plot_rows,
        "baseline": baseline_out,
        "comparison": comparison,
        "baseline_free": baseline_free_out,
        "comparison_free": comparison_free,
        "monthly": monthly,
        "limits": {"budget_qar": lim.budget, "water_m3_year": lim.water_year, "energy_kwh_year": lim.energy_year,
                   "water_peak_m3_month": None if lim.water_month_max == float("inf") else lim.water_month_max,
                   "energy_peak_kwh_month": None if lim.energy_month_max == float("inf") else lim.energy_month_max,
                   "usable_m2": sum(p.usable_m2 for p in ctx.plots),
                   "total_m2": sum(p.area_m2 for p in ctx.plots)},
        "options": opt_table,
        "excluded": excluded,
        "limiting": diagnose(problem, sol, sum(p.usable_m2 for p in ctx.plots)),
        "warnings": list(sol.warnings) + list(ctx.notes),
        "missing_inputs": ctx.missing_inputs,
        "accepted_planning_profile": ctx.req.accept_planning_profile,
    }
    out["explanations"] = explain(out, problem, sol, cat, detail) if sol.alloc else []
    out["data_panel"] = [r.to_dict() for r in build_data_panel(ctx, problem, detail, scenario_id, sol, _tariffs(ctx, cat["scenarios"][scenario_id]))]
    if with_context:
        out["context"] = [{"plot_id": pc.id, "market_access": pc.access, "error": pc.access_error} for pc in ctx.plots]
    return out


# ------------------------------------------------------------------------------------------------
# 4. data & assumptions panel
# ------------------------------------------------------------------------------------------------
