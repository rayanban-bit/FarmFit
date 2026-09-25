"""The opening viewport must be derived from live cadastral data, not a hardcoded coordinate."""
import math

import pytest

from app import exploration as ex
from app.adapters.base import AdapterUnavailable
from app.units import haversine_m

QATAR = (50.7, 24.4, 51.8, 26.3)  # lon/lat envelope of the country


@pytest.fixture(scope="module")
def area():
    try:
        data, _meta = ex.exploration_area()
    except AdapterUnavailable as exc:  # pragma: no cover - only with a cold cache and no network
        pytest.skip(f"cadastral service unavailable: {exc}")
    return data


def test_viewport_is_inside_qatar_and_correctly_ordered(area):
    minx, miny, maxx, maxy = area["bbox"]
    assert minx < maxx and miny < maxy
    assert QATAR[0] < minx and maxx < QATAR[2]
    assert QATAR[1] < miny and maxy < QATAR[3]
    lon, lat = area["centre"]
    assert minx <= lon <= maxx and miny <= lat <= maxy


def test_viewport_holds_several_real_plots_of_differing_size(area):
    assert area["plot_count"] >= ex.MIN_PLOTS_IN_CLUSTER
    assert area["min_area_m2"] >= ex.MIN_PLOT_M2
    assert area["max_area_m2"] <= ex.MAX_PLOT_M2
    # "noticeably different sizes" - the largest plot must be a clear multiple of the smallest
    assert area["max_area_m2"] / area["min_area_m2"] >= 3.0


def test_viewport_is_small_enough_to_read_on_one_screen(area):
    minx, miny, maxx, maxy = area["bbox"]
    width = haversine_m(minx, (miny + maxy) / 2, maxx, (miny + maxy) / 2)
    height = haversine_m((minx + maxx) / 2, miny, (minx + maxx) / 2, maxy)
    assert 200 < width < 6_000, "the opening view should be a farm cluster, not a region"
    assert 200 < height < 6_000
    # and it must be zoomed in past the level at which the app loads parcels
    assert math.log2(360 / (maxx - minx)) > 12.5


def test_the_choice_is_explained_and_reproducible(area):
    assert area["label"] == "Suggested exploration area - real Qatar cadastral data"
    assert area["reasons"] and all(isinstance(r, str) and r for r in area["reasons"])
    assert area["window"] in {name for name, _ in ex.SEARCH_WINDOWS}
    assert 0.0 <= area["score"] <= 1.0
    again, _ = ex.exploration_area()
    assert again["bbox"] == area["bbox"], "the same data must give the same viewport"


def test_every_search_window_was_actually_queried_live(area):
    searched = {w["window"] for w in area["windows_searched"]}
    assert searched == {name for name, _ in ex.SEARCH_WINDOWS}
    assert sum(w["plots_found"] for w in area["windows_searched"]) > 100
    assert any(w.get("candidate_clusters", 0) > 0 for w in area["windows_searched"])


def test_only_informative_criteria_contribute_to_the_score(area):
    used, unused = set(area["criteria_used"]), set(area["criteria_uninformative"])
    assert used, "at least one criterion must have discriminated"
    assert used.isdisjoint(unused)
    assert used | unused == set(area["weights"])


def test_a_criterion_with_no_spread_is_dropped_not_awarded_full_marks():
    """Regression: identical values used to normalise to 1.0, silently awarding every candidate full marks."""
    values, informative = ex._normalise([4.0, 4.0, 4.0])
    assert informative is False
    assert values == [0.0, 0.0, 0.0]
    values, informative = ex._normalise([1.0, 3.0])
    assert informative is True
    assert values == [0.0, 1.0]


def test_plot_count_is_scored_against_a_comfortable_band():
    lo, hi = ex.IDEAL_PLOTS
    assert ex._count_score(lo) == 1.0 and ex._count_score(hi) == 1.0
    assert ex._count_score((lo + hi) // 2) == 1.0
    assert ex._count_score(1) < 0.3, "a couple of plots is too thin to compare"
    assert ex._count_score(300) < 0.2, "hundreds of plots cannot be compared on one screen"


def test_agricultural_band_excludes_residential_plots():
    """Qatari residential plots are a few hundred m2; they must not drive the exploration area."""
    assert ex.MIN_PLOT_M2 >= 5_000
    assert ex.MAX_PLOT_M2 <= 1_000_000


def test_no_plot_is_preselected(area):
    assert "selected" not in area and "preselected" not in area
