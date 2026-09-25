"""Choose the map's opening viewport from live cadastral data, not from a hardcoded coordinate.

The only hardcoded geography here is a set of SEARCH WINDOWS over Qatar's named farming municipalities -
where to go looking. Everything the user actually sees (the cluster centre, its extent, which plots are in
it) is derived at run time from the State of Qatar CadastrePlots FeatureServer, and the winning cluster is
picked by measurable criteria rather than chosen by hand.

Method
  1. For each search window, page through the cadastre with returnCentroid=true, keeping plots whose
     registered area falls in an agricultural band. This costs no polygon geometry.
  2. Bin the centroids onto a ~1.3 km grid and form a candidate cluster around every populated cell
     (all plots within CLUSTER_RADIUS_M of the cell centre), then suppress overlapping candidates.
  3. Score each candidate on plot count, size diversity, compactness and market-distance spread, all
     computed from the cadastral data itself.
  4. Enrich only the finalists with OpenStreetMap context (major roads, markets, farmland land use),
     because Overpass is rate-limited and unreliable. If it is unavailable the cluster is still scored on
     the cadastral criteria alone and the result records which signals were used.
  5. Return the winner's bounding box, its metrics and the reasons it won.

Nothing is invented: if no window yields a qualifying cluster the caller is told so and the map falls back
to the full extent of whichever window held the most agricultural plots.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import httpx

from .adapters.base import USER_AGENT, AdapterUnavailable, cached_fetch
from .adapters.cadastre import layer_url
from .units import haversine_m

# Named farming municipalities of Qatar, as search windows (minlon, minlat, maxlon, maxlat).
# These say where to look; the live data decides what is actually shown.
SEARCH_WINDOWS: list[tuple[str, tuple[float, float, float, float]]] = [
    ("Al Shahaniya", (51.10, 25.33, 51.32, 25.50)),
    ("Al Khor / Al Dhakhira", (51.36, 25.61, 51.58, 25.78)),
    ("Al Wakrah / Mesaieed", (51.44, 24.98, 51.62, 25.20)),
    ("Umm Salal / Al Kharaitiyat", (51.32, 25.40, 51.50, 25.56)),
    ("Al Shamal / Madinat ash Shamal", (51.10, 25.90, 51.33, 26.12)),
    ("Al Rayyan outskirts", (51.20, 25.20, 51.42, 25.36)),
]

# An agricultural holding in Qatar is far larger than a residential plot (typically 400-1,200 m2) and
# smaller than a desert reserve. This band is a filter on the official PDAREA, not an invented attribute:
# the cadastral layer carries no land-use field.
MIN_PLOT_M2 = 5_000
MAX_PLOT_M2 = 1_000_000

# A cluster you can take in on one screen and actually click through, not the densest patch of land.
CLUSTER_RADIUS_M = 800.0
GRID_DEG_LAT = 0.007            # about 780 m
MIN_PLOTS_IN_CLUSTER = 6
IDEAL_PLOTS = (10, 30)          # comfortable to compare; scored down outside this band
FINALISTS = 8                   # how many candidates get the (slow, flaky) OSM enrichment
PAGE = 2000                     # the service's maxRecordCount

# Scoring weights: a modelling choice, documented here and returned with the result. Size diversity and
# genuine agricultural land use outrank raw plot count, because the goal is a handful of clearly different
# parcels to compare - not the densest block of near-identical ones.
WEIGHTS = {
    "size_diversity": 0.28,
    "farmland_context": 0.22,
    "plot_count": 0.18,
    "compactness": 0.12,
    "road_access": 0.10,
    "market_spread": 0.10,
}


def _count_score(n: float) -> float:
    """1.0 inside the comfortable band, tapering outside. Too few is thin; too many is unreadable."""
    lo, hi = IDEAL_PLOTS
    if lo <= n <= hi:
        return 1.0
    return max(0.0, n / lo) if n < lo else max(0.0, hi / n)


@dataclass
class Plot:
    pin: str
    area_m2: float
    lon: float
    lat: float


@dataclass
class Cluster:
    window: str
    lon: float
    lat: float
    plots: list[Plot]
    raw: dict = field(default_factory=dict)
    norm: dict = field(default_factory=dict)
    score: float = 0.0
    osm: dict = field(default_factory=dict)

    @property
    def areas(self) -> list[float]:
        return [p.area_m2 for p in self.plots]

    def bbox(self, pad_m: float = 250.0) -> tuple[float, float, float, float]:
        lons = [p.lon for p in self.plots]
        lats = [p.lat for p in self.plots]
        dlat = pad_m / 111_320.0
        dlon = pad_m / (111_320.0 * math.cos(math.radians(self.lat)))
        return (min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat)


# ------------------------------------------------------------------------------------------------
# 1. live cadastral centroids
# ------------------------------------------------------------------------------------------------
def _fetch_window(box: tuple[float, float, float, float]) -> list[dict]:
    """Page through plot centroids in a window. returnCentroid avoids downloading polygon rings."""
    out: list[dict] = []
    offset = 0
    while True:
        params = [
            ("where", f"PDAREA >= {MIN_PLOT_M2} AND PDAREA <= {MAX_PLOT_M2}"),
            ("geometry", ",".join(str(v) for v in box)), ("geometryType", "esriGeometryEnvelope"),
            ("inSR", "4326"), ("spatialRel", "esriSpatialRelIntersects"),
            ("outFields", "PIN,PDAREA"), ("outSR", "4326"),
            ("returnGeometry", "false"), ("returnCentroid", "true"),
            ("resultOffset", str(offset)), ("resultRecordCount", str(PAGE)), ("f", "json"),
        ]
        r = httpx.get(f"{layer_url()}/query", params=params, timeout=90, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        j = r.json()
        if "error" in j:
            raise AdapterUnavailable(f"cadastre: {j['error'].get('message')}")
        feats = j.get("features") or []
        for f in feats:
            c = f.get("centroid") or {}
            a = f.get("attributes") or {}
            if c.get("x") is None or not a.get("PDAREA"):
                continue
            out.append({"pin": str(a.get("PIN") or ""), "area_m2": float(a["PDAREA"]), "lon": float(c["x"]), "lat": float(c["y"])})
        if not j.get("exceededTransferLimit") or not feats:
            break
        offset += len(feats)
        if offset > 20_000:  # safety stop
            break
    return out


def window_plots(name: str, box: tuple[float, float, float, float], force: bool = False) -> tuple[list[Plot], dict]:
    payload, meta = cached_fetch("explore_window", {"w": name, "box": box, "band": [MIN_PLOT_M2, MAX_PLOT_M2]},
                                 lambda: _fetch_window(box), ttl_days=30, force=force)
    return [Plot(**p) for p in payload], meta


# ------------------------------------------------------------------------------------------------
# 2. candidate clusters
# ------------------------------------------------------------------------------------------------
def _candidates(name: str, plots: list[Plot]) -> list[Cluster]:
    if not plots:
        return []
    cells: dict[tuple[int, int], list[Plot]] = {}
    for p in plots:
        glon = GRID_DEG_LAT / max(0.2, math.cos(math.radians(p.lat)))
        cells.setdefault((int(p.lat / GRID_DEG_LAT), int(p.lon / glon)), []).append(p)
    out: list[Cluster] = []
    for _, members in cells.items():
        clat = statistics.fmean(p.lat for p in members)
        clon = statistics.fmean(p.lon for p in members)
        near = [p for p in plots if haversine_m(clon, clat, p.lon, p.lat) <= CLUSTER_RADIUS_M]
        if len(near) < MIN_PLOTS_IN_CLUSTER:
            continue
        clat = statistics.fmean(p.lat for p in near)
        clon = statistics.fmean(p.lon for p in near)
        out.append(Cluster(window=name, lon=clon, lat=clat, plots=near))
    return out


def _suppress_overlaps(clusters: list[Cluster]) -> list[Cluster]:
    """Keep the strongest candidate in any CLUSTER_RADIUS_M neighbourhood (deterministic order)."""
    kept: list[Cluster] = []
    for c in sorted(clusters, key=lambda x: (-x.score, x.lat, x.lon)):
        if all(haversine_m(c.lon, c.lat, k.lon, k.lat) > CLUSTER_RADIUS_M for k in kept):
            kept.append(c)
    return kept


# ------------------------------------------------------------------------------------------------
# 3. measurable criteria
# ------------------------------------------------------------------------------------------------
def _raw_metrics(c: Cluster) -> dict:
    areas = sorted(c.areas)
    n = len(areas)
    logs = [math.log10(a) for a in areas]
    p10, p90 = areas[max(0, int(0.10 * (n - 1)))], areas[int(0.90 * (n - 1))]
    dists = [haversine_m(c.lon, c.lat, p.lon, p.lat) for p in c.plots]
    return {
        "plot_count": float(n),
        "count_score": _count_score(n),
        # spread of plot sizes on a log scale: rewards a mix of small and large holdings
        "size_diversity": float(statistics.pstdev(logs)) if n > 1 else 0.0,
        "size_ratio_p90_p10": (p90 / p10) if p10 > 0 else 1.0,
        "median_area_m2": statistics.median(areas),
        "min_area_m2": areas[0],
        "max_area_m2": areas[-1],
        # compactness: tight clusters are easier to compare on one screen
        "mean_dist_m": statistics.fmean(dists),
        "compactness": 1.0 - min(1.0, statistics.fmean(dists) / CLUSTER_RADIUS_M),
        "radius_m": max(dists) if dists else 0.0,
    }


def _osm_context(c: Cluster) -> dict:
    """Roads, markets and farmland around the cluster. Returns availability flags, never invented values."""
    from .adapters import osm
    out: dict = {"available": False}
    try:
        data, _meta = osm.nearest_access(c.lon, c.lat)
        mk = data.get("nearest_market") or {}
        out.update(available=True,
                   nearest_road_m=(data.get("nearest_main_road") or {}).get("distance_m"),
                   nearest_road=(data.get("nearest_main_road") or {}).get("name"),
                   nearest_market_m=mk.get("distance_m"),
                   nearest_market=mk.get("name"),
                   nearest_market_point=[mk["lon"], mk["lat"]] if mk.get("lon") is not None else None,
                   markets_within_radius=data.get("markets_within_radius"))
    except AdapterUnavailable as exc:
        out["error"] = str(exc)[:140]
        return out
    try:
        out["farmland_features"] = _farmland_count(c.lon, c.lat)
    except AdapterUnavailable as exc:
        out["farmland_error"] = str(exc)[:140]
    return out


def _farmland_count(lon: float, lat: float) -> int:
    """How many OSM farmland/greenhouse land-use features sit within 3 km: real agricultural context."""
    q = (f'[out:json][timeout:25];(way["landuse"~"^(farmland|farmyard|orchard|greenhouse_horticulture)$"]'
         f"(around:3000,{lat},{lon}););out ids 200;")

    def fetch() -> int:
        from .adapters.osm import ENDPOINTS
        last: Exception | None = None
        for ep in ENDPOINTS:
            try:
                r = httpx.post(ep, data={"data": q}, timeout=45, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                return len(r.json().get("elements", []))
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise AdapterUnavailable(f"overpass farmland: {last}")

    payload, _ = cached_fetch("explore_farmland", {"lon": round(lon, 3), "lat": round(lat, 3)}, fetch, ttl_days=30)
    return int(payload)


def _market_spread(c: Cluster) -> float:
    """How much the distance to the nearest market varies across the cluster's plots, in metres.

    Needs the market's real coordinates. Without them the spread is unknown and scores 0, rather than being
    substituted with the cluster radius, which measures something else entirely.
    """
    mk = (c.osm or {}).get("nearest_market_point")
    if not mk:
        return 0.0
    d = [haversine_m(mk[0], mk[1], p.lon, p.lat) for p in c.plots]
    return max(d) - min(d)


def _normalise(values: list[float]) -> tuple[list[float], bool]:
    """Min-max normalise, and say whether the criterion actually discriminated.

    When every candidate shares a value the criterion carries no information. Returning 1.0 for all of them
    (as an earlier version did) silently awarded full marks for a signal that was absent - in Qatar the OSM
    farmland count is frequently 0 everywhere, so a 0.22-weight criterion was inflating every score equally.
    Such a criterion is dropped and its weight redistributed over the ones that did discriminate.
    """
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [0.0 for _ in values], False
    return [(v - lo) / (hi - lo) for v in values], True


def score_clusters(clusters: list[Cluster], use_osm: bool = True) -> list[Cluster]:
    for c in clusters:
        c.raw = _raw_metrics(c)
    # cadastral-only pre-score so the OSM budget is spent on real contenders
    pre = {k: _normalise([c.raw[k] for c in clusters])[0] for k in ("size_diversity", "compactness")}
    for i, c in enumerate(clusters):
        c.score = 0.45 * c.raw["count_score"] + 0.35 * pre["size_diversity"][i] + 0.20 * pre["compactness"][i]
    clusters = _suppress_overlaps(clusters)
    finalists = sorted(clusters, key=lambda c: -c.score)[:FINALISTS]

    if use_osm:
        for c in finalists:
            c.osm = _osm_context(c)
            c.raw["road_access"] = 1.0 / (1.0 + (c.osm.get("nearest_road_m") or 1e6) / 1000.0)
            c.raw["farmland_context"] = float(c.osm.get("farmland_features") or 0)
            c.raw["market_spread"] = _market_spread(c)
    for c in finalists:
        c.raw.setdefault("road_access", 0.0)
        c.raw.setdefault("farmland_context", 0.0)
        c.raw.setdefault("market_spread", 0.0)

    keys = list(WEIGHTS)
    norms: dict[str, list[float]] = {}
    informative: dict[str, bool] = {}
    for k in keys:
        if k == "plot_count":
            # keeps its absolute band score: "comfortable to compare" is not a property of whichever other
            # candidates happen to be competing.
            norms[k] = [c.raw["count_score"] for c in finalists]
            informative[k] = True
            continue
        norms[k], informative[k] = _normalise([c.raw.get(k, 0.0) for c in finalists])
    used = [k for k in keys if informative[k]]
    total_w = sum(WEIGHTS[k] for k in used) or 1.0
    for i, c in enumerate(finalists):
        c.norm = {k: norms[k][i] for k in keys}
        c.score = sum(WEIGHTS[k] / total_w * norms[k][i] for k in used)
        c.raw["_criteria_used"] = used
        c.raw["_criteria_uninformative"] = [k for k in keys if not informative[k]]
    return sorted(finalists, key=lambda c: -c.score)


# ------------------------------------------------------------------------------------------------
# 4. the public entry point
# ------------------------------------------------------------------------------------------------
def _describe(c: Cluster) -> list[str]:
    r = c.raw
    reasons = [
        f"{int(r['plot_count'])} agricultural-scale plots within {CLUSTER_RADIUS_M / 1000:.1f} km",
        f"plot sizes from {r['min_area_m2']:,.0f} to {r['max_area_m2']:,.0f} m2 "
        f"({r['size_ratio_p90_p10']:.0f}x between the 10th and 90th percentile)",
    ]
    if c.osm.get("available"):
        if c.osm.get("nearest_road_m") is not None:
            reasons.append(f"nearest main road {c.osm['nearest_road_m'] / 1000:.1f} km "
                           f"({c.osm.get('nearest_road') or 'unnamed'})")
        if c.osm.get("nearest_market_m") is not None:
            reasons.append(f"nearest market {c.osm['nearest_market_m'] / 1000:.1f} km "
                           f"({c.osm.get('nearest_market') or 'unnamed'})")
        if c.osm.get("farmland_features"):
            reasons.append(f"{c.osm['farmland_features']} OpenStreetMap farmland parcels within 3 km")
    else:
        reasons.append("OpenStreetMap context unavailable; ranked on cadastral criteria alone")
    return reasons


def _compute(use_osm: bool) -> dict:
    windows: list[dict] = []
    all_clusters: list[Cluster] = []
    for name, box in SEARCH_WINDOWS:
        try:
            plots, meta = window_plots(name, box)
            cands = _candidates(name, plots)
            windows.append({"window": name, "plots_found": len(plots), "candidate_clusters": len(cands),
                            "status": meta["status"]})
            all_clusters += cands
        except (AdapterUnavailable, httpx.HTTPError) as exc:
            windows.append({"window": name, "plots_found": 0, "candidate_clusters": 0, "error": str(exc)[:140]})
    if not all_clusters:
        raise AdapterUnavailable("no agricultural cluster could be identified from the cadastral service")

    ranked = score_clusters(all_clusters, use_osm=use_osm)
    best = ranked[0]
    return {
        "bbox": list(best.bbox()),
        "centre": [best.lon, best.lat],
        "window": best.window,
        "label": "Suggested exploration area - real Qatar cadastral data",
        "plot_count": int(best.raw["plot_count"]),
        "min_area_m2": best.raw["min_area_m2"],
        "max_area_m2": best.raw["max_area_m2"],
        "median_area_m2": best.raw["median_area_m2"],
        "radius_m": best.raw["radius_m"],
        "score": round(best.score, 4),
        "reasons": _describe(best),
        "criteria": {k: round(best.norm.get(k, 0.0), 3) for k in WEIGHTS},
        "criteria_used": best.raw.get("_criteria_used", list(WEIGHTS)),
        "criteria_uninformative": best.raw.get("_criteria_uninformative", []),
        "weights": WEIGHTS,
        "osm": best.osm,
        "windows_searched": windows,
        "runners_up": [{"window": c.window, "centre": [round(c.lon, 5), round(c.lat, 5)],
                        "plots": int(c.raw["plot_count"]), "score": round(c.score, 4)} for c in ranked[1:]],
        "method": ("Live CadastrePlots query with returnCentroid over Qatar's farming municipalities, grid "
                   "clustering, then ranking on plot count, size diversity, compactness and OpenStreetMap "
                   "road/market/farmland context."),
    }


def exploration_area(force: bool = False, use_osm: bool = True) -> tuple[dict, dict]:
    """Best agricultural cluster to open the map on. Cached: the cadastre changes slowly."""
    return cached_fetch("exploration_area", {"v": 4, "radius": CLUSTER_RADIUS_M, "band": [MIN_PLOT_M2, MAX_PLOT_M2]},
                        lambda: _compute(use_osm), ttl_days=30, force=force)
