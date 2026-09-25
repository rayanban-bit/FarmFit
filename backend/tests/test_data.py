"""Data layer: unit conversions, missing-data handling, provenance, adapters' failure behaviour."""
import json
import math

import pandas as pd
import pytest

from app import catalog, climate, crop_model, provenance, units
from app.adapters import base, nasa_power, qatar_open_data as qod, soilgrids
from app.adapters.base import AdapterUnavailable, cached_fetch


# ---------------------------------------------------------------- unit conversions
def test_unit_conversions():
    assert units.ha_to_m2(1) == 10_000
    assert units.m2_to_ha(2_500) == 0.25
    assert units.t_per_ha_to_kg_per_m2(50) == pytest.approx(5.0)  # 50 t/ha = 5 kg/m2
    assert units.mm_to_m3_per_m2(300) == pytest.approx(0.3)
    assert units.mj_to_kwh(3.6) == pytest.approx(1.0)
    assert units.kelvin_to_c(273.15) == 0


def test_polygon_area_matches_expected_size():
    # 0.001 deg x 0.001 deg near 25.3 N is about 111.2 m x 100.6 m
    ring = [[51.4, 25.3], [51.401, 25.3], [51.401, 25.301], [51.4, 25.301], [51.4, 25.3]]
    a = units.ring_area_m2(ring)
    expected = 111_195 * 0.001 * 111_195 * 0.001 * math.cos(math.radians(25.3005))
    assert a == pytest.approx(expected, rel=2e-3)


def test_polygon_with_hole_and_multipolygon_area():
    outer = [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]
    hole = [[0.004, 0.004], [0.006, 0.004], [0.006, 0.006], [0.004, 0.006], [0.004, 0.004]]
    full = units.geometry_area_m2({"type": "Polygon", "coordinates": [outer]})
    holed = units.geometry_area_m2({"type": "Polygon", "coordinates": [outer, hole]})
    assert holed == pytest.approx(full * (1 - 0.04), rel=1e-3)
    multi = units.geometry_area_m2({"type": "MultiPolygon", "coordinates": [[outer], [outer]]})
    assert multi == pytest.approx(2 * full)


def test_live_cadastre_metadata_matches_the_documented_service():
    """The layer we rely on must really be a public, queryable polygon layer in the Qatar National Grid."""
    from app.adapters import cadastre
    from app.adapters.base import AdapterUnavailable
    try:
        meta, m = cadastre.describe()
    except AdapterUnavailable as exc:
        pytest.skip(f"cadastral service unavailable and not cached: {exc}")
    assert meta["geometryType"] == "esriGeometryPolygon"
    assert "Query" in (meta["capabilities"] or "")
    assert meta["native_wkid"] == 2932  # QND 1995 / Qatar National Grid
    names = {f["name"] for f in meta["fields"]}
    assert {"OBJECTID", "PIN", "PDAREA"} <= names
    assert "CadastrePlots" in m["source_url"]


def test_live_cadastre_returns_wgs84_polygons_with_registered_areas():
    from app.adapters import cadastre
    from app.adapters.base import AdapterUnavailable
    try:
        fc, _ = cadastre.query_bbox((51.15, 25.35, 51.30, 25.45), min_area_m2=5000, limit=10)
    except AdapterUnavailable as exc:
        pytest.skip(f"cadastral service unavailable and not cached: {exc}")
    assert fc["features"]
    for f in fc["features"]:
        q = f["properties"]
        assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
        lon, lat = q["centroid"]
        assert 50.5 < lon < 52.0 and 24.4 < lat < 26.3, "coordinates must be WGS84 inside Qatar"
        assert q["data_status"] == "Live cadastral service"
        assert q["registered_area_m2"] > 0
        # the officially registered area must agree with a geodesic area recomputed from the boundary
        assert abs(q["geodesic_area_m2"] - q["registered_area_m2"]) / q["registered_area_m2"] < 0.02
        assert str(q["plot_pin"]) == q["id"] or str(q["object_id"]) == q["id"]
        # normalised keys must not collide case-insensitively with the raw ArcGIS attributes,
        # or case-insensitive JSON parsers (PowerShell, some .NET) reject the response outright
        lower = [k.lower() for k in q]
        assert len(lower) == len(set(lower)), f"duplicate keys ignoring case: {sorted(k for k in lower if lower.count(k) > 1)}"


def test_cadastre_rejects_a_malformed_bbox():
    from app.adapters import cadastre
    with pytest.raises(ValueError):
        cadastre.query_bbox((52.0, 25.0, 51.0, 26.0))


