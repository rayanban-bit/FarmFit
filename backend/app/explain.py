"""'Why this configuration?' - explanations generated ONLY from solved model outputs.

Every sentence is assembled from numbers that exist in the result (allocation, per-option economics,
which constraints are tight in the solution, infrastructure sharing, baseline). Nothing is asserted that the
model did not compute; causal wording is limited to comparisons of computed quantities and to constraints
that are verifiably at their limit in the solution.
"""
from __future__ import annotations

from .optimizer import MONTHS, Problem, Solution

MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TIGHT = 0.995


def _rank(values: list[float | None], v: float | None, higher_is_better: bool = True) -> int | None:
    if v is None:
        return None
    pool = [x for x in values if x is not None]
    return 1 + sum(1 for x in pool if (x > v + 1e-9 if higher_is_better else x < v - 1e-9))


def binding_constraints(out: dict, problem: Problem, sol: Solution) -> dict:
    lim, ev = problem.limits, sol.metrics
    b: dict = {"budget": None, "water_annual": None, "energy_annual": None, "water_months": [], "energy_months": [], "land_plots": [], "utilisation_floor": False}
    if lim.budget < float("inf") and ev["capex"] >= TIGHT * lim.budget:
        b["budget"] = ev["capex"] / lim.budget
    if lim.water_year < float("inf"):
        if ev["water_m3"] >= TIGHT * lim.water_year:
            b["water_annual"] = ev["water_m3"] / lim.water_year
        cap = lim.water_cap_month()
        b["water_months"] = [m for m in range(MONTHS) if ev["water_month"][m] >= TIGHT * cap]
    if lim.energy_year < float("inf"):
        if ev["energy_kwh"] >= TIGHT * lim.energy_year:
            b["energy_annual"] = ev["energy_kwh"] / lim.energy_year
        cap = lim.energy_cap_month()
        b["energy_months"] = [m for m in range(MONTHS) if ev["energy_month"][m] >= TIGHT * cap]
    for p in out["plots"]:
        if p["unallocated_m2"] <= 0.005 * p["usable_m2"]:
            b["land_plots"].append(p["plot_id"])
    tot = out["limits"]["usable_m2"]
    if sol.utilisation_floor_used > 0 and ev["area_m2"] <= sol.utilisation_floor_used * tot * 1.005:
        b["utilisation_floor"] = True
    return b


