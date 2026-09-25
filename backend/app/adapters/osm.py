"""OpenStreetMap / Overpass: nearest markets and main roads (informational context, not an optimizer input).

Data (c) OpenStreetMap contributors, ODbL: https://www.openstreetmap.org/copyright
Requests are cached per ~1 km cell and sent with an identifying User-Agent (Overpass usage policy).
"""
from __future__ import annotations

import httpx

from .base import USER_AGENT, cached_fetch
from ..units import haversine_m

OVERPASS = "https://overpass-api.de/api/interpreter"
SOURCE_URL = "https://www.openstreetmap.org/copyright"
RADIUS_M = 25_000


ENDPOINTS = [OVERPASS, "https://overpass.kumi.systems/api/interpreter"]


def _queries(lon: float, lat: float) -> list[str]:
    return [
        f'[out:json][timeout:25];(node["shop"~"^(supermarket|greengrocer|wholesale)$"](around:{RADIUS_M},{lat},{lon});'
        f'node["amenity"="marketplace"](around:{RADIUS_M},{lat},{lon}););out 60;',
        f'[out:json][timeout:25];way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"](around:8000,{lat},{lon});out center 60;',
    ]


def _post(query: str) -> list[dict]:
    last: Exception | None = None
    for ep in ENDPOINTS:
        try:
            r = httpx.post(ep, data={"data": query}, timeout=45, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last  # type: ignore[misc]


def _fetch(lon: float, lat: float) -> list[dict]:
    out: list[dict] = []
    for q in _queries(lon, lat):
        out += _post(q)
    return out


def nearest_access(lon: float, lat: float, force: bool = False) -> tuple[dict, dict]:
    rlon, rlat = round(lon, 2), round(lat, 2)
    els, meta = cached_fetch("osm", {"lon": rlon, "lat": rlat}, lambda: _fetch(rlon, rlat), ttl_days=30, force=force)
    markets, roads = [], []
    for e in els:
        c = e.get("center") or ({"lon": e.get("lon"), "lat": e.get("lat")} if "lon" in e else None)
        if not c or c.get("lon") is None:
            continue
        d = haversine_m(lon, lat, c["lon"], c["lat"])
        tags = e.get("tags", {})
        rec = {"name": tags.get("name") or tags.get("name:en") or "(unnamed)", "distance_m": d,
               "kind": tags.get("shop") or tags.get("amenity") or tags.get("highway"),
               "lon": c["lon"], "lat": c["lat"]}
        (roads if "highway" in tags else markets).append(rec)
    markets.sort(key=lambda r: r["distance_m"])
    roads.sort(key=lambda r: r["distance_m"])
    return ({"nearest_market": markets[0] if markets else None, "nearest_main_road": roads[0] if roads else None,
             "markets_within_radius": len(markets), "radius_m": RADIUS_M, "distance_type": "straight-line (haversine) from plot centroid, not road distance"},
            {**meta, "source_url": SOURCE_URL})