# ---------------------------------------------------------------- climate / model correctness
def test_extraterrestrial_radiation_matches_fao56_example_8():
    # FAO-56 Example 8: latitude 20 S, 3 September (day 246) -> Ra = 32.2 MJ m-2 day-1
    assert float(climate.extraterrestrial_radiation(-20.0, [246])[0]) == pytest.approx(32.2, abs=0.1)


def test_et0_is_physically_plausible_for_a_hot_dry_day():
    idx = pd.date_range("2024-07-01", periods=3)
    df = pd.DataFrame({"tmax": 44.0, "tmin": 31.0, "tmean": 37.0, "rs": 27.0, "rh": 35.0, "ws": 4.0, "rain": 0.0}, index=idx)
    et0 = climate.et0_daily(df, 25.5)
    assert 8.0 < et0.iloc[0] < 15.0


def test_usda_texture_classes():
    assert soilgrids.usda_texture(90, 5, 5) == "Sand"
    assert soilgrids.usda_texture(63, 18, 18) == "SandyLoam"
    assert soilgrids.usda_texture(20, 30, 50) == "Clay"


def test_nasa_power_grid_snapping():
    lon, lat = nasa_power.snap_to_native_cell(51.4123, 25.3987)
    assert lat == 25.5 and lon == 51.25
    assert nasa_power.snap_to_native_cell(51.2105, 25.3902) == (51.25, 25.5)


def test_salinity_factor_maas_hoffman():
    assert crop_model.salinity_factor(None, 2.5, 9.9) == 1.0  # unknown EC -> no penalty (and the UI shows it missing)
    assert crop_model.salinity_factor(2.0, 2.5, 9.9) == 1.0
    assert crop_model.salinity_factor(4.5, 2.5, 9.9) == pytest.approx(1 - 0.099 * 2.0)
    assert crop_model.salinity_factor(50, 2.5, 9.9) == 0.0


QATAR_LIKE = {"tmax": [23, 24.4, 28.4, 33.3, 38.7, 42.7, 43.2, 43.2, 41.4, 36.9, 30.7, 25.2],
              "tmin": [13, 14, 17, 21, 26, 29, 31, 31, 28, 24, 19, 15], "tmean": [18, 19, 22.5, 27, 32, 36, 37, 37, 34.5, 30, 25, 20],
              "et0_mm_day": [3.2, 3.9, 5.3, 6.6, 8.6, 10.1, 9.3, 8.3, 7.4, 5.8, 4.3, 3.2],
              "rain_mm_month": [24, 5, 5, 19, 5, 0, 6, 0, 0, 5, 9, 8], "days": crop_model.MONTH_DAYS, "years": 6}
TOMATO_T = {"tmin_mean": 8, "tmax_mean": 35, "topt_low": 18, "topt_high": 27}


def test_open_field_tomato_window_is_the_cool_season():
    s = crop_model.build_schedule(QATAR_LIKE, TOMATO_T, 0, 0, False, 135, 10, 1)
    assert s is not None
    assert [m + 1 for m in s["run_months"]] == [11, 12, 1, 2, 3, 4]  # Nov-Apr
    assert s["cycles"] == 1


def test_no_window_returns_none_not_a_guess():
    strawberry = {"tmin_mean": 5, "tmax_mean": 27, "topt_low": 12, "topt_high": 22}
    assert crop_model.build_schedule(QATAR_LIKE, strawberry, 0, 0, False, 180, 10, 1) is None
    # fully controlled systems are feasible all year
    assert crop_model.build_schedule(QATAR_LIKE, strawberry, 0, 0, True, 90, 10, 3)["run_days"] == pytest.approx(365.25)


def test_monthly_water_only_in_operating_months_and_positive():
    s = crop_model.build_schedule(QATAR_LIKE, TOMATO_T, 0, 0, False, 135, 10, 1)
    w = crop_model.monthly_water_kc(QATAR_LIKE, s, [30, 40, 40, 25], [0.6, 1.15, 0.8], 0.9, 1.0, 0.0, True, 0.6)
    assert all(v == 0 for m, v in enumerate(w) if m not in s["run_months"])
    assert sum(w) > 0.2  # 0.2 m3/m2 = 200 mm - lower bound for a winter tomato crop in Qatar
    assert sum(w) < 0.9


def test_monthly_energy_conserves_annual_total_scaled_by_operating_fraction():
    s = crop_model.build_schedule(QATAR_LIKE, TOMATO_T, 8, 4, False, 135, 10, 2)
    e = crop_model.monthly_energy(QATAR_LIKE, s, 60.0, 0.8)
    assert sum(e) == pytest.approx(60.0 * s["run_days"] / 365.0)


