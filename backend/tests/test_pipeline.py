"""End-to-end on REAL Qatar cadastral plots: live cadastre -> climate/soil -> AquaCrop -> OR-Tools MIP.

Uses the seeded local cache, so it runs offline; with a network the adapters refresh it.
"""
import pytest

from app import catalog as catalog_mod, pipeline
from app.adapters import cadastre
from app.adapters.base import AdapterUnavailable
from app.optimizer import check_feasible
from app.schemas import OptimizeRequest

CROPS = ["tomato", "cucumber", "lettuce", "bell_pepper", "strawberry"]
TECHS = ["open_field", "greenhouse", "hydroponic_greenhouse", "vertical_hydroponics"]
# Al Shahaniya farming belt - a real, stable area of the cadastre.
BBOX = (51.15, 25.35, 51.30, 25.45)


@pytest.fixture(scope="module")
def real_plots():
    try:
        fc, _ = cadastre.query_bbox(BBOX, min_area_m2=5000, limit=25)
    except AdapterUnavailable as exc:  # pragma: no cover - only when offline with a cold cache
        pytest.skip(f"cadastral service unavailable and not cached: {exc}")
    feats = [f for f in fc["features"] if 5_000 <= f["properties"]["area_m2"] <= 60_000][:3]
    if len(feats) < 2:
        pytest.skip("not enough agricultural-scale plots returned")
    return [{"id": f["properties"]["id"], "name": f["properties"]["name"], "geometry": f["geometry"],
             "source": f["properties"]["data_status"], "registered_area_m2": f["properties"]["registered_area_m2"]}
            for f in feats]


def make_request(plots, accept=True, **c):
    cons = dict(budget_qar=1_200_000, water_m3_year=16_000, energy_kwh_year=400_000)
    cons.update(c)
    return OptimizeRequest(plots=plots, crops=CROPS, techniques=TECHS, constraints=cons, accept_planning_profile=accept)


@pytest.fixture(scope="module")
def ctx(real_plots):
    return pipeline.prepare_context(make_request(real_plots, accept=True, objective="net_profit"))


# ---------------------------------------------------------------- the real end-to-end flow
def test_runs_on_live_cadastral_plots_and_is_feasible(ctx, real_plots):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    assert res["status"] in ("OPTIMAL", "FEASIBLE")
    assert res["portfolio"], "the portfolio must come from the solver"
    problem, _, _ = pipeline.build_problem(ctx, "normal")
    alloc = {(r["plot_id"], r["crop"], r["technique"]): r["area_m2"] for r in res["portfolio"]}
    assert check_feasible(problem, alloc, res["solver"]["utilisation_floor_used"]) == []
    for p in res["plots"]:
        assert p["allocated_m2"] <= p["usable_m2"] + 1e-6
        assert p["geometry_source"] == "Live cadastral service"


