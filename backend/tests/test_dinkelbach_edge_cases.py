"""Regression tests for the ROI (fractional) objective at its boundaries.

ROI = N / CapEx is undefined when CapEx = 0, which is reachable whenever a user enters zero capital costs.
The optimizer must classify that case rather than divide by zero, spin, or silently regularise the objective
with an epsilon. These tests pin the behaviour of every branch.
"""
import math

import pytest

from app import catalog as catalog_mod, crop_model
from app.optimizer import (AREA_TOL, CAPEX_TOL, GroupIn, Limits, Option, PlotIn, Problem, TechIn,
                           check_feasible, evaluate, solve)


def flat(x: float) -> list[float]:
    return [x / 12.0] * 12


def make(capex_m2: float, fixed_capex: float, group_capex: float, rev: float = 40.0, opex: float = 10.0, **lim) -> Problem:
    """One plot, one option. capex/rev/opex are per m2 per year so each case is easy to reason about."""
    opts = [Option("c", "t", rev_m2=rev, opex_m2=opex, capex_m2=capex_m2, water_m=flat(0.5), energy_m=flat(2.0), yield_kg_m2=5)]
    techs = {"t": TechIn("t", min_area_m2=300, fixed_capex=fixed_capex, fixed_opex=0.0, requires=["g"])}
    groups = {"g": GroupIn("g", group_capex, 0.0)}
    limits = Limits(**{"budget": 1e6, "water_year": 1e6, "energy_year": 1e6, "min_block_m2": 100,
                       "min_utilisation": 0.0, **lim})
    return Problem([PlotIn("P", 10_000.0)], opts, techs, groups, limits)


# ---------------------------------------------------------------- 1. normal positive CapEx (no regression)
def test_normal_positive_capex_still_solves_to_the_optimum():
    p = make(20.0, 3000, 15000)
    sol = solve(p)
    assert sol.status == "OPTIMAL"
    assert sol.ratio_outcome == "optimal"
    assert sol.alloc and sol.metrics["capex"] > CAPEX_TOL
    assert sol.metrics["roi"] == pytest.approx((5 * sol.metrics["profit"] - sol.metrics["capex"]) / sol.metrics["capex"])
    assert check_feasible(p, sol.alloc, sol.utilisation_floor_used) == []
    assert sol.warnings == []


def test_removing_the_capex_floor_did_not_change_the_optimum():
    """The old code added `CapEx >= 1` to dodge the division; the optimum must not depend on that."""
    p = make(20.0, 3000, 15000)
    sol = solve(p)
    # brute force over the single decision (area) on a fine grid
    best = None
    for a in range(0, 10_001, 50):
        alloc = {("P", "c", "t"): float(a)} if a >= 300 else {}
        if alloc and check_feasible(p, alloc):
            continue
        ev = evaluate(p, alloc)
        if ev["capex"] <= CAPEX_TOL:
            continue
        best = ev["roi"] if best is None else max(best, ev["roi"])
    assert sol.metrics["roi"] >= best - 1e-6


# ---------------------------------------------------------------- 2. zero CapEx
def test_zero_capex_with_production_is_reported_not_divided():
    """Production without capital: ROI = N/0 is unbounded above, so no ROI is claimed."""
    p = make(0.0, 0.0, 0.0)
    sol = solve(p)
    assert sol.status == "ZERO_CAPEX"
    assert sol.ratio_outcome == "zero_capex_unbounded"
    assert sol.alloc, "a zero-investment plan that produces must still be returned"
    assert sol.metrics["area_m2"] > AREA_TOL
    assert sol.metrics["capex"] <= CAPEX_TOL
    assert sol.metrics["net_gain"] > 0
    assert sol.metrics["roi"] is None, "ROI must not be fabricated when CapEx is zero"
    assert any("unbounded" in w for w in sol.warnings)
    assert check_feasible(p, sol.alloc, sol.utilisation_floor_used) == []