# ---------------------------------------------------------------- missing data: never invented
def test_robust_yield_rejects_inconsistent_records_with_reasons():
    obs = [{"year": str(y), "area_ha": 100.0, "production_t": 5000.0, "reported_t_ha": 50.0} for y in range(2018, 2023)]
    obs.append({"year": "2023", "area_ha": 27682.3, "production_t": 381.8, "reported_t_ha": 0.01})  # real bad record in the dataset
    r = qod.robust_yield(obs)
    assert r["t_ha"] == pytest.approx(50.0)
    assert r["n"] == 5
    assert any(x["year"] == "2023" for x in r["rejected"])


def test_robust_yield_returns_none_when_nothing_usable():
    r = qod.robust_yield([{"year": "2024", "area_ha": None, "production_t": None, "reported_t_ha": None}])
    assert r["t_ha"] is None and r["n"] == 0 and r["rejected"]


def test_cached_fetch_raises_when_source_down_and_no_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "CACHE_DIR", tmp_path)

    def boom():
        raise RuntimeError("network down")

    with pytest.raises(AdapterUnavailable):
        cached_fetch("unit_test", {"k": 1}, boom)


def test_cached_fetch_uses_stale_cache_when_source_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(base, "CACHE_DIR", tmp_path)
    payload, meta = cached_fetch("unit_test", {"k": 2}, lambda: {"v": 1})
    assert meta["status"] == "live"
    p, m = cached_fetch("unit_test", {"k": 2}, lambda: {"v": 2}, ttl_days=None)
    assert p == {"v": 1} and m["status"] == "cached"

    def boom():
        raise RuntimeError("down")

    p, m = cached_fetch("unit_test", {"k": 2}, boom, ttl_days=0, force=True)
    assert p == {"v": 1} and m["status"] == "stale_cache"


# ---------------------------------------------------------------- provenance
def test_every_catalog_number_has_a_known_source_and_catalog_is_consistent():
    cat = catalog.base_catalog()
    assert catalog.validate(cat) == []


def test_validate_flags_unknown_source_and_incompatibility():
    cat = catalog.base_catalog()
    cat["crops"]["tomato"]["price_qar_kg"]["src"] = "does_not_exist"
    cat["techniques"]["vertical_hydroponics"]["compatible_crops"].append("tomato")
    problems = catalog.validate(cat)
    assert any("does_not_exist" in p for p in problems)
    assert any("no yield entry" in p for p in problems)


def test_overrides_are_relabelled_user_supplied():
    cat, _ = catalog.resolve(catalog.base_catalog(),
                             {"crops": {"tomato": {"price_qar_kg": 9.5}}, "techniques": {"greenhouse": {"capex_qar_m2": 200}}},
                             accept_planning_profile=False)
    assert cat["crops"]["tomato"]["price_qar_kg"]["value"] == 9.5
    assert cat["crops"]["tomato"]["price_qar_kg"]["src"] == "user"
    assert cat["techniques"]["greenhouse"]["capex_qar_m2"]["src"] == "user"
    assert provenance.source("user")["type"] == "user_supplied"


def test_required_inputs_start_unresolved_and_block_their_combinations():
    base = catalog.base_catalog()
    cat, missing = catalog.resolve(base, None, accept_planning_profile=False)
    assert missing, "a fresh catalog must report unresolved required inputs"
    assert cat["crops"]["tomato"]["price_qar_kg"]["value"] is None
    need = catalog.missing_for(cat, "tomato", "greenhouse")
    assert need and all(n["label"] for n in need)


def test_missing_for_is_empty_once_everything_is_supplied():
    cat, _ = catalog.resolve(catalog.base_catalog(), None, accept_planning_profile=True)
    assert catalog.missing_for(cat, "tomato", "greenhouse") == []
    # vertical hydroponics deliberately has no planning figure - a vendor quotation is required
    assert catalog.missing_for(cat, "lettuce", "vertical_hydroponics")


def test_row_from_param_marks_missing_values():
    row = provenance.row_from_param("x", "X", {"value": None, "unit": "kg", "src": "qatar_od_crops"})
    assert row.status == "missing"
    r2 = provenance.missing_row("soil.ec", "EC", "dS/m", "not provided")
    assert r2.value is None and r2.status == "missing" and r2.type == "user_supplied"


def test_provenance_registry_types_are_allowed_kinds():
    reg = provenance.registry()
    assert {s["type"] for s in reg.values()} <= set(provenance.TYPES)
    for sid, s in reg.items():
        assert s["name"] and "status" in s, sid


def test_catalog_json_files_are_valid_json():
    for name in ("crops.json", "techniques.json", "infrastructure.json", "scenarios.json", "defaults.json", "sources.json"):
        json.loads((provenance.DATA_DIR / name).read_text(encoding="utf-8"))
