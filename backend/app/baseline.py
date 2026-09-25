"""Baseline: ONE crop x ONE technique spread uniformly over the usable area of all plots.

For every (crop, technique) pair available on every plot, the largest uniform scale s in (0, 1] that
satisfies every constraint of the optimizer (budget, monthly + annual water/energy, minimum technique
scale, minimum block, the same utilisation floor and crop-share cap) is computed in closed form (all
constraints are linear in s once the infrastructure is fixed). s = 1 means the whole usable plot; s < 1
is reported explicitly as "scaled to fit". The best baseline by the same objective is returned, so
'optimized vs baseline' is a fair comparison: the baseline is always a feasible point of the optimizer's
own problem, hence optimum >= baseline.
"""
from __future__ import annotations

from dataclasses import replace

from .optimizer import MONTHS, Problem, evaluate, solve_with_floor

INF = float("inf")


def pair_baseline(problem: Problem, crop: str, tech: str, util_floor: float) -> dict | None:
    lim = problem.limits
    t = problem.techs[tech]
    opts = []
    for p in problem.plots:
        o = problem.option_for(p.id, crop, tech)
        if o is None:
            return None  # not allowed on every plot -> not a whole-farm single-option baseline
        opts.append((p, o))
    total = sum(p.usable_m2 for p, _ in opts)
    fixed_cap = sum(t.fixed_capex + sum(problem.groups[g].fixed_capex for g in t.requires) for _ in opts)
    var_cap = sum(o.capex_m2 * p.usable_m2 for p, o in opts)
    water_m = [sum(o.water_m[m] * p.usable_m2 for p, o in opts) for m in range(MONTHS)]
    energy_m = [sum(o.energy_m[m] * p.usable_m2 for p, o in opts) for m in range(MONTHS)]

    s_max = 1.0
    if lim.budget < INF and var_cap > 0:
        s_max = min(s_max, (lim.budget - fixed_cap) / var_cap)
    elif lim.budget < INF and fixed_cap > lim.budget:
        return None
    wc, ec = lim.water_cap_month(), lim.energy_cap_month()
    for m in range(MONTHS):
        if water_m[m] > 0 and lim.water_year < INF:
            s_max = min(s_max, wc / water_m[m])
        if energy_m[m] > 0 and lim.energy_year < INF:
            s_max = min(s_max, ec / energy_m[m])
    if sum(water_m) > 0 and lim.water_year < INF:
        s_max = min(s_max, lim.water_year / sum(water_m))
    if sum(energy_m) > 0 and lim.energy_year < INF:
        s_max = min(s_max, lim.energy_year / sum(energy_m))
    if lim.max_crop_share < 1.0:
        s_max = min(s_max, lim.max_crop_share)
    s_max = min(s_max * (1 - 1e-9), 1.0)  # safety margin against feasibility tolerances
    if s_max <= 0 or s_max < util_floor:
        return None
    if any(s_max * p.usable_m2 < max(t.min_area_m2, lim.min_block_m2) for p, _ in opts):
        return None
    alloc = {(p.id, crop, tech): s_max * p.usable_m2 for p, _ in opts}
    return {"crop": crop, "technique": tech, "scale": s_max, "alloc": alloc, "metrics": evaluate(problem, alloc), "area_total": total}


def best_baseline(problem: Problem, util_floor: float) -> dict | None:
    """Best single-option baseline by the problem's objective (ROI, or net gain)."""
    best = None
    for crop, tech in problem.pairs():
        cand = pair_baseline(problem, crop, tech, util_floor)
        if cand is None:
            continue
        ev = cand["metrics"]
        score = ev["roi"] if problem.limits.objective == "roi" else ev["net_gain"]
        if score is None:
            continue
        cand["score"] = score
        if best is None or score > best["score"]:
            best = cand
    return best


def all_baselines(problem: Problem, util_floor: float) -> list[dict]:
    out = []
    for crop, tech in problem.pairs():
        c = pair_baseline(problem, crop, tech, util_floor)
        if c is not None:
            out.append({k: v for k, v in c.items() if k != "alloc"})
    return out


def best_single_option_free(problem: Problem, util_floor: float) -> dict | None:
    """Second baseline: the best farm that grows ONE crop with ONE technique but may choose plots and areas.

    Each (crop, technique) pair is solved with the SAME MIP (same objective and constraints, same utilisation
    floor); the best by objective is returned. Because it is a restriction of the full problem, the optimizer
    can never do worse than it. It differs from `best_baseline`, which insists on the whole usable area of every
    plot (scaled uniformly only when constraints force it).
    """
    best = None
    for crop, tech in problem.pairs():
        sub = replace(problem, options=[o for o in problem.options if o.key == (crop, tech)])
        sol = solve_with_floor(sub, util_floor)
        if sol is None or not sol.alloc or sol.status == "CHECK_FAILED":
            continue
        ev = sol.metrics
        score = ev["roi"] if problem.limits.objective == "roi" else ev["net_gain"]
        if score is None:
            continue
        if best is None or score > best["score"]:
            best = {"crop": crop, "technique": tech, "alloc": sol.alloc, "metrics": ev, "score": score,
                    "scale": ev["area_m2"] / sum(p.usable_m2 for p in problem.plots)}
    return best
