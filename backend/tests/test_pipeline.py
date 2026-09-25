"""End-to-end: real (cached) data -> AquaCrop -> MIP. Uses the seeded local cache; falls back to live APIs if stale."""
import pytest

from app import pipeline
from app.adapters import cadastre
from app.optimizer import check_feasible
from app.schemas import OptimizeRequest

CROPS = ["tomato", "cucumber", "lettuce", "bell_pepper", "strawberry"]
TECHS = ["open_field", "greenhouse", "hydroponic_greenhouse", "vertical_hydroponics"]


def make_request(ids=("DEMO-01", "DEMO-03"), **c):
    fc = cadastre.demo_parcels()
    plots = [{"id": f["properties"]["id"], "name": f["properties"]["name"], "geometry": f["geometry"], "source": f["properties"]["source"]}
             for f in fc["features"] if f["properties"]["id"] in ids]
    cons = dict(budget_qar=1_200_000, water_m3_year=16_000, energy_kwh_year=400_000)
    cons.update(c)
    return OptimizeRequest(plots=plots, crops=CROPS, techniques=TECHS, constraints=cons)


@pytest.fixture(scope="module")
def ctx():
    return pipeline.prepare_context(make_request(("DEMO-01", "DEMO-02", "DEMO-03"), objective="net_profit"))


def test_demo_runs_through_the_real_optimizer_and_is_feasible(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    assert res["status"] in ("OPTIMAL", "FEASIBLE")
    assert res["portfolio"], "portfolio must come from the solver"
    problem, _, _ = pipeline.build_problem(ctx, "normal")
    alloc = {(r["plot_id"], r["crop"], r["technique"]): r["area_m2"] for r in res["portfolio"]}
    assert check_feasible(problem, alloc, res["solver"]["utilisation_floor_used"]) == []
    # per-plot land: allocated <= usable
    for p in res["plots"]:
        assert p["allocated_m2"] <= p["usable_m2"] + 1e-6


def test_summary_numbers_are_consistent(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    s = res["summary"]
    assert s["profit"] == pytest.approx(s["revenue"] - s["opex"])
    assert s["roi"] == pytest.approx((s["horizon_years"] * s["profit"] - s["capex"]) / s["capex"])
    assert sum(r["revenue"] for r in res["portfolio"]) == pytest.approx(s["revenue"])
    assert s["cash_flows"][0] == pytest.approx(-s["capex"])
    assert res["limits"]["budget_qar"] >= s["capex"] - 1e-6


def test_optimized_is_at_least_as_good_as_both_baselines(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    obj = "net_gain"
    for key in ("baseline", "baseline_free"):
        b = res[key]
        if b:
            assert res["summary"][obj] >= b["summary"][obj] - 1e-3


def test_scenarios_recompute_with_same_model_and_change_constraints(ctx):
    normal = pipeline.solve_scenario(ctx, "normal", with_context=False)
    dry = pipeline.solve_scenario(ctx, "water_constrained", with_context=False)
    assert dry["limits"]["water_m3_year"] == pytest.approx(0.4 * normal["limits"]["water_m3_year"])
    assert dry["summary"]["water_m3"] <= dry["limits"]["water_m3_year"] + 1e-6
    assert dry["summary"]["water_m3"] < normal["summary"]["water_m3"]
    assert dry["solver"]["backend"] == normal["solver"]["backend"]


def test_energy_expensive_changes_prices_not_the_model(ctx):
    normal = pipeline.solve_scenario(ctx, "normal", with_context=False)
    exp = pipeline.solve_scenario(ctx, "energy_expensive", with_context=False)
    assert exp["summary"]["opex"] >= normal["summary"]["opex"] - 1e-6 or exp["summary"]["energy_kwh"] <= normal["summary"]["energy_kwh"]


def test_aquacrop_is_only_used_for_open_field_tomato(ctx):
    _, _, detail = pipeline.build_problem(ctx, "normal")
    for (pid, cid, tid), d in detail.items():
        if d["yield_kind"] == "aquacrop":
            assert (cid, tid) == ("tomato", "open_field")
    assert any(d["yield_kind"] == "aquacrop" for (p, c, t), d in detail.items() if (c, t) == ("tomato", "open_field"))
    assert all(d["yield_kind"] != "aquacrop" for (p, c, t), d in detail.items() if t != "open_field")


def test_data_panel_labels_types_and_shows_missing_salinity(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    rows = res["data_panel"]
    assert {r["type"] for r in rows} <= {"official_dataset", "scientific_model", "open_dataset", "user_supplied", "prototype_assumption"}
    ec = next(r for r in rows if r["key"] == "soil.ec")
    assert ec["value"] is None and ec["status"] == "missing"
    assert any(r["type"] == "prototype_assumption" for r in rows)
    assert all(r["source"] and r["type_label"] for r in rows)
    geo = next(r for r in rows if r["key"].endswith(".geometry"))
    assert "DEMO" in str(geo["value"])


def test_explanations_reference_only_solved_quantities(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    text = " ".join(e["text"] for e in res["explanations"])
    for r in res["portfolio"]:
        assert f"{r['area_m2']:,.0f}" in text  # every block's solver-derived area is quoted verbatim


def test_infeasible_request_reports_status_not_a_fake_plan():
    ctx2 = pipeline.prepare_context(make_request(("DEMO-05",), budget_qar=500.0))
    res = pipeline.solve_scenario(ctx2, "normal", with_context=False)
    assert res["status"] == "INFEASIBLE"
    assert res["portfolio"] == []
