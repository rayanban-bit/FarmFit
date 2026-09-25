"""Farm-portfolio optimizer: OR-Tools MIP (SCIP) + Dinkelbach fractional programming.

Sets
    p in P   plots (usable area U_p, m2)
    o in O   compatible (crop c, technique t) options, month m in 1..12
    g in G   shared infrastructure groups; technique t requires groups R_t

Decision variables
    a[p,o]  >= 0    continuous  area allocated (m2)                     "area[p,c,t]"
    z[p,o]  in {0,1}            block is used (enforces minimum block area)
    b[p,t]  in {0,1}            technique t is built on plot p          "build[p,t]"
    y[p,g]  in {0,1}            shared infrastructure g built on plot p (fixed cost paid ONCE)

Linear expressions
    Revenue-less-opex  P = sum (rev_o - opex_o) a[p,o] - sum F^op_t b[p,t] - sum F^op_g y[p,g]   [QAR/yr]
    CapEx              C = sum capex_o a[p,o] + sum F_t b[p,t] + sum F_g y[p,g]                  [QAR]
    Net gain (H yrs)   N = H*P - C            (cumulative undiscounted cash flow, Year0 = -C)
    5-year ROI         N / C

Constraints
    land          sum_o a[p,o] <= U_p                                      (each plot)
    link          a[p,o] <= U_p z[p,o];  a[p,o] >= minblock z[p,o];  z[p,o] <= b[p,t(o)]
    min scale     sum_{o in t} a[p,o] >= minarea_t b[p,t]
    shared infra  b[p,t] <= y[p,g]   for g in R_t
    budget        C <= Budget
    water         sum w[o,m] a[p,o] <= Wcap_m  (each month m);  annual sum <= W_year
    energy        sum e[o,m] a[p,o] <= Ecap_m  (each month m);  annual sum <= E_year
    utilisation   sum a >= u * sum U        (optional planning floor, relaxed with a warning if infeasible)
    crop share    sum_{p,t} a[p,c,t] <= s_max * sum U   (optional)
    compatibility incompatible (crop, technique) pairs simply have no variable.

Objective = maximise the ratio N/C. Because the objective is a ratio of two linear functions of the
same decision variables, it is solved exactly by Dinkelbach's algorithm:

    lambda_0 = 0
    repeat:  x_k = argmax_x  N(x) - lambda_k * C(x)         <- one MIP per iteration, solved to optimality
             F_k = N(x_k) - lambda_k C(x_k)
             if F_k <= tol: stop, x_k is the exact ROI-optimal portfolio
             lambda_{k+1} = N(x_k) / C(x_k)                  <- ROI of the incumbent

F(lambda) = max_x N - lambda*C is convex, piecewise linear and decreasing; the iteration is the Newton
method on F(lambda) = 0 and converges superlinearly to lambda* = max ROI. (Dinkelbach, 1967.)
A second objective, 'net_profit', maximises N directly with a single MIP.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from ortools.linear_solver import pywraplp

MONTHS = 12


@dataclass
class PlotIn:
    id: str
    usable_m2: float


@dataclass
class Option:
    crop: str
    technique: str
    rev_m2: float  # QAR/m2/yr
    opex_m2: float  # QAR/m2/yr, all variable operating cost (technique opex + inputs + water + energy)
    capex_m2: float  # QAR/m2
    water_m: list[float]  # m3/m2 per month
    energy_m: list[float]  # kWh/m2 per month
    yield_kg_m2: float = 0.0  # kg/m2/yr (reporting)
    water_cost_m2: float = 0.0  # reporting only (already in opex_m2)
    energy_cost_m2: float = 0.0  # reporting only (already in opex_m2)
    plot: str | None = None  # None = applies to every plot; else only to that plot (climate differs per plot)

    @property
    def key(self) -> tuple[str, str]:
        return (self.crop, self.technique)

    @property
    def water_year(self) -> float:
        return sum(self.water_m)

    @property
    def energy_year(self) -> float:
        return sum(self.energy_m)


@dataclass
class TechIn:
    id: str
    min_area_m2: float = 0.0
    fixed_capex: float = 0.0
    fixed_opex: float = 0.0
    requires: list[str] = field(default_factory=list)


@dataclass
class GroupIn:
    id: str
    fixed_capex: float = 0.0
    fixed_opex: float = 0.0


@dataclass
class Limits:
    budget: float = float("inf")
    water_year: float = float("inf")
    energy_year: float = float("inf")
    monthly_peak_factor: float = 1.5
    min_utilisation: float = 0.0
    min_block_m2: float = 0.0
    horizon_years: int = 5
    objective: str = "roi"  # 'roi' | 'net_profit'
    max_crop_share: float = 1.0

    def water_cap_month(self) -> float:
        return self.water_year * self.monthly_peak_factor / MONTHS

    def energy_cap_month(self) -> float:
        return self.energy_year * self.monthly_peak_factor / MONTHS


@dataclass
class Problem:
    plots: list[PlotIn]
    options: list[Option]
    techs: dict[str, TechIn]
    groups: dict[str, GroupIn]
    limits: Limits

    def option_for(self, plot_id: str, crop: str, tech: str) -> Option | None:
        """Plot-specific option if present, else the plot-independent one, else None (= not allowed)."""
        general = None
        for o in self.options:
            if o.crop == crop and o.technique == tech:
                if o.plot == plot_id:
                    return o
                if o.plot is None:
                    general = o
        return general

    def pairs(self) -> list[tuple[str, str]]:
        seen: list[tuple[str, str]] = []
        for o in self.options:
            if o.key not in seen:
                seen.append(o.key)
        return seen


@dataclass
class Iteration:
    k: int
    lam: float
    n: float
    d: float
    f: float
    mip_status: str
    mip_ms: float

    def to_dict(self) -> dict:
        return {"k": self.k, "lambda": self.lam, "net_gain": self.n, "capex": self.d, "F": self.f,
                "mip_status": self.mip_status, "mip_ms": round(self.mip_ms, 1)}


@dataclass
class Solution:
    status: str  # OPTIMAL | INFEASIBLE | ...
    alloc: dict[tuple[str, str, str], float]  # (plot, crop, tech) -> m2
    builds: set[tuple[str, str]]  # (plot, tech)
    infra: set[tuple[str, str]]  # (plot, group)
    metrics: dict
    iterations: list[Iteration]
    solver: dict
    warnings: list[str] = field(default_factory=list)
    utilisation_floor_used: float = 0.0


# ------------------------------------------------------------------------------------------------
# Independent evaluation (does not use the solver): used for Dinkelbach updates, baseline & tests
# ------------------------------------------------------------------------------------------------
def derive_structure(problem: Problem, alloc: dict[tuple[str, str, str], float], eps: float = 1e-6):
    builds: set[tuple[str, str]] = set()
    infra: set[tuple[str, str]] = set()
    for (p, c, t), a in alloc.items():
        if a > eps:
            builds.add((p, t))
    for (p, t) in builds:
        for g in problem.techs[t].requires:
            infra.add((p, g))
    return builds, infra


def evaluate(problem: Problem, alloc: dict[tuple[str, str, str], float]) -> dict:
    """Recompute revenue/opex/capex/water/energy/ROI for an allocation from first principles."""
    builds, infra = derive_structure(problem, alloc)
    rev = var_opex = capex = 0.0
    water_m = [0.0] * MONTHS
    energy_m = [0.0] * MONTHS
    kg = 0.0
    area = 0.0
    for (p, c, t), a in alloc.items():
        if a <= 1e-9:
            continue
        o = problem.option_for(p, c, t)
        if o is None:
            raise KeyError(f"no option for {p}/{c}/{t}")
        area += a
        rev += o.rev_m2 * a
        var_opex += o.opex_m2 * a
        capex += o.capex_m2 * a
        kg += o.yield_kg_m2 * a
        for m in range(MONTHS):
            water_m[m] += o.water_m[m] * a
            energy_m[m] += o.energy_m[m] * a
    fixed_capex = sum(problem.techs[t].fixed_capex for (_, t) in builds) + sum(problem.groups[g].fixed_capex for (_, g) in infra)
    fixed_opex = sum(problem.techs[t].fixed_opex for (_, t) in builds) + sum(problem.groups[g].fixed_opex for (_, g) in infra)
    capex_total = capex + fixed_capex
    opex_total = var_opex + fixed_opex
    profit = rev - opex_total
    h = problem.limits.horizon_years
    net = h * profit - capex_total
    return {
        "area_m2": area,
        "revenue": rev,
        "opex": opex_total,
        "opex_variable": var_opex,
        "opex_fixed": fixed_opex,
        "profit": profit,
        "capex": capex_total,
        "capex_variable": capex,
        "capex_fixed": fixed_capex,
        "net_gain": net,
        "roi": (net / capex_total) if capex_total > 0 else None,
        "water_m3": sum(water_m),
        "energy_kwh": sum(energy_m),
        "water_month": water_m,
        "energy_month": energy_m,
        "yield_kg": kg,
    }


def check_feasible(problem: Problem, alloc: dict[tuple[str, str, str], float], util_floor: float = 0.0, tol: float = 1e-6) -> list[str]:
    """Return a list of violated constraints (empty = feasible). Used by tests and as a solver self-check."""
    lim = problem.limits
    violations: list[str] = []
    bad = [k for k, a in alloc.items() if a > 1e-9 and problem.option_for(k[0], k[1], k[2]) is None]
    if bad:  # compatibility is checked first; such an allocation cannot even be priced
        return [f"incompatible option {c}x{t}" for (_, c, t) in bad]
    ev = evaluate(problem, alloc)
    usable = {p.id: p.usable_m2 for p in problem.plots}
    per_plot: dict[str, float] = {}
    per_tech: dict[tuple[str, str], float] = {}
    per_crop: dict[str, float] = {}
    for (p, c, t), a in alloc.items():
        if a <= 1e-9:
            continue
        per_plot[p] = per_plot.get(p, 0.0) + a
        per_tech[(p, t)] = per_tech.get((p, t), 0.0) + a
        per_crop[c] = per_crop.get(c, 0.0) + a
        if a < lim.min_block_m2 - tol * max(1.0, lim.min_block_m2):
            violations.append(f"block {p}/{c}/{t} below minimum block area")
    for p, a in per_plot.items():
        if a > usable[p] * (1 + tol) + tol:
            violations.append(f"land exceeded on {p}")
    for (p, t), a in per_tech.items():
        if a < problem.techs[t].min_area_m2 * (1 - tol) - tol:
            violations.append(f"minimum scale not met for {t} on {p}")
    if ev["capex"] > lim.budget * (1 + tol) + tol:
        violations.append("budget exceeded")
    if ev["water_m3"] > lim.water_year * (1 + tol) + tol:
        violations.append("annual water exceeded")
    if ev["energy_kwh"] > lim.energy_year * (1 + tol) + tol:
        violations.append("annual energy exceeded")
    wc, ec = lim.water_cap_month(), lim.energy_cap_month()
    for m in range(MONTHS):
        if ev["water_month"][m] > wc * (1 + tol) + tol:
            violations.append(f"monthly water exceeded (month {m + 1})")
        if ev["energy_month"][m] > ec * (1 + tol) + tol:
            violations.append(f"monthly energy exceeded (month {m + 1})")
    total_usable = sum(usable.values())
    if util_floor > 0 and ev["area_m2"] < util_floor * total_usable * (1 - tol) - tol:
        violations.append("land utilisation floor not met")
    if lim.max_crop_share < 1.0:
        for c, a in per_crop.items():
            if a > lim.max_crop_share * total_usable * (1 + tol) + tol:
                violations.append(f"crop share exceeded for {c}")
    return violations


# ------------------------------------------------------------------------------------------------
# MIP construction
# ------------------------------------------------------------------------------------------------
class _Model:
    def __init__(self, problem: Problem, util_floor: float, time_limit_s: float):
        self.problem = problem
        lim = problem.limits
        s = pywraplp.Solver.CreateSolver("SCIP")
        if s is None:
            raise RuntimeError("OR-Tools SCIP backend is unavailable")
        self.s = s
        s.SetTimeLimit(int(time_limit_s * 1000))
        inf = s.infinity()
        self.a: dict[tuple[str, int], pywraplp.Variable] = {}
        self.z: dict[tuple[str, int], pywraplp.Variable] = {}
        self.b: dict[tuple[str, str], pywraplp.Variable] = {}
        self.y: dict[tuple[str, str], pywraplp.Variable] = {}
        opts = problem.options
        # applicable (plot, option) pairs: an option is either global (plot None) or bound to one plot
        self.items = [(pl, j, o) for pl in problem.plots for j, o in enumerate(opts) if o.plot in (None, pl.id)]
        techs_used = sorted({o.technique for o in opts})
        groups_used = sorted({g for t in techs_used for g in problem.techs[t].requires})

        for pl, j, o in self.items:
            self.a[(pl.id, j)] = s.NumVar(0.0, pl.usable_m2, f"a[{pl.id},{o.crop},{o.technique}]")
            self.z[(pl.id, j)] = s.BoolVar(f"z[{pl.id},{o.crop},{o.technique}]")
        for pl in problem.plots:
            for t in techs_used:
                self.b[(pl.id, t)] = s.BoolVar(f"build[{pl.id},{t}]")
            for g in groups_used:
                self.y[(pl.id, g)] = s.BoolVar(f"infra[{pl.id},{g}]")

        for pl in problem.plots:
            here = [(j, o) for (p2, j, o) in self.items if p2.id == pl.id]
            if here:
                s.Add(sum(self.a[(pl.id, j)] for j, _ in here) <= pl.usable_m2)  # land
            for j, o in here:
                a, z = self.a[(pl.id, j)], self.z[(pl.id, j)]
                s.Add(a <= pl.usable_m2 * z)
                s.Add(a >= lim.min_block_m2 * z)
                s.Add(z <= self.b[(pl.id, o.technique)])
            for t in techs_used:
                terms = [self.a[(pl.id, j)] for j, o in here if o.technique == t]
                if terms:
                    s.Add(sum(terms) >= problem.techs[t].min_area_m2 * self.b[(pl.id, t)])
                for g in problem.techs[t].requires:
                    s.Add(self.b[(pl.id, t)] <= self.y[(pl.id, g)])

        # expressions
        self.profit = self._profit_expr()
        self.capex = self._capex_expr()
        if lim.budget < inf:
            s.Add(self.capex <= lim.budget)
        wcap, ecap = lim.water_cap_month(), lim.energy_cap_month()
        for m in range(MONTHS):
            if lim.water_year < float("inf"):
                s.Add(sum(o.water_m[m] * self.a[(pl.id, j)] for pl, j, o in self.items) <= wcap)
            if lim.energy_year < float("inf"):
                s.Add(sum(o.energy_m[m] * self.a[(pl.id, j)] for pl, j, o in self.items) <= ecap)
        if lim.water_year < float("inf"):
            s.Add(sum(o.water_year * self.a[(pl.id, j)] for pl, j, o in self.items) <= lim.water_year)
        if lim.energy_year < float("inf"):
            s.Add(sum(o.energy_year * self.a[(pl.id, j)] for pl, j, o in self.items) <= lim.energy_year)
        total_usable = sum(p.usable_m2 for p in problem.plots)
        if util_floor > 0:
            s.Add(sum(self.a.values()) >= util_floor * total_usable)
        if lim.max_crop_share < 1.0:
            for c in sorted({o.crop for o in opts}):
                s.Add(sum(self.a[(pl.id, j)] for pl, j, o in self.items if o.crop == c) <= lim.max_crop_share * total_usable)

        self.n_vars = s.NumVariables()
        self.n_int = len(self.z) + len(self.b) + len(self.y)
        self.n_cons = s.NumConstraints()

    def _profit_expr(self):
        p = self.problem
        e = sum((o.rev_m2 - o.opex_m2) * self.a[(pl.id, j)] for pl, j, o in self.items)
        e = e - sum(p.techs[t].fixed_opex * v for (pid, t), v in self.b.items())
        e = e - sum(p.groups[g].fixed_opex * v for (pid, g), v in self.y.items())
        return e

    def _capex_expr(self):
        p = self.problem
        e = sum(o.capex_m2 * self.a[(pl.id, j)] for pl, j, o in self.items)
        e = e + sum(p.techs[t].fixed_capex * v for (pid, t), v in self.b.items())
        e = e + sum(p.groups[g].fixed_capex * v for (pid, g), v in self.y.items())
        return e

    def set_objective(self, lam: float | None, require_capex: bool) -> None:
        h = self.problem.limits.horizon_years
        n_expr = h * self.profit - self.capex
        obj = n_expr if lam is None else n_expr - lam * self.capex
        self.s.Maximize(obj)
        if require_capex:
            self._capex_floor = self.s.Add(self.capex >= 1.0)

    def solve(self):
        params = pywraplp.MPSolverParameters()
        params.SetDoubleParam(pywraplp.MPSolverParameters.RELATIVE_MIP_GAP, 1e-9)
        t0 = time.perf_counter()
        status = self.s.Solve(params)
        ms = (time.perf_counter() - t0) * 1000
        return status, ms

    def extract(self) -> dict[tuple[str, str, str], float]:
        alloc: dict[tuple[str, str, str], float] = {}
        for pl, j, o in self.items:
            v = self.a[(pl.id, j)].solution_value()
            if v > 1e-6:
                alloc[(pl.id, o.crop, o.technique)] = v
        return alloc


_STATUS = {
    pywraplp.Solver.OPTIMAL: "OPTIMAL",
    pywraplp.Solver.FEASIBLE: "FEASIBLE",
    pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
    pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
    pywraplp.Solver.ABNORMAL: "ABNORMAL",
    pywraplp.Solver.NOT_SOLVED: "NOT_SOLVED",
}


def _clean(problem: Problem, alloc: dict) -> dict:
    """Snap solver noise: drop blocks below the minimum block area threshold noise, clip to plot area."""
    usable = {p.id: p.usable_m2 for p in problem.plots}
    out = {}
    for (p, c, t), a in alloc.items():
        out[(p, c, t)] = min(a, usable[p])
    return out


def _run(problem: Problem, util_floor: float, on_progress, time_limit_s: float, max_iter: int, tol: float) -> Solution | None:
    lim = problem.limits
    iterations: list[Iteration] = []
    t_start = time.perf_counter()
    info = {"backend": "OR-Tools pywraplp / SCIP", "method": "", "n_binary": 0, "n_vars": 0, "n_constraints": 0}
    best_alloc: dict = {}

    if lim.objective == "net_profit":
        m = _Model(problem, util_floor, time_limit_s)
        m.set_objective(None, require_capex=False)
        status, ms = m.solve()
        info.update(method="single MIP: maximise 5-year net cash flow", n_binary=m.n_int, n_vars=m.n_vars, n_constraints=m.n_cons)
        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            return None
        alloc = _clean(problem, m.extract())
        ev = evaluate(problem, alloc)
        iterations.append(Iteration(0, 0.0, ev["net_gain"], ev["capex"], m.s.Objective().Value(), _STATUS.get(status, "?"), ms))
        if on_progress:
            on_progress(iterations[-1])
        best_alloc, sol_status = alloc, _STATUS.get(status, "?")
    else:
        lam = 0.0
        sol_status = "NOT_SOLVED"
        info["method"] = "Dinkelbach: iterate max N - lambda*CapEx (MIP) until F(lambda) <= tol"
        converged = False
        for k in range(max_iter):
            m = _Model(problem, util_floor, time_limit_s)
            m.set_objective(lam, require_capex=True)
            status, ms = m.solve()
            info.update(n_binary=m.n_int, n_vars=m.n_vars, n_constraints=m.n_cons)
            if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
                if k == 0:
                    return None
                break
            alloc = _clean(problem, m.extract())
            ev = evaluate(problem, alloc)
            n, d = ev["net_gain"], ev["capex"]
            f = n - lam * d
            it = Iteration(k, lam, n, d, f, _STATUS.get(status, "?"), ms)
            iterations.append(it)
            if on_progress:
                on_progress(it)
            if d <= 0:
                return None
            best_alloc = alloc
            sol_status = _STATUS.get(status, "?")
            if f <= tol * max(1.0, d):
                converged = True
                break
            new_lam = n / d
            if k > 0 and new_lam <= lam + 1e-12:
                converged = True
                break
            lam = new_lam
        if not converged:
            sol_status = "MAX_ITER"
        elif sol_status == "FEASIBLE":
            sol_status = "FEASIBLE"

    builds, infra = derive_structure(problem, best_alloc)
    metrics = evaluate(problem, best_alloc)
    info["wall_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
    info["dinkelbach_iterations"] = len(iterations) if lim.objective == "roi" else None
    violations = check_feasible(problem, best_alloc, util_floor)
    sol = Solution(sol_status, best_alloc, builds, infra, metrics, iterations, info, utilisation_floor_used=util_floor)
    if violations:
        sol.warnings.append("Solver self-check found violated constraints: " + "; ".join(violations))
        sol.status = "CHECK_FAILED"
    return sol


def solve_with_floor(problem: Problem, floor: float, time_limit_s: float = 30.0) -> Solution | None:
    """Solve with a FIXED utilisation floor (no relaxation). None if infeasible. Used for restricted sub-problems."""
    if not problem.options or not problem.plots:
        return None
    return _run(problem, floor, None, time_limit_s, 40, 1e-9)


def solve(problem: Problem, on_progress: Callable[[Iteration], None] | None = None,
          time_limit_s: float = 60.0, max_iter: int = 40, tol: float = 1e-9) -> Solution:
    """Solve the portfolio problem. Relaxes the utilisation floor (with a warning) if it is infeasible."""
    lim = problem.limits
    if not problem.options or not problem.plots:
        return Solution("INFEASIBLE", {}, set(), set(), evaluate(problem, {}), [], {"backend": "none"}, ["No feasible crop x technique option."])
    floor = lim.min_utilisation
    sol = _run(problem, floor, on_progress, time_limit_s, max_iter, tol)
    if sol is None and floor > 0:
        sol = _run(problem, 0.0, on_progress, time_limit_s, max_iter, tol)
        if sol is not None:
            sol.warnings.append(
                f"The requested minimum land utilisation of {floor:.0%} cannot be met within the budget/water/energy limits; "
                "the floor was relaxed to 0% and the solver chose how much land to use."
            )
    if sol is None:
        return Solution("INFEASIBLE", {}, set(), set(), evaluate(problem, {}), [], {"backend": "OR-Tools pywraplp / SCIP"},
                        ["No portfolio satisfies the constraints (minimum technique scale, budget, water or energy is too small)."])
    return sol
