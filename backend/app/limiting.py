"""Why is land left unallocated? Answers it from the solved model, exactly and without guessing.

Unallocated land is a legitimate optimizer output - a budget of QAR 1.2 M cannot develop 170 ha - but the
result is only honest if it says which limit stopped it and what it would take to go further. Every number
here comes from the solution or from the per-m2 coefficients the solver actually used.
"""
from __future__ import annotations

from .optimizer import MONTHS, Problem, Solution

MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TIGHT = 0.995  # a constraint counts as binding at 99.5% of its limit


def _marginal_option(problem: Problem, sol: Solution):
    """The option carrying most of the allocation: the one that would be expanded first."""
    if not sol.alloc:
        return None
    (pid, crop, tech), _ = max(sol.alloc.items(), key=lambda kv: kv[1])
    return problem.option_for(pid, crop, tech)


def diagnose(problem: Problem, sol: Solution, usable_m2: float) -> dict:
    """Return the limiting factor, the headroom of every limit, and what each would support."""
    lim, ev = problem.limits, sol.metrics
    allocated = ev["area_m2"]
    unallocated = max(0.0, usable_m2 - allocated)
    out: dict = {
        "usable_m2": usable_m2,
        "allocated_m2": allocated,
        "unallocated_m2": unallocated,
        "unallocated_share": (unallocated / usable_m2) if usable_m2 > 0 else 0.0,
        "limits": [],
        "limiting_factor": None,
        "headline": "",
        "land_supported_m2": None,
    }
    if allocated <= 0:
        out["headline"] = "No land was allocated at all."
        return out

    o = _marginal_option(problem, sol)
    rows = []

    def add(key, label, used, cap, per_m2, note=""):
        if cap is None or cap == float("inf") or per_m2 in (None, 0):
            supported = None
        else:
            supported = cap / per_m2
        rows.append({"key": key, "label": label, "used": used, "limit": cap,
                     "utilisation": (used / cap) if cap not in (None, 0, float("inf")) else None,
                     "land_supported_m2": supported, "binding": bool(cap) and cap != float("inf") and used >= TIGHT * cap,
                     "note": note})

    if o is not None:
        add("budget", "Budget (CapEx)", ev["capex"], lim.budget, o.capex_m2,
            "Fixed technique and infrastructure costs are charged on top, so the area shown is an upper bound.")
        add("water_year", "Water, annual volume", ev["water_m3"], lim.water_year, o.water_year)
        add("energy_year", "Electricity, annual", ev["energy_kwh"], lim.energy_year, o.energy_year)
        if lim.has_water_rate_limit():
            peak_m = max(range(MONTHS), key=lambda m: ev["water_month"][m])
            share = ev["water_month"][peak_m] / ev["water_m3"] if ev["water_m3"] > 0 else 0
            add("water_month", f"Water in the peak month ({MONTH[peak_m]})", ev["water_month"][peak_m],
                lim.water_cap_month(), o.water_year * share if share else None,
                f"This crop draws {share:.0%} of its yearly water in {MONTH[peak_m]}.")
        if lim.has_energy_rate_limit():
            peak_m = max(range(MONTHS), key=lambda m: ev["energy_month"][m])
            share = ev["energy_month"][peak_m] / ev["energy_kwh"] if ev["energy_kwh"] > 0 else 0
            add("energy_month", f"Electricity in the peak month ({MONTH[peak_m]})", ev["energy_month"][peak_m],
                lim.energy_cap_month(), o.energy_year * share if share else None,
                f"This system uses {share:.0%} of its yearly electricity in {MONTH[peak_m]}.")
    add("land", "Usable land", allocated, usable_m2, 1.0)
    out["limits"] = rows

    binding = [r for r in rows if r["binding"] and r["key"] != "land"]
    land_full = allocated >= TIGHT * usable_m2
    if land_full:
        out["limiting_factor"] = "land"
        out["headline"] = "All usable land is allocated."
        return out

    # the limit that supports the least land is what actually stops expansion
    scored = [r for r in rows if r["land_supported_m2"] is not None and r["key"] != "land"]
    tightest = min(scored, key=lambda r: r["land_supported_m2"]) if scored else None
    chosen = binding[0] if binding else tightest
    if chosen is None:
        out["headline"] = f"{unallocated:,.0f} m2 is unallocated and no resource limit is binding."
        return out
    out["limiting_factor"] = chosen["key"]
    out["land_supported_m2"] = chosen["land_supported_m2"]
    share = out["unallocated_share"]
    if chosen["key"] == "budget":
        need = (usable_m2 * (o.capex_m2 if o else 0)) if o else None
        extra = f" Developing all {usable_m2:,.0f} m2 the same way would cost roughly QAR {need:,.0f}." if need else ""
        out["headline"] = (f"{share:.0%} of the selected land ({unallocated:,.0f} m2) is unallocated because the "
                           f"budget is the binding limit: QAR {lim.budget:,.0f} buys about "
                           f"{chosen['land_supported_m2']:,.0f} m2 of this system.{extra}")
    elif chosen["key"] in ("water_month", "energy_month"):
        out["headline"] = (f"{share:.0%} of the selected land ({unallocated:,.0f} m2) is unallocated because the stated "
                           f"{'water' if 'water' in chosen['key'] else 'electricity'} delivery capacity for a single "
                           f"month is reached. Raise or remove that monthly capacity if only the annual total really "
                           f"limits you.")
    elif chosen["key"] in ("water_year", "energy_year"):
        res = "water" if "water" in chosen["key"] else "electricity"
        out["headline"] = (f"{share:.0%} of the selected land ({unallocated:,.0f} m2) is unallocated because the annual "
                           f"{res} allowance supports about {chosen['land_supported_m2']:,.0f} m2 of this system.")
    else:
        out["headline"] = f"{share:.0%} of the selected land is unallocated; {chosen['label']} is the binding limit."
    return out