def test_plot_area_uses_the_officially_registered_cadastral_area(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    for p in res["plots"]:
        assert p["registered_area_m2"] is not None
        assert p["area_m2"] == pytest.approx(p["registered_area_m2"])
        # the geodesic area recomputed from the boundary must corroborate it closely
        assert abs(p["geodesic_area_m2"] - p["registered_area_m2"]) / p["registered_area_m2"] < 0.02


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
    for key in ("baseline", "baseline_free"):
        b = res[key]
        if b:
            assert res["summary"]["net_gain"] >= b["summary"]["net_gain"] - 1e-3


def test_scenarios_recompute_with_the_same_model(ctx):
    normal = pipeline.solve_scenario(ctx, "normal", with_context=False)
    dry = pipeline.solve_scenario(ctx, "water_constrained", with_context=False)
    assert dry["limits"]["water_m3_year"] == pytest.approx(0.4 * normal["limits"]["water_m3_year"])
    assert dry["summary"]["water_m3"] <= dry["limits"]["water_m3_year"] + 1e-6
    assert dry["summary"]["water_m3"] <= normal["summary"]["water_m3"] + 1e-6
    assert dry["solver"]["backend"] == normal["solver"]["backend"]
    # Cutting the water allowance only changes the design when water actually binds. If the budget caps the
    # farm below the reduced allowance, an unchanged plan is the correct answer, not a broken scenario.
    if normal["summary"]["water_m3"] > dry["limits"]["water_m3_year"]:
        assert dry["summary"]["area_m2"] < normal["summary"]["area_m2"]
    else:
        assert dry["limiting"]["limiting_factor"] == normal["limiting"]["limiting_factor"]


def test_a_binding_water_limit_does_shrink_the_farm(real_plots):
    """Same model, water tight enough to bind: the design must change."""
    loose = pipeline.prepare_context(make_request(real_plots, accept=True, water_m3_year=16_000))
    tight = pipeline.prepare_context(make_request(real_plots, accept=True, water_m3_year=1_500))
    a = pipeline.solve_scenario(loose, "normal", with_context=False)
    b = pipeline.solve_scenario(tight, "normal", with_context=False)
    assert b["summary"]["water_m3"] <= 1_500 + 1e-6
    assert b["summary"]["area_m2"] < a["summary"]["area_m2"]
    assert b["limiting"]["limiting_factor"] in ("water_year", "water_month")


def test_limiting_diagnosis_identifies_the_binding_constraint(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    d = res["limiting"]
    assert d["headline"]
    assert d["allocated_m2"] + d["unallocated_m2"] == pytest.approx(d["usable_m2"], rel=1e-9)
    binding = [l for l in d["limits"] if l["binding"]]
    if d["limiting_factor"] not in (None, "land"):
        assert binding, "an unallocated farm must name the limit that stopped it"
        # the named limit must be the one supporting the least land
        supported = [l["land_supported_m2"] for l in d["limits"] if l["land_supported_m2"] is not None and l["key"] != "land"]
        named = next(l for l in d["limits"] if l["key"] == d["limiting_factor"])
        assert named["land_supported_m2"] == pytest.approx(min(supported))


def test_no_invented_monthly_cap_when_only_an_annual_quota_is_given(ctx):
    """An annual allowance must be usable in whichever months the crops need it."""
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    assert res["monthly"]["water_cap_m3"] is None
    assert res["monthly"]["energy_cap_kwh"] is None
    assert res["limits"]["water_peak_m3_month"] is None


def test_aquacrop_is_only_used_for_open_field_tomato(ctx):
    _, _, detail = pipeline.build_problem(ctx, "normal")
    for (_pid, cid, tid), d in detail.items():
        if d["yield_kind"] == "aquacrop":
            assert (cid, tid) == ("tomato", "open_field")
    assert all(d["yield_kind"] != "aquacrop" for (_p, _c, t), d in detail.items() if t != "open_field")


def test_opex_is_built_from_components(ctx):
    _, _, detail = pipeline.build_problem(ctx, "normal")
    assert detail
    for d in detail.values():
        br = d["opex_breakdown"]
        assert set(br) == {"labour", "maintenance", "seedlings", "nutrients", "water", "electricity"}
        assert all(v >= 0 for v in br.values())
        assert br["water"] > 0 and br["electricity"] > 0  # priced from metered use, not a lump figure


# ---------------------------------------------------------------- refusing rather than inventing
def test_without_inputs_every_scenario_is_refused_and_nothing_is_invented(real_plots):
    strict = pipeline.prepare_context(make_request(real_plots, accept=False))
    assert strict.missing_inputs, "required inputs must be reported as unresolved"
    res = pipeline.solve_scenario(strict, "normal", with_context=False)
    assert res["status"] == "INFEASIBLE"
    assert res["portfolio"] == []
    assert res["summary"]["revenue"] == 0
    kinds = {e.get("kind") for e in res["excluded"]}
    assert "required_input" in kinds
    for e in res["excluded"]:
        if e["kind"] == "required_input":
            assert e["missing"] and "Required input unavailable" in e["reason"]


def test_vertical_farming_stays_excluded_even_with_the_planning_profile(ctx):
    """It has no profile value on purpose: a real vendor quotation is required."""
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    vertical = [e for e in res["excluded"] if e["technique"] == "vertical_hydroponics" and e.get("kind") == "required_input"]
    assert vertical, "vertical hydroponics must be refused without a quotation"
    assert all(b["technique"] != "vertical_hydroponics" for b in res["portfolio"])


def test_supplying_one_price_resolves_only_that_input(real_plots):
    base, missing_before = catalog_mod.resolve(catalog_mod.base_catalog(), None, False)
    ov = {"crops": {"tomato": {"price_qar_kg": 5.25}}}
    cat, missing_after = catalog_mod.resolve(catalog_mod.base_catalog(), ov, False)
    assert cat["crops"]["tomato"]["price_qar_kg"]["value"] == 5.25
    assert cat["crops"]["tomato"]["price_qar_kg"]["src"] == "user"
    assert len(missing_after) == len(missing_before) - 1


def test_planning_profile_is_labelled_unverified_not_sourced():
    cat, missing = catalog_mod.resolve(catalog_mod.base_catalog(), None, accept_planning_profile=True)
    gh = cat["techniques"]["greenhouse"]["capex_qar_m2"]
    assert gh["value"] == gh["profile_value"]
    assert gh["src"] == "planning_profile"
    # the vertical farm has no profile value, so it must still be unresolved
    assert any(m["owner"] == "vertical_hydroponics" for m in missing)


def test_user_value_beats_the_planning_profile(real_plots):
    ov = {"techniques": {"greenhouse": {"capex_qar_m2": 700}}}
    cat, _ = catalog_mod.resolve(catalog_mod.base_catalog(), ov, accept_planning_profile=True)
    leaf = cat["techniques"]["greenhouse"]["capex_qar_m2"]
    assert leaf["value"] == 700 and leaf["src"] == "user"


# ---------------------------------------------------------------- provenance surface
def test_data_panel_is_traceable_and_shows_missing_values(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    rows = res["data_panel"]
    assert {r["type"] for r in rows} <= {"official_qatar", "official_dataset", "scientific_model", "peer_reviewed",
                                         "open_dataset", "vendor_data", "user_supplied", "unverified"}
    assert all(r["source"] and r["type_label"] for r in rows)
    ec = next(r for r in rows if r["key"] == "soil.ec")
    assert ec["value"] is None and ec["status"] == "missing"
    # the live cadastre must be cited as the source of the boundary and the area
    geo = next(r for r in rows if r["key"].endswith(".geometry"))
    assert geo["type"] == "official_qatar" and "cadastral" in str(geo["value"]).lower()
    assert any(r["type"] == "official_qatar" and "yield" in r["key"] for r in rows)


def test_unverified_values_are_visibly_unverified(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    unver = [r for r in res["data_panel"] if r["type"] == "unverified"]
    assert unver, "the accepted planning profile must appear as Unverified"
    assert res["accepted_planning_profile"] is True


def test_explanations_reference_only_solved_quantities(ctx):
    res = pipeline.solve_scenario(ctx, "normal", with_context=False)
    text = " ".join(e["text"] for e in res["explanations"])
    for r in res["portfolio"]:
        assert f"{r['area_m2']:,.0f}" in text