def test_zero_capex_and_zero_net_gain_is_undefined_not_zero():
    """0/0. Forced to produce by a utilisation floor so the trivial plan is not available."""
    p = make(0.0, 0.0, 0.0, rev=10.0, opex=10.0, min_utilisation=0.5)
    sol = solve(p)
    assert sol.status == "ZERO_CAPEX"
    assert sol.ratio_outcome == "zero_capex_undefined"
    assert sol.metrics["capex"] <= CAPEX_TOL
    assert sol.metrics["net_gain"] == pytest.approx(0.0, abs=1e-6)
    assert sol.metrics["roi"] is None
    assert any("undefined" in w for w in sol.warnings)


# ---------------------------------------------------------------- 3. zero profit
def test_zero_profit_with_real_capex_reports_no_viable_investment():
    """Revenue exactly covers OpEx, so every plan loses its CapEx: there is nothing to return on."""
    p = make(20.0, 3000, 15000, rev=10.0, opex=10.0)
    sol = solve(p)
    assert sol.status == "NO_VIABLE_INVESTMENT"
    assert sol.ratio_outcome == "no_viable_investment"
    assert sol.alloc == {}
    assert sol.metrics["roi"] is None
    assert any("No viable investment solution" in w for w in sol.warnings)


def test_loss_making_options_report_no_viable_investment():
    sol = solve(make(20.0, 3000, 15000, rev=5.0, opex=10.0))
    assert sol.status == "NO_VIABLE_INVESTMENT"
    assert sol.alloc == {}


def test_a_forced_loss_still_optimises_the_ratio_instead_of_bailing_out():
    """With a utilisation floor the trivial plan is infeasible, so a negative ROI is a real answer."""
    p = make(20.0, 3000, 15000, rev=5.0, opex=10.0, min_utilisation=0.9)
    sol = solve(p)
    assert sol.status == "OPTIMAL"
    assert sol.metrics["roi"] is not None and sol.metrics["roi"] < 0
    assert math.isfinite(sol.metrics["roi"])


# ---------------------------------------------------------------- 4. empty feasible set
def test_empty_option_set_is_infeasible():
    p = make(20.0, 3000, 15000)
    p.options = []
    sol = solve(p)
    assert sol.status == "INFEASIBLE"
    assert sol.alloc == {}
    assert sol.metrics["roi"] is None


def test_budget_below_the_minimum_build_cost_terminates_cleanly():
    sol = solve(make(20.0, 3000, 15000, budget=10.0))
    assert sol.status in ("INFEASIBLE", "NO_VIABLE_INVESTMENT")
    assert sol.alloc == {}
    assert sol.metrics["roi"] is None


def test_infeasible_utilisation_floor_is_relaxed_and_still_terminates():
    sol = solve(make(20.0, 3000, 15000, budget=60_000, min_utilisation=0.95))
    assert sol.status in ("OPTIMAL", "FEASIBLE", "NO_VIABLE_INVESTMENT", "INFEASIBLE")
    assert any("relaxed" in w for w in sol.warnings) or sol.status == "INFEASIBLE"


# ---------------------------------------------------------------- 5. convergence
def test_dinkelbach_converges_with_monotone_lambda_and_vanishing_residual():
    sol = solve(make(20.0, 3000, 15000))
    assert sol.status == "OPTIMAL"
    assert 1 <= len(sol.iterations) <= 10, "Newton on a convex piecewise-linear F must converge in a few solves"
    lams = [it.lam for it in sol.iterations]
    assert all(math.isfinite(x) for x in lams)
    assert all(b >= a - 1e-9 for a, b in zip(lams[1:], lams[2:])), "lambda must not decrease after the first step"
    last = sol.iterations[-1]
    assert last.f <= 1e-6 * max(1.0, abs(last.n), last.d), "F(lambda) must reach 0 at the root"
    # At the root, lambda IS the optimal ratio. The final iterate may legitimately be the trivial
    # "build nothing" point (N = CapEx = 0) that ties the optimum there, so compare against lambda,
    # not against N/CapEx of that iterate.
    assert sol.metrics["roi"] == pytest.approx(last.lam, rel=1e-6)
    for it in sol.iterations:
        if it.d > CAPEX_TOL:
            assert math.isfinite(it.n / it.d)


