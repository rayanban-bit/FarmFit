import math

import pytest

from app import finance
from app.optimizer import Limits, PlotIn, Problem, evaluate, solve, Option, TechIn, GroupIn
from tests.helpers import flat, make_problem


def test_cash_flow_vector_year0_is_minus_capex():
    cf = finance.cash_flows(1000, 300, 5)
    assert cf == [-1000, 300, 300, 300, 300, 300]
    assert finance.cumulative(cf)[-1] == 500


def test_revenue_opex_profit_summary():
    s = finance.summarise(revenue=1000, opex=400, capex=1200, water_m3=50, energy_kwh=70, years=5)
    assert s.profit == 600
    assert s.net_gain == 5 * 600 - 1200
    assert s.roi == pytest.approx((3000 - 1200) / 1200)
    assert s.payback_years == pytest.approx(2.0)


def test_roi_is_not_payback():
    # Same investment, same profit: ROI (a ratio of net gain) and payback (years) are different numbers.
    assert finance.roi(1000, 500, 5) == pytest.approx(1.5)
    assert finance.payback_years(1000, 500) == pytest.approx(2.0)


def test_payback_never_when_unprofitable():
    assert finance.payback_years(1000, 0) is None
    assert finance.payback_years(1000, -5) is None
    assert finance.roi(1000, -5, 5) < 0


def test_roi_undefined_without_capex():
    assert finance.roi(0, 100, 5) is None


def test_evaluate_matches_hand_calculation():
    p = make_problem()
    alloc = {("P1", "tomato", "open"): 4000.0}
    ev = evaluate(p, alloc)
    assert ev["revenue"] == pytest.approx(30 * 4000)
    # variable opex + no fixed opex for open field, but water network fixed opex 600
    assert ev["opex"] == pytest.approx(12 * 4000 + 600)
    # capex: 20/m2 + technique fixed 3000 + water network 15000 (paid once)
    assert ev["capex"] == pytest.approx(20 * 4000 + 3000 + 15000)
    assert ev["profit"] == pytest.approx(ev["revenue"] - ev["opex"])
    assert ev["roi"] == pytest.approx((5 * ev["profit"] - ev["capex"]) / ev["capex"])
    assert ev["water_m3"] == pytest.approx(1.2 * 4000)


def test_dinkelbach_converges_to_max_roi_by_brute_force():
    """The solver's ROI must equal the best ROI found by dense enumeration of a 1-D family of portfolios."""
    p = make_problem(min_utilisation=0.0, budget=400_000)
    sol = solve(p)
    assert sol.status == "OPTIMAL"
    # F(lambda) must reach ~0 and lambda must be monotonically non-decreasing (Newton on a convex F)
    lams = [it.lam for it in sol.iterations]
    assert all(b >= a - 1e-9 for a, b in zip(lams, lams[1:]))
    assert abs(sol.iterations[-1].f) < 1e-3
    best = -1e9
    for x_t in range(0, 10001, 100):
        for x_l in range(0, 10001 - x_t, 100):
            for x_h in range(0, 10001 - x_t - x_l, 500):
                alloc = {}
                if x_t >= 100: alloc[("P1", "tomato", "open")] = float(x_t)
                if x_l >= 100: alloc[("P1", "lettuce", "open")] = float(x_l)
                if x_h >= 500: alloc[("P1", "lettuce", "hydro")] = float(x_h)
                if not alloc:
                    continue
                if any(t == "open" for (_, _, t) in alloc) and sum(a for (k, a) in alloc.items() if k[2] == "open") < 500:
                    continue
                from app.optimizer import check_feasible
                if check_feasible(p, alloc):
                    continue
                r = evaluate(p, alloc)["roi"]
                best = max(best, r)
    assert sol.metrics["roi"] >= best - 1e-6


def test_dinkelbach_iterations_are_recorded_and_finite():
    sol = solve(make_problem())
    assert 1 <= len(sol.iterations) <= 10
    assert all(math.isfinite(it.lam) for it in sol.iterations)
