import random

import pytest

from app.baseline import best_baseline
from app.optimizer import (GroupIn, Limits, Option, PlotIn, Problem, TechIn, check_feasible, evaluate, solve)
from tests.helpers import flat, make_problem


def area_by(sol, idx):
    out = {}
    for k, a in sol.alloc.items():
        out[k[idx]] = out.get(k[idx], 0) + a
    return out


def test_solver_returns_feasible_solution():
    sol = solve(make_problem())
    assert sol.status == "OPTIMAL"
    assert sol.alloc
    assert check_feasible(make_problem(), sol.alloc, sol.utilisation_floor_used) == []


def test_land_constraint():
    p = make_problem(min_utilisation=0.0)
    sol = solve(p)
    assert sum(sol.alloc.values()) <= 10_000 + 1e-6


def test_budget_constraint_binds_and_is_respected():
    p = make_problem(budget=120_000, min_utilisation=0.0)
    sol = solve(p)
    assert sol.metrics["capex"] <= 120_000 + 1e-6
    p2 = make_problem(budget=5e6, min_utilisation=0.0)
    assert solve(p2).metrics["capex"] > 120_000  # unconstrained solution wants more capital


def test_water_constraint_annual_and_monthly():
    p = make_problem(water_year=3_000, min_utilisation=0.0, water_month_max=3_000 / 12)
    sol = solve(p)
    assert sol.metrics["water_m3"] <= 3_000 + 1e-6
    assert max(sol.metrics["water_month"]) <= 3_000 / 12 + 1e-6


def test_monthly_water_binds_before_annual():
    """Crops that all draw water in the same months hit the monthly cap even if the annual total fits."""
    seasonal = [0.0] * 12
    for m in (0, 1, 2):
        seasonal[m] = 1.0  # 3 m3/m2 in Jan-Mar only
    opts = [Option("c", "t", rev_m2=40, opex_m2=10, capex_m2=10, water_m=seasonal, energy_m=flat(0), yield_kg_m2=5)]
    techs = {"t": TechIn("t", 100, 0, 0, [])}
    lim = Limits(budget=1e9, water_year=12_000, water_month_max=1_000, min_block_m2=100, min_utilisation=0.0)
    p = Problem([PlotIn("P", 100_000)], opts, techs, {}, lim)
    sol = solve(p)
    # annual cap alone would allow 4000 m2; monthly cap (1000 m3/month / 1 m3/m2/month) allows only 1000 m2
    assert sum(sol.alloc.values()) == pytest.approx(1000.0, rel=1e-5)
    assert sol.metrics["water_m3"] < 12_000


def test_energy_constraint():
    p = make_problem(energy_year=20_000, min_utilisation=0.0, energy_month_max=20_000 / 12)
    sol = solve(p)
    assert sol.metrics["energy_kwh"] <= 20_000 + 1e-6
    assert check_feasible(p, sol.alloc) == []


def test_compatibility_no_variable_for_invalid_pair():
    """Options not in the compatibility list can never appear in a solution."""
    p = make_problem(min_utilisation=0.0)
    sol = solve(p)
    valid = {o.key for o in p.options}
    assert all((c, t) in valid for (_, c, t) in sol.alloc)
    assert check_feasible(p, {("P1", "tomato", "hydro"): 800.0})  # tomato x hydro is not an option -> violation


def test_minimum_area_per_technique():
    # hydro min 500 m2: never chosen with less than that
    for budget in (100_000, 200_000, 300_000, 400_000, 900_000):
        sol = solve(make_problem(budget=budget, min_utilisation=0.0))
        for (p, t), _ in [((k[0], k[2]), 0) for k in sol.alloc]:
            total = sum(a for (pp, c, tt), a in sol.alloc.items() if pp == p and tt == t)
            assert total >= 500 - 1e-6
        for a in sol.alloc.values():
            assert a >= 100 - 1e-6  # minimum block