def test_every_iteration_has_a_defined_lambda_and_no_division_by_zero():
    for kwargs in ({}, {"rev": 12.0}, {"rev": 10.5}, {"budget": 120_000}, {"min_utilisation": 0.4}):
        sol = solve(make(20.0, 3000, 15000, **kwargs))
        for it in sol.iterations:
            assert math.isfinite(it.lam) and math.isfinite(it.f)
            assert it.d >= 0
            if it.d <= CAPEX_TOL:
                assert sol.ratio_outcome in ("no_viable_investment", "zero_capex_unbounded", "zero_capex_undefined", "optimal")


def test_no_zero_division_across_a_sweep_of_degenerate_parameters():
    """Any combination of zero costs, zero revenue and zero margins must return, never raise."""
    for capex in (0.0, 20.0):
        for fixed in (0.0, 3000.0):
            for grp in (0.0, 15000.0):
                for rev, opex in ((40.0, 10.0), (10.0, 10.0), (0.0, 10.0), (10.0, 0.0), (0.0, 0.0)):
                    for floor in (0.0, 0.5):
                        p = make(capex, fixed, grp, rev=rev, opex=opex, min_utilisation=floor)
                        sol = solve(p)  # must not raise ZeroDivisionError
                        assert sol.status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "NO_VIABLE_INVESTMENT",
                                              "ZERO_CAPEX", "MAX_ITER", "CHECK_FAILED")
                        if sol.metrics["capex"] <= CAPEX_TOL:
                            assert sol.metrics["roi"] is None


# ---------------------------------------------------------------- the input that actually crashed
def test_zero_irrigation_efficiency_is_rejected_with_a_clear_message():
    """It would demand infinite water. This is the input that produced `float division by zero`."""
    cat, _ = catalog_mod.resolve(catalog_mod.base_catalog(),
                                 {"techniques": {"open_field": {"irrigation_efficiency": 0}}},
                                 accept_planning_profile=True)
    problems = catalog_mod.validate_values(cat)
    assert any("irrigation efficiency" in p.lower() and "greater than 0" in p for p in problems)


def test_irrigation_efficiency_above_one_is_rejected():
    cat, _ = catalog_mod.resolve(catalog_mod.base_catalog(),
                                 {"techniques": {"open_field": {"irrigation_efficiency": 1.4}}},
                                 accept_planning_profile=True)
    assert any("irrigation efficiency" in p.lower() for p in catalog_mod.validate_values(cat))


def test_negative_costs_and_prices_are_rejected():
    cat, _ = catalog_mod.resolve(catalog_mod.base_catalog(),
                                 {"crops": {"tomato": {"price_qar_kg": -2}},
                                  "techniques": {"greenhouse": {"capex_qar_m2": -5}}},
                                 accept_planning_profile=True)
    problems = catalog_mod.validate_values(cat)
    assert len(problems) >= 2


def test_a_fully_valid_catalog_reports_no_value_problems():
    cat, _ = catalog_mod.resolve(catalog_mod.base_catalog(), None, accept_planning_profile=True)
    assert catalog_mod.validate_values(cat) == []


def test_monthly_water_rejects_zero_efficiency_at_source():
    clim = {"tmax": [30] * 12, "tmin": [15] * 12, "tmean": [22] * 12, "et0_mm_day": [5] * 12,
            "rain_mm_month": [0] * 12, "days": crop_model.MONTH_DAYS, "years": 1}
    sched = crop_model.build_schedule(clim, {"tmin_mean": 5, "tmax_mean": 40}, 0, 0, False, 100, 10, 1)
    with pytest.raises(ValueError, match="irrigation efficiency"):
        crop_model.monthly_water_kc(clim, sched, [25, 25, 25, 25], [0.6, 1.1, 0.8], 0.0, 1.0, 0.0, False, 0.6)
