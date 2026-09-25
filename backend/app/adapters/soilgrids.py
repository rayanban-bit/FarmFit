"""SoilGrids 2.0 through the ISRIC WCS (the REST API is paused, so it is NOT used).

WCS endpoint: https://maps.isric.org/mapserv?map=/map/{property}.map   coverage id {property}_{depth}_mean
Values are integers in 'mapped units' (pH x10, sand/silt/clay g/kg). SoilGrids does NOT contain soil
salinity; EC is a user input elsewhere in the app.
"""
from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import tifffile

from .base import USER_AGENT, cached_fetch

WCS = "https://maps.isric.org/mapserv"
SOURCE_URL = "https://www.isric.org/explore/soilgrids"
DEPTHS = ["0-5cm", "5-15cm", "15-30cm", "30-60cm", "60-100cm"]
THICK = [5, 10, 15, 30, 40]
PROPS = {"phh2o": 10.0, "sand": 10.0, "silt": 10.0, "clay": 10.0}  # divisor: mapped unit -> pH / percent
HALF = 0.006  # degrees, about 600 m half-width: a few 250 m pixels around the plot centroid


def _get(prop: str, depth: str, lon: float, lat: float) -> float | None:
    params = [("map", f"/map/{prop}.map"), ("SERVICE", "WCS"), ("VERSION", "2.0.1"), ("REQUEST", "GetCoverage"),
              ("COVERAGEID", f"{prop}_{depth}_mean"), ("FORMAT", "image/tiff"),
              ("SUBSETTINGCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"), ("OUTPUTCRS", "http://www.opengis.net/def/crs/EPSG/0/4326"),
              ("SUBSET", f"X({lon - HALF:.5f},{lon + HALF:.5f})"), ("SUBSET", f"Y({lat - HALF:.5f},{lat + HALF:.5f})")]
    r = httpx.get(WCS, params=params, timeout=90, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    arr = tifffile.imread(io.BytesIO(r.content)).astype("float64")
    vals = arr[arr > 0]  # 0 / negative = nodata over water or masked pixels
    return float(np.median(vals)) if vals.size else None


def _fetch(lon: float, lat: float) -> dict:
    jobs = [(p, d) for p in PROPS for d in DEPTHS]
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda pd_: _get(pd_[0], pd_[1], lon, lat), jobs))
    return {f"{p}|{d}": v for (p, d), v in zip(jobs, res)}


def get_soil(lon: float, lat: float, force: bool = False) -> tuple[dict, dict]:
    """Depth-weighted 0-100 cm means. Missing layers are skipped and reported, never filled."""
    rlon, rlat = round(lon, 3), round(lat, 3)
    raw, meta = cached_fetch("soilgrids", {"lon": rlon, "lat": rlat}, lambda: _fetch(rlon, rlat), ttl_days=None, force=force)
    out: dict = {"layers": {}, "missing": []}
    for prop, div in PROPS.items():
        num = den = 0.0
        for d, w in zip(DEPTHS, THICK):
            v = raw.get(f"{prop}|{d}")
            if v is None:
                out["missing"].append(f"{prop} {d}")
                continue
            out["layers"].setdefault(prop, {})[d] = v / div
            num += w * v / div
            den += w
        out[prop] = num / den if den else None
    if out.get("sand") and out.get("clay") is not None:
        s, c = out["sand"], out["clay"]
        silt = out["silt"] if out.get("silt") is not None else max(0.0, 100 - s - c)
        out["texture_class"] = usda_texture(s, silt, c)
    else:
        out["texture_class"] = None
    return out, {**meta, "source_url": SOURCE_URL, "query_lon": rlon, "query_lat": rlat, "half_width_deg": HALF}


def usda_texture(sand: float, silt: float, clay: float) -> str:
    """USDA soil texture class from percentages (sums are renormalised to 100)."""
    tot = sand + silt + clay
    if tot <= 0:
        raise ValueError("empty texture")
    sand, silt, clay = 100 * sand / tot, 100 * silt / tot, 100 * clay / tot
    if silt + 1.5 * clay < 15:
        return "Sand"
    if silt + 1.5 * clay >= 15 and silt + 2 * clay < 30:
        return "LoamySand"
    if (7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "SandyLoam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "Loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "SiltLoam"
    if silt >= 80 and clay < 12:
        return "Silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "SandyClayLoam"
    if 27 <= clay < 40 and sand > 20 and sand <= 45:
        return "ClayLoam"
    if 27 <= clay < 40 and sand <= 20:
        return "SiltClayLoam"
    if clay >= 35 and sand > 45:
        return "SandyClay"
    if clay >= 40 and silt >= 40:
        return "SiltClay"
    if clay >= 40:
        return "Clay"
    return "Loam"
