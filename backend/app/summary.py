"""The decision-oriented headline: 2-4 sentences and 3 quantitative reasons, from solved outputs only.

Every sentence is assembled from numbers the model computed. Nothing is asserted that the optimizer did not
produce, and no reason appears unless the quantity behind it was measured in this solution.
"""
from __future__ import annotations

from .optimizer import MONTHS, Problem, Solution

MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TIGHT = 0.995


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def optimal_management(out: dict, problem: Problem, sol: Solution, cat: dict, detail: dict) -> dict:
    """Return {headline: [sentences], reasons: [{label, value, detail}]}."""
    s = out["summary"]
    lim = problem.limits
    usable = out["limits"]["usable_m2"]
    rows = out["portfolio"]
    H = lim.horizon_years

    if not rows:
        return {
            "headline": [out["limiting"]["headline"] if out.get("limiting") else
                         "No configuration satisfies the stated limits, so no land was allocated."],
            "reasons": [],
        }

    # ---- sentence 1: what to build, largest blocks first
    by_block: dict[tuple[str, str], float] = {}
    for r in rows:
        by_block[(r["crop"], r["technique"])] = by_block.get((r["crop"], r["technique"]), 0.0) + r["area_m2"]
    ordered = sorted(by_block.items(), key=lambda kv: -kv[1])
    named = [f"{_pct(a / usable)} to {cat['crops'][c]['name'].lower()} under {cat['techniques'][t]['name'].lower()}"
             for (c, t), a in ordered[:3]]
    first = "Allocate " + (", ".join(named[:-1]) + " and " + named[-1] if len(named) > 1 else named[0]) + "."

    # ---- sentence 2: what the rest of the land does
    access = sum(p["access_m2"] for p in out["plots"])
    unalloc = max(0.0, usable - s["area_m2"])
    rest = []
    if access > 0:
        rest.append(f"{_pct(access / out['limits']['total_m2'])} of the site is kept for access and shared infrastructure")
    if unalloc > 0.01 * usable:
        rest.append(f"{unalloc:,.0f} m2 stays unplanted")
    second = (" and ".join(rest).capitalize() + ".") if rest else "The remaining area carries access and shared infrastructure."

    # ---- sentence 3: what it earns, against which binding limit
    binding = [l for l in (out.get("limiting") or {}).get("limits", []) if l.get("binding") and l["key"] != "land"]
    floor = out["solver"]["utilisation_floor_used"]
    floor_binds = floor > 0 and s["area_m2"] <= floor * usable * 1.005
    roi_txt = "an undefined return" if s["roi"] is None else f"a {H}-year return of {s['roi'] * 100:.0f}%"
    money = (f"This earns QAR {s['profit']:,.0f} a year on QAR {s['capex']:,.0f} of capital, {roi_txt}"
             if s["profit"] >= 0 else
             f"This loses QAR {abs(s['profit']):,.0f} a year against QAR {s['capex']:,.0f} of capital, {roi_txt}")
    if binding:
        money += f", limited by {binding[0]['label'].lower()}."
    elif floor_binds:
        money += f", with the {floor:.0%} minimum land-utilisation rule deciding how much is planted."
    else:
        money += ", with no resource limit binding."
    sentences = [first, second, money]

    # ---- sentence 4 only when it carries a decision
    # What the model would rather have built, and the arithmetic that ruled it out.
    chosen = {(r["crop"], r["technique"]) for r in rows}
    best_margin = None
    for m in out.get("matrix", []):
        if m.get("state") != "modelled" or m.get("profit_m2_year") is None:
            continue
        if (m["crop"], m["technique"]) in chosen:
            continue
        if best_margin is None or m["profit_m2_year"] > best_margin["profit_m2_year"]:
            best_margin = m
    required_m2 = floor * usable if floor > 0 else s["area_m2"]
    if (best_margin and best_margin["profit_m2_year"] > 0 and best_margin.get("capex_m2")
            and required_m2 > 0 and lim.budget < float("inf")):
        need = required_m2 * best_margin["capex_m2"]
        if need > lim.budget:
            sentences.append(
                f"{best_margin['crop_name']} under {best_margin['technique_name'].lower()} earns more per square "
                f"metre (QAR {best_margin['profit_m2_year']:,.1f} a year) but costs QAR {best_margin['capex_m2']:,.0f}/m2, "
                f"so covering the required {required_m2:,.0f} m2 that way would need QAR {need:,.0f} against a "
                f"QAR {lim.budget:,.0f} budget.")
    if s["profit"] < 0 and len(sentences) < 4:
        sentences.append(
            f"No configuration repays its capital within {H} years at the current cost and price figures, so the "
            "plan shown is the least unprofitable one the constraints allow.")
    elif s["profit"] >= 0 and s["payback_years"] is not None and len(sentences) < 4:
        sentences.append(f"Capital is repaid after {s['payback_years']:.1f} years.")

    # ---- exactly three quantitative reasons, each measured in this solution
    reasons: list[dict] = []
    w_used, w_cap = s["water_m3"], lim.water_year
    if w_cap and w_cap != float("inf"):
        reasons.append({"label": "Water constraint", "value": f"{_pct(w_used / w_cap)} utilised",
                        "detail": f"{w_used:,.0f} m3 of {w_cap:,.0f} m3 a year"})
    e_used, e_cap = s["energy_kwh"], lim.energy_kwh_year if hasattr(lim, "energy_kwh_year") else lim.energy_year
    if e_cap and e_cap != float("inf"):
        reasons.append({"label": "Electricity", "value": f"{_pct(e_used / e_cap)} utilised",
                        "detail": f"{e_used:,.0f} kWh of {e_cap:,.0f} kWh a year"})
    if lim.budget and lim.budget != float("inf"):
        reasons.append({"label": "Budget", "value": f"{_pct(s['capex'] / lim.budget)} committed",
                        "detail": f"QAR {s['capex']:,.0f} of QAR {lim.budget:,.0f}"})

    saved = sum(g["capex_saved_by_sharing"] for p in out["plots"] for g in p["infrastructure"])
    if saved > 0:
        reasons.insert(0, {"label": "Shared infrastructure", "value": f"saves QAR {saved:,.0f}",
                           "detail": "charged once per plot instead of once per production block"})

    # the block that actually earns most per m2, straight from the solution
    best_block = max(rows, key=lambda r: (r["profit_contribution"] / r["area_m2"]) if r["area_m2"] else -1e9)
    if best_block["area_m2"] > 0:
        per_m2 = best_block["profit_contribution"] / best_block["area_m2"]
        reasons.insert(0, {
            "label": f"{cat['crops'][best_block['crop']]['name']} under {cat['techniques'][best_block['technique']]['name'].lower()}",
            "value": f"QAR {per_m2:,.1f} per m2 a year",
            "detail": ("highest operating margin per square metre in this plan" if per_m2 >= 0 else
                       "the least negative margin per square metre available within the budget")})
    if floor_binds:
        reasons.insert(0, {"label": "Land-utilisation rule", "value": f"{floor:.0%} must be planted",
                           "detail": f"{required_m2:,.0f} m2 of {usable:,.0f} m2 usable, which decides the cheapest "
                                     "system the budget can cover"})

    peak = max(range(MONTHS), key=lambda m: out["monthly"]["water_m3"][m])
    if out["monthly"]["water_m3"][peak] > 0 and len(reasons) < 3:
        reasons.append({"label": f"Peak water month ({MONTH[peak]})",
                        "value": f"{out['monthly']['water_m3'][peak]:,.0f} m3",
                        "detail": "when the crop calendar concentrates irrigation demand"})

    return {"headline": sentences, "reasons": reasons[:3]}
