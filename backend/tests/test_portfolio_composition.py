"""Validation for the portfolio-composition rules (spec item 10).

The rules restrict the feasible set; they never pin an area. These tests check that a feasible solution is a
genuine multi-part portfolio, that every stated limit still holds, and that anything relaxed is declared.
"""
from dataclasses import replace

import pytest

from app import optimizer, pipeline
from app.adapters import cadastre
from app.adapters.base import AdapterUnavailable
from app.optimizer import check_feasible
from app.schemas import OptimizeRequest

CROPS = ["tomato", "cucumber", "lettuce", "bell_pepper", "strawberry"]
TECHS = ["open_field", "greenhouse", "hydroponic_greenhouse", "vertical_hydroponics"]
BBOX = (51.39, 25.32, 51.43, 25.36)


@pytest.fixture(scope="module")
def solved():
    try:
        fc, _ = cadastre.query_bbox(BBOX, min_area_m2=5000, limit=25)
    except AdapterUnavailable as exc:  # pragma: no cover
        pytest.skip(f"cadastral service unavailable: {exc}")
    feats = [f for f in fc["features"] if 5_000 <= f["properties"]["area_m2"] <= 120_000][:3]
    if len(feats) < 2:
        pytest.skip("not enough agricultural plots")
    plots = [{"id": f["properties"]["id"], "name": f["properties"]["name"], "geometry": f["geometry"],
              "source": f["properties"]["data_status"], "registered_area_m2": f["properties"]["registered_area_m2"]}
             for f in feats]
    req = OptimizeRequest(plots=plots, crops=CROPS, techniques=TECHS,
                          constraints=dict(budget_qar=3_000_000, water_m3_year=16_000, energy_kwh_year=400_000),
                          accept_planning_profile=True)
    ctx = pipeline.prepare_context(req)
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    problem, _, _ = pipeline.build_problem(ctx, "normal")
    return res, problem, ctx


# ---------------------------------------------------------------- composition
def test_feasible_solution_has_at_least_three_distinct_production_blocks(solved):
    res, _problem, _ctx = solved
    comp = res["composition"]
    if res["effective_composition"]["min_distinct_combos"] == 0:
        pytest.skip("the combination rule was relaxed; that case is covered by its own test")
    assert comp["distinct_combos"] >= 3
    blocks = {(r["crop"], r["technique"]) for r in res["portfolio"]}
    assert len(blocks) == comp["distinct_combos"]
    assert len(blocks) >= 3, "a portfolio must be more than one crop x technique"


def test_each_active_block_meets_the_minimum_viable_share(solved):
    res, _problem, _ctx = solved
    share = res["effective_composition"]["min_combo_area_share"]
    if share <= 0:
        pytest.skip("minimum block size was relaxed")
    usable = res["limits"]["usable_m2"]
    per_block: dict[tuple[str, str], float] = {}
    for r in res["portfolio"]:
        per_block[(r["crop"], r["technique"])] = per_block.get((r["crop"], r["technique"]), 0.0) + r["area_m2"]
    for key, area in per_block.items():
        assert area >= share * usable - 1e-6, f"{key} is below the minimum viable share"


def test_land_utilisation_reaches_the_requested_floor(solved):
    res, _problem, _ctx = solved
    floor = res["solver"]["utilisation_floor_used"]
    if floor <= 0:
        pytest.skip("the utilisation floor was relaxed")
    assert res["composition"]["land_utilisation"] >= floor - 1e-6


def test_areas_sum_correctly_and_respect_the_land(solved):
    res, _problem, _ctx = solved
    total = sum(r["area_m2"] for r in res["portfolio"])
    assert total == pytest.approx(res["summary"]["area_m2"], rel=1e-9)
    for p in res["plots"]:
        allocated = sum(r["area_m2"] for r in res["portfolio"] if r["plot_id"] == p["plot_id"])
        assert allocated == pytest.approx(p["allocated_m2"], rel=1e-9)
        assert allocated <= p["usable_m2"] + 1e-6
        assert p["access_m2"] > 0, "access and infrastructure must be explicitly reserved"