def explain(out: dict, problem: Problem, sol: Solution, cat: dict, detail: dict) -> list[dict]:
    items: list[dict] = []
    crops, techs = cat["crops"], cat["techniques"]
    s = out["summary"]
    H = problem.limits.horizon_years
    nm = lambda c, t: f"{crops[c]['name']} ({techs[t]['name'].lower()})"  # noqa: E731
    bind = binding_constraints(out, problem, sol)
    opts = out["options"]

    # 1. what the solver did
    it = out["solver"]["iterations"]
    if out["objective"] == "roi":
        items.append({"kind": "method", "text": f"The portfolio is the exact optimum of the {H}-year ROI problem: Dinkelbach's algorithm converged in {len(it)} MIP solve(s) "
                      f"to lambda = {it[-1]['lambda'] * 100:.1f}% and the final residual F(lambda) = {it[-1]['F']:.2e}.", "evidence": {"iterations": len(it)}})

    # 2. every block: share + computed reasons
    for row in out["portfolio"]:
        pid, c, t = row["plot_id"], row["crop"], row["technique"]
        same_plot = [o for o in opts if o["plot_id"] == pid]
        this = next(o for o in same_plot if o["crop"] == c and o["technique"] == t)
        r_roi = _rank([o["marginal_roi"] for o in same_plot], this["marginal_roi"])
        r_w = _rank([o["profit_per_m3_water"] for o in same_plot], this["profit_per_m3_water"])
        parts = [f"{nm(c, t)} on {row['plot_name']} received {row['area_m2']:,.0f} m2 ({row['share_of_plot_usable']:.0%} of the plot's usable area)."]
        if this["marginal_roi"] is not None:
            parts.append(f"Its stand-alone {H}-year return on its own per-m2 CapEx is {this['marginal_roi'] * 100:.0f}% (rank {r_roi} of {len(same_plot)} options on this plot)")
        if this["profit_per_m3_water"] is not None:
            parts[-1] += f" and it earns QAR {this['profit_per_m3_water']:.1f} of operating profit per m3 of water (rank {r_w} of {len(same_plot)})."
        else:
            parts[-1] += "."
        items.append({"kind": "block", "text": " ".join(parts), "evidence": {"plot": pid, "crop": c, "technique": t, "area_m2": row["area_m2"], "rank_roi": r_roi, "rank_profit_per_water": r_w}})

    # 3. binding constraints
    if bind["budget"]:
        items.append({"kind": "constraint", "text": f"The budget is binding: CapEx uses {bind['budget']:.1%} of QAR {problem.limits.budget:,.0f}. The solver therefore trades area between systems by return per QAR of CapEx.", "evidence": bind})
    if bind["water_months"] or bind["water_annual"]:
        months = ", ".join(MONTH[m] for m in bind["water_months"])
        txt = "Water is binding" + (f" in {months} (monthly water at the limit of {problem.limits.water_cap_month():,.0f} m3)" if months else "") + (
            f"; annual use is {bind['water_annual']:.1%} of the {problem.limits.water_year:,.0f} m3 available" if bind["water_annual"] else "") + "."
        items.append({"kind": "constraint", "text": txt, "evidence": {"months": [MONTH[m] for m in bind["water_months"]]}})
    if bind["energy_months"] or bind["energy_annual"]:
        months = ", ".join(MONTH[m] for m in bind["energy_months"])
        items.append({"kind": "constraint", "text": "Energy is binding" + (f" in {months}" if months else "") + f" (annual use {sol.metrics['energy_kwh']:,.0f} kWh of {problem.limits.energy_year:,.0f}).", "evidence": {}})
    if bind["land_plots"]:
        items.append({"kind": "constraint", "text": f"Usable land is fully allocated on: {', '.join(bind['land_plots'])}.", "evidence": {"plots": bind["land_plots"]}})
    if bind["utilisation_floor"]:
        items.append({"kind": "constraint", "text": f"The minimum land-utilisation floor ({sol.utilisation_floor_used:.0%}) is active: the solver would otherwise use less land.", "evidence": {}})
    if not any([bind["budget"], bind["water_months"], bind["water_annual"], bind["energy_months"], bind["energy_annual"], bind["land_plots"], bind["utilisation_floor"]]):
        items.append({"kind": "constraint", "text": "No resource limit is binding in this solution; the design is driven by option economics and the minimum-scale rules.", "evidence": {}})

    # 4. shared infrastructure
    for p in out["plots"]:
        for g in p["infrastructure"]:
            if g["capex_saved_by_sharing"] > 0:
                users = ", ".join(techs[t]["name"].lower() for t in g["used_by"])
                items.append({"kind": "sharing", "text": f"{g['name']} on {p['name']} is built once and shared by {len(g['used_by'])} systems ({users}), avoiding QAR {g['capex_saved_by_sharing']:,.0f} of duplicated fixed CapEx.",
                              "evidence": g})

    # 5. baseline comparison
    any_base = False
    for key, tag in (("baseline", "whole-plot single-option baseline"), ("baseline_free", "best single-option plan (free plots/area)")):
        b = out.get(key)
        if not b:
            continue
        any_base = True
        bs = b["summary"]
        if s["roi"] is not None and bs["roi"] is not None:
            same = (abs(s["roi"] - bs["roi"]) < 1e-6 and abs(s["profit"] - bs["profit"]) < 1e-3 * max(1.0, abs(bs["profit"])))
            tail = " The optimum is itself a single-option plan here, so the two coincide." if same else ""
            items.append({"kind": "baseline", "text": f"Against the {tag} ({b['crop_name']}, {b['technique_name'].lower()}, {b['scale_of_usable_area']:.0%} of usable area), "
                          f"the optimized portfolio changes {H}-year ROI from {bs['roi'] * 100:.1f}% to {s['roi'] * 100:.1f}% and annual profit from QAR {bs['profit']:,.0f} to QAR {s['profit']:,.0f}." + tail,
                          "evidence": {"baseline": key, "baseline_roi": bs["roi"], "optimized_roi": s["roi"]}})
    if not any_base:
        items.append({"kind": "baseline", "text": "No single crop x technique satisfies all constraints, so no baseline could be computed.", "evidence": {}})

    # 6. attractive options that were limited
    chosen = {(r["plot_id"], r["crop"], r["technique"]) for r in out["portfolio"]}
    ranked = sorted([o for o in opts if o["marginal_roi"] is not None], key=lambda o: -o["marginal_roi"])[:3]
    for o in ranked:
        key = (o["plot_id"], o["crop"], o["technique"])
        opt = problem.option_for(*key)
        uses_binding_water = [MONTH[m] for m in bind["water_months"] if opt.water_m[m] > 1e-9]
        row = next((r for r in out["portfolio"] if (r["plot_id"], r["crop"], r["technique"]) == key), None)
        if key not in chosen:
            why = []
            if uses_binding_water:
                why.append(f"it draws water in {', '.join(uses_binding_water)}, where the water limit is binding")
            if bind["budget"]:
                why.append("the budget is exhausted")
            if bind["energy_months"] and any(opt.energy_m[m] > 1e-9 for m in bind["energy_months"]):
                why.append("it uses energy in months where the energy limit is binding")
            items.append({"kind": "not_chosen", "text": f"{nm(o['crop'], o['technique'])} on {o['plot_id']} has a high stand-alone return ({o['marginal_roi'] * 100:.0f}%) but was not selected"
                          + (": " + "; ".join(why) + "." if why else " - the solver found a better combination once fixed infrastructure and shared limits are counted."),
                          "evidence": {"marginal_roi": o["marginal_roi"]}})
        elif row and row["share_of_plot_usable"] < 0.99 and uses_binding_water:
            items.append({"kind": "limited", "text": f"{nm(o['crop'], o['technique'])} on {o['plot_id']} is limited to {row['share_of_plot_usable']:.0%} of the plot: it draws water in {', '.join(uses_binding_water)}, where the water limit is binding.", "evidence": {}})

    # 7. exclusions
    if out["excluded"]:
        reasons: dict[str, int] = {}
        for e in out["excluded"]:
            reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
        items.append({"kind": "excluded", "text": "Options removed before optimization: " + "; ".join(f"{n} x {r}" for r, n in reasons.items()) + ".", "evidence": reasons})
    return items
