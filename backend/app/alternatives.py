"""Distinct optimized configurations, all from the SAME mixed-integer model.

Every alternative inherits the portfolio-composition rules of the base problem, so each one is itself a real
multi-part portfolio rather than a single block, and each is solved independently.

Nothing here ranks options by a made-up score. Each alternative is a genuine optimum of the same MIP under a
different objective or a different epsilon-constraint, so every row in the comparison is a plan the solver
actually proved optimal for the question it was asked:

    Best 5-year ROI        maximise N/CapEx                      (Dinkelbach)
    Best 5-year cash flow  maximise N = 5*profit - CapEx         (single MIP)
    Water-efficient        maximise N subject to water <= a x the water the cash-flow optimum used
    Lower CapEx            maximise N subject to CapEx <= b x the CapEx the cash-flow optimum used

The epsilon-constraint variants are the standard way to trace a trade-off frontier: they do not change the
model, only tighten one resource, so the answer is still a proved optimum. Two alternatives can legitimately
coincide - when they do it is reported rather than perturbed into looking different.
"""
from __future__ import annotations

from dataclasses import replace

from . import optimizer
from .finance import summarise

WATER_FACTOR = 0.6   # "water-efficient" means at most this share of the unconstrained optimum's water
CAPEX_FACTOR = 0.5   # "lower CapEx" means at most this share of the unconstrained optimum's capital


def _alloc_rows(problem: optimizer.Problem, sol: optimizer.Solution, cat: dict, detail: dict) -> list[dict]:
    rows = []
    for (pid, cid, tid), area in sorted(sol.alloc.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1])):
        o = problem.option_for(pid, cid, tid)
        d = detail.get((pid, cid, tid), {})
        rows.append({
            "plot_id": pid, "crop": cid, "crop_name": cat["crops"][cid]["name"],
            "technique": tid, "technique_name": cat["techniques"][tid]["name"],
            "area_m2": area, "yield_kg_year": area * o.yield_kg_m2,
            "revenue": area * o.rev_m2, "profit_contribution": area * (o.rev_m2 - o.opex_m2),
            "water_m3_year": area * o.water_year, "energy_kwh_year": area * o.energy_year,
            "yield_source": d.get("yield_kind", "parameter"),
        })
    return rows


def _record(key: str, label: str, question: str, problem: optimizer.Problem, sol: optimizer.Solution,
            cat: dict, detail: dict, usable_m2: float, note: str = "") -> dict:
    from .limiting import diagnose
    ev = sol.metrics
    s = summarise(ev["revenue"], ev["opex"], ev["capex"], ev["water_m3"], ev["energy_kwh"],
                  problem.limits.horizon_years)
    out = s.to_dict()
    out.update(area_m2=ev["area_m2"], yield_kg=ev["yield_kg"])
    return {
        "key": key, "label": label, "question": question, "note": note,
        "status": sol.status, "ratio_outcome": sol.ratio_outcome,
        "summary": out,
        "portfolio": _alloc_rows(problem, sol, cat, detail),
        "limiting": diagnose(problem, sol, usable_m2),
        "warnings": list(sol.warnings),
        "crops": sorted({cid for (_p, cid, _t) in sol.alloc}),
        "techniques": sorted({tid for (_p, _c, tid) in sol.alloc}),
    }


def _signature(sol: optimizer.Solution) -> tuple:
    """Two plans are the same configuration when they allocate the same areas to the same blocks."""
    return tuple(sorted((p, c, t, round(a, 3)) for (p, c, t), a in sol.alloc.items()))


def build(problem: optimizer.Problem, cat: dict, detail: dict, usable_m2: float,
          time_limit_s: float = 30.0) -> list[dict]:
    """Solve the four questions and return them in a stable order, marking any that coincide."""
    out: list[dict] = []
    sigs: dict[tuple, str] = {}

    def add(key, label, question, lim, note=""):
        sub = replace(problem, limits=lim)
        sol = optimizer.solve(sub, time_limit_s=time_limit_s)
        # An empty allocation is not a configuration. It means the restriction left nothing worth building,
        # which is reported as such rather than shown as a farm with zeroes in every column.
        if not sol.alloc:
            out.append({"key": key, "label": label, "question": question, "note": note or "",
                        "status": sol.status, "summary": None, "portfolio": [], "limiting": None,
                        "warnings": list(sol.warnings), "crops": [], "techniques": [],
                        "unavailable": (note + " " if note else "") +
                        "Under that restriction the solver found nothing worth building: every remaining "
                        "option loses money, so the best plan is to build none of it."})
            return None
        rec = _record(key, label, question, sub, sol, cat, detail, usable_m2, note)
        sig = _signature(sol)
        if sig in sigs:
            rec["same_as"] = sigs[sig]
        else:
            sigs[sig] = key
        out.append(rec)
        return sol

    base = problem.limits
    add("roi", "Best 5-year ROI", "Which plan returns the most per riyal invested?",
        replace(base, objective="roi"))
    cash = add("cash", "Best 5-year cash flow", "Which plan produces the largest total return?",
               replace(base, objective="net_profit"))

    if cash is not None and cash.alloc:
        w = cash.metrics["water_m3"]
        c = cash.metrics["capex"]
        add("water", "Water-efficient",
            "What is the best plan that uses substantially less water?",
            replace(base, objective="net_profit", water_year=min(base.water_year, w * WATER_FACTOR)),
            note=f"Water capped at {WATER_FACTOR:.0%} of the {w:,.0f} m3 the best-cash-flow plan uses.")
        add("capex", "Lower CapEx",
            "What is the best plan that needs substantially less capital?",
            replace(base, objective="net_profit", budget=min(base.budget, c * CAPEX_FACTOR)),
            note=f"CapEx capped at {CAPEX_FACTOR:.0%} of the QAR {c:,.0f} the best-cash-flow plan needs.")
    else:
        for key, label, question in (("water", "Water-efficient", "What is the best plan that uses substantially less water?"),
                                     ("capex", "Lower CapEx", "What is the best plan that needs substantially less capital?")):
            out.append({"key": key, "label": label, "question": question, "note": "",
                        "status": "INFEASIBLE", "summary": None, "portfolio": [], "limiting": None,
                        "warnings": [], "crops": [], "techniques": [],
                        "unavailable": "Derived from the best-cash-flow plan, which has no feasible solution here."})
    return out
