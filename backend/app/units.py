"""Unit conversions and geodesic area. Pure functions, no I/O."""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean radius; same sphere Turf.js uses (6371008.8)


def ha_to_m2(ha: float) -> float:
    return ha * 10_000.0


def m2_to_ha(m2: float) -> float:
    return m2 / 10_000.0


def t_per_ha_to_kg_per_m2(t_ha: float) -> float:
    """1 t/ha = 1000 kg / 10 000 m2 = 0.1 kg/m2."""
    return t_ha * 0.1


def mm_to_m3_per_m2(mm: float) -> float:
    """1 mm of water over 1 m2 = 1 litre = 0.001 m3."""
    return mm / 1000.0


def mj_to_kwh(mj: float) -> float:
    return mj / 3.6


def kelvin_to_c(k: float) -> float:
    return k - 273.15


def ring_area_m2(ring: list[list[float]]) -> float:
    """Spherical polygon-ring area (m2) from [lon, lat] degrees.

    Uses the Chamberlain-Duquette formula (the one Turf.js uses), so the frontend and the
    backend agree to floating-point precision.
    """
    if len(ring) < 4:
        return 0.0
    total = 0.0
    n = len(ring)
    for i in range(n - 1):
        lon1, lat1 = ring[i][0], ring[i][1]
        lon2, lat2 = ring[i + 1][0], ring[i + 1][1]
        total += math.radians(lon2 - lon1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total * EARTH_RADIUS_M * EARTH_RADIUS_M / 2.0)


def polygon_area_m2(rings: list[list[list[float]]]) -> float:
    """Area of a GeoJSON Polygon coordinate array: outer ring minus holes."""
    if not rings:
        return 0.0
    area = ring_area_m2(rings[0])
    for hole in rings[1:]:
        area -= ring_area_m2(hole)
    return max(area, 0.0)


def geometry_area_m2(geometry: dict) -> float:
    kind = geometry.get("type")
    if kind == "Polygon":
        return polygon_area_m2(geometry["coordinates"])
    if kind == "MultiPolygon":
        return sum(polygon_area_m2(p) for p in geometry["coordinates"])
    raise ValueError(f"Unsupported geometry type: {kind}")


def geometry_centroid(geometry: dict) -> tuple[float, float]:
    """Area-weighted centroid (lon, lat) of the outer ring(s), planar in degrees (fine at plot scale)."""
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    ax = ay = a_tot = 0.0
    for poly in polys:
        ring = poly[0]
        a2 = cx = cy = 0.0
        for i in range(len(ring) - 1):
            x0, y0 = ring[i][0], ring[i][1]
            x1, y1 = ring[i + 1][0], ring[i + 1][1]
            cross = x0 * y1 - x1 * y0
            a2 += cross
            cx += (x0 + x1) * cross
            cy += (y0 + y1) * cross
        if abs(a2) < 1e-18:
            continue
        ax += cx / (3 * a2) * abs(a2)
        ay += cy / (3 * a2) * abs(a2)
        a_tot += abs(a2)
    if a_tot == 0:
        ring = polys[0][0]
        return ring[0][0], ring[0][1]
    return ax / a_tot, ay / a_tot


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