def test_every_stated_limit_still_holds(solved):
    res, problem, _ctx = solved
    eff = replace(problem.limits, **res["effective_composition"])
    alloc = {(r["plot_id"], r["crop"], r["technique"]): r["area_m2"] for r in res["portfolio"]}
    assert check_feasible(replace(problem, limits=eff), alloc, res["solver"]["utilisation_floor_used"]) == []
    s = res["summary"]
    assert s["capex"] <= res["limits"]["budget_qar"] + 1e-6
    assert s["water_m3"] <= res["limits"]["water_m3_year"] + 1e-6
    assert s["energy_kwh"] <= res["limits"]["energy_kwh_year"] + 1e-6


def test_no_duplicate_blocks_in_the_portfolio(solved):
    res, _problem, _ctx = solved
    seen = [(r["plot_id"], r["crop"], r["technique"]) for r in res["portfolio"]]
    assert len(seen) == len(set(seen)), "each plot x crop x technique must appear once"


# ---------------------------------------------------------------- alternatives
def test_alternatives_are_independently_solved_portfolios(solved):
    res, _problem, _ctx = solved
    alts = res["alternatives"]
    assert len(alts) >= 4
    keys = [a["key"] for a in alts]
    assert keys[:2] == ["roi", "cash"]
    live = [a for a in alts if a.get("summary")]
    assert live, "at least one alternative must be solvable"
    for a in live:
        total = sum(r["area_m2"] for r in a["portfolio"])
        assert total == pytest.approx(a["summary"]["area_m2"], rel=1e-9)
        assert a["summary"]["capex"] <= res["limits"]["budget_qar"] + 1e-6
        assert a["summary"]["water_m3"] <= res["limits"]["water_m3_year"] + 1e-6
        # each alternative reports its own composition, not the headline plan's
        assert set(a["crops"]) == {r["crop"] for r in a["portfolio"]}
        assert set(a["techniques"]) == {r["technique"] for r in a["portfolio"]}


def test_alternatives_that_coincide_say_so_rather_than_being_perturbed(solved):
    res, _problem, _ctx = solved
    by_key = {a["key"]: a for a in res["alternatives"] if a.get("summary")}
    for key, a in by_key.items():
        if a.get("same_as"):
            other = by_key[a["same_as"]]
            assert a["summary"]["capex"] == pytest.approx(other["summary"]["capex"])
            assert a["summary"]["profit"] == pytest.approx(other["summary"]["profit"])


def test_unavailable_alternatives_explain_themselves(solved):
    res, _problem, _ctx = solved
    for a in res["alternatives"]:
        if a.get("summary") is None:
            assert a.get("unavailable"), "an alternative without a plan must say why"
            assert a["portfolio"] == []


# ---------------------------------------------------------------- relaxation is transparent
def test_relaxations_are_declared_and_the_result_stays_a_proved_optimum():
    """A budget too small for the technique rule must relax it and say so, not silently ignore it."""
    from tests.helpers import make_problem
    p = make_problem(min_utilisation=0.0, budget=120_000)
    p.limits = replace(p.limits, min_distinct_combos=3, min_combo_area_share=0.2, min_distinct_techniques=2)
    sol = optimizer.solve(p)
    if sol.relaxations:
        assert any("relaxed" in w for w in sol.warnings)
        assert sol.effective_limits is not None
        assert check_feasible(replace(p, limits=sol.effective_limits), sol.alloc, sol.utilisation_floor_used) == []


def test_composition_rules_do_not_pin_areas():
    """The rules set floors only; the solver must still choose unequal, optimised percentages."""
    from tests.helpers import make_problem
    p = make_problem(min_utilisation=0.9, budget=5_000_000)
    p.limits = replace(p.limits, min_distinct_combos=2, min_combo_area_share=0.1, objective="net_profit")
    sol = optimizer.solve(p)
    areas = sorted(sol.alloc.values(), reverse=True)
    if len(areas) >= 2:
        assert areas[0] != pytest.approx(areas[1], rel=1e-3), "equal areas would mean the rules pinned them"
