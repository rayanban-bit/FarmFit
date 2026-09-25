"""NASA POWER daily point API (official REST API, no key required).

Docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
Native resolution: meteorological parameters come from MERRA-2 (0.5 deg lat x 0.625 deg lon) and solar
from CERES SYN1deg (1 deg). We therefore snap the query point to the MERRA-2 cell centre instead of
requesting a fake 'high precision' coordinate; results are cached per cell.
"""
from __future__ import annotations

import httpx
import pandas as pd

from .base import USER_AGENT, cached_fetch

BASE = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M", "T2M_MAX", "T2M_MIN", "ALLSKY_SFC_SW_DWN", "RH2M", "WS2M", "PRECTOTCORR"]
SOURCE_URL = "https://power.larc.nasa.gov/docs/services/api/temporal/daily/"
FILL = -999.0
DEFAULT_START, DEFAULT_END = 2019, 2024


def snap_to_native_cell(lon: float, lat: float) -> tuple[float, float]:
    """Cell centre of the 0.5 x 0.625 degree MERRA-2 grid (lat multiples of 0.5, lon multiples of 0.625)."""
    return round(round(lon / 0.625) * 0.625, 3), round(round(lat / 0.5) * 0.5, 3)


def _fetch(lon: float, lat: float, start: int, end: int) -> dict:
    q = {
        "parameters": ",".join(PARAMS),
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": f"{start}0101",
        "end": f"{end}1231",
        "format": "JSON",
    }
    r = httpx.get(BASE, params=q, timeout=90, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    j = r.json()
    return {"parameters": j["properties"]["parameter"], "units": {k: v.get("units", "") for k, v in j.get("parameters", {}).items()},
            "header": {k: j.get("header", {}).get(k) for k in ("title", "api", "sources", "fill_value", "start", "end")},
            "geometry": j.get("geometry")}


def get_daily(lon: float, lat: float, start: int = DEFAULT_START, end: int = DEFAULT_END, force: bool = False) -> tuple[pd.DataFrame, dict]:
    """Daily weather DataFrame indexed by date (tmean/tmax/tmin degC, rs MJ/m2/d, rh %, ws m/s, rain mm/d) + provenance meta."""
    slon, slat = snap_to_native_cell(lon, lat)
    payload, meta = cached_fetch("nasa_power", {"lon": slon, "lat": slat, "start": start, "end": end},
                                 lambda: _fetch(slon, slat, start, end), ttl_days=None if not force else 0, force=force)
    df = pd.DataFrame(payload["parameters"])
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.replace(FILL, float("nan"))
    units = payload.get("units", {})
    rs = df["ALLSKY_SFC_SW_DWN"]
    if "kW-hr" in units.get("ALLSKY_SFC_SW_DWN", "") or "kWh" in units.get("ALLSKY_SFC_SW_DWN", ""):
        rs = rs * 3.6  # kWh/m2/day -> MJ/m2/day
    out = pd.DataFrame({"tmean": df["T2M"], "tmax": df["T2M_MAX"], "tmin": df["T2M_MIN"], "rs": rs,
                        "rh": df["RH2M"], "ws": df["WS2M"], "rain": df["PRECTOTCORR"]})
    n_missing = int(out.isna().any(axis=1).sum())
    out = out.interpolate(limit=3).dropna()
    meta = {**meta, "requested_lon": lon, "requested_lat": lat, "query_lon": slon, "query_lat": slat, "n_days": len(out),
            "n_days_dropped": n_missing, "units": units, "source_url": SOURCE_URL,
            "note": "Query snapped to the native 0.5 x 0.625 deg MERRA-2 cell centre; solar radiation is 1 deg CERES."}
    return out, meta