def test_infrastructure_paid_once_when_shared():
    """Two techniques on one plot that both need the water network pay for it once."""
    p = make_problem(min_utilisation=0.0)
    alloc = {("P1", "tomato", "open"): 3000.0, ("P1", "lettuce", "hydro"): 3000.0}
    ev = evaluate(p, alloc)
    var = 20 * 3000 + 300 * 3000
    fixed_techs = 3000 + 10000
    groups_once = 15000 + 60000  # water network counted ONCE although both techniques require it
    assert ev["capex"] == pytest.approx(var + fixed_techs + groups_once)
    standalone = (var + 3000 + 15000) + (300 * 3000 + 10000 + 15000 + 60000)  # if each paid its own copy
    assert ev["capex"] < standalone


def test_objective_value_matches_independent_evaluation():
    p = make_problem(min_utilisation=0.0, budget=600_000)
    sol = solve(p)
    ev = evaluate(p, sol.alloc)
    # The reported metrics must equal an independent recomputation from the allocation.
    assert sol.metrics["net_gain"] == pytest.approx(ev["net_gain"], rel=1e-9)
    assert ev["roi"] == pytest.approx(ev["net_gain"] / ev["capex"])
    assert sol.metrics["roi"] == pytest.approx(ev["roi"])
    # At the Dinkelbach root lambda equals the optimal ratio. The final iterate itself may be the trivial
    # zero-CapEx point that ties the optimum there, so compare against lambda rather than that iterate's N.
    assert sol.metrics["roi"] == pytest.approx(sol.iterations[-1].lam, rel=1e-6)


def test_optimum_is_at_least_as_good_as_every_single_option_baseline():
    rng = random.Random(7)
    for trial in range(8):
        opts = []
        for i in range(4):
            opts.append(Option(f"c{i}", "t1" if i < 2 else "t2", rev_m2=rng.uniform(15, 80), opex_m2=rng.uniform(5, 30),
                               capex_m2=rng.uniform(10, 200), water_m=flat(rng.uniform(0.2, 2.0)), energy_m=flat(rng.uniform(1, 60)),
                               yield_kg_m2=1.0))
        techs = {"t1": TechIn("t1", 300, 2000, 100, ["g"]), "t2": TechIn("t2", 300, 8000, 200, ["g"])}
        groups = {"g": GroupIn("g", 20000, 500)}
        lim = Limits(budget=rng.uniform(150_000, 900_000), water_year=rng.uniform(4_000, 20_000), energy_year=rng.uniform(50_000, 400_000),
                     min_block_m2=100, min_utilisation=0.0)
        p = Problem([PlotIn("A", 6000), PlotIn("B", 4000)], opts, techs, groups, lim)
        sol = solve(p)
        base = best_baseline(p, sol.utilisation_floor_used)
        if sol.status != "OPTIMAL":
            continue
        assert check_feasible(p, sol.alloc) == []
        if base is not None:
            assert sol.metrics["roi"] >= base["metrics"]["roi"] - 1e-6


def test_utilisation_floor_relaxed_with_warning_when_infeasible():
    p = make_problem(budget=60_000, min_utilisation=0.9)
    sol = solve(p)
    assert any("relaxed" in w for w in sol.warnings)
    assert sol.utilisation_floor_used == 0.0


def test_no_viable_investment_when_minimum_scale_exceeds_budget():
    """Nothing can be built for QAR 1,000, and with no utilisation floor "build nothing" is feasible.

    The honest answer is therefore that no investment exists, not that the constraint set is empty.
    """
    p = make_problem(budget=1_000, min_utilisation=0.0)
    sol = solve(p)
    assert sol.status == "NO_VIABLE_INVESTMENT"
    assert sol.alloc == {}
    assert sol.metrics["roi"] is None
    assert any("No viable investment solution" in w for w in sol.warnings)


def test_multi_plot_shares_resources_globally():
    p = make_problem(water_year=6_000, min_utilisation=0.0, water_month_max=500)
    p.plots = [PlotIn("P1", 6_000), PlotIn("P2", 6_000)]
    sol = solve(p)
    assert sol.metrics["water_m3"] <= 6_000 + 1e-6
    assert check_feasible(p, sol.alloc) == []


def test_net_profit_objective_is_a_single_mip():
    p = make_problem(objective="net_profit", min_utilisation=0.0)
    sol = solve(p)
    assert len(sol.iterations) == 1
    assert sol.metrics["net_gain"] >= solve(make_problem(objective="roi", min_utilisation=0.0)).metrics["net_gain"] - 1e-6
