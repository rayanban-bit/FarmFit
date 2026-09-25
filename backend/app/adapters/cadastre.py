"""Parcel source adapter.

Investigation result (2026-09-25): the public Qatar GIS ArcGIS Server at
  https://services.gisqatar.org.qa/server/rest/services
lists Vector/Landmarks (MapServer), geocoders, GP and geometry utilities - NO cadastral parcel layer.
Other candidate hosts probed did not answer or had no REST directory. No authentication is involved:
a public parcel service simply does not exist there. We therefore use a clearly labelled DEMO dataset
and keep a live ArcGIS FeatureServer/MapServer adapter that activates when you provide a real endpoint:

    QATAR_PARCEL_QUERY_URL=https://<host>/arcgis/rest/services/<...>/FeatureServer/0/query   (layer query URL)
    QATAR_GIS_TOKEN=<token>                       (optional; only if the service requires one)
    QATAR_PARCEL_ID_FIELD=PARCEL_ID               (optional; attribute used as plot id)
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base import USER_AGENT, AdapterUnavailable
from ..provenance import DATA_DIR
from ..units import geometry_area_m2

DEMO_FILE = DATA_DIR / "demo_parcels.geojson"
PROBE_HOSTS = ["https://services.gisqatar.org.qa/server/rest/services"]


def demo_parcels() -> dict:
    with open(DEMO_FILE, "r", encoding="utf-8") as fh:
        fc = json.load(fh)
    for f in fc["features"]:
        f["properties"]["area_m2"] = geometry_area_m2(f["geometry"])
        f["properties"]["data_status"] = "DEMO geometry - not cadastral"
    return fc


def live_configured() -> bool:
    return bool(os.environ.get("QATAR_PARCEL_QUERY_URL"))


def live_parcels(bbox: tuple[float, float, float, float]) -> dict:
    """Query a real ArcGIS layer for parcels intersecting bbox (minx, miny, maxx, maxy in WGS84)."""
    url = os.environ["QATAR_PARCEL_QUERY_URL"]
    params: dict[str, Any] = {"where": "1=1", "geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                              "spatialRel": "esriSpatialRelIntersects", "outSR": 4326, "outFields": "*", "f": "geojson", "resultRecordCount": 500}
    if os.environ.get("QATAR_GIS_TOKEN"):
        params["token"] = os.environ["QATAR_GIS_TOKEN"]
    r = httpx.get(url, params=params, timeout=60, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    fc = r.json()
    if "error" in fc:
        raise AdapterUnavailable(f"ArcGIS error: {fc['error']}")
    id_field = os.environ.get("QATAR_PARCEL_ID_FIELD", "PARCEL_ID")
    for i, f in enumerate(fc.get("features", [])):
        pid = f.get("properties", {}).get(id_field) or f.get("id") or i
        f["properties"]["id"] = str(pid)
        f["properties"]["area_m2"] = geometry_area_m2(f["geometry"])
        f["properties"]["data_status"] = "Live cadastral service"
    return fc


def probe() -> list[dict]:
    """Ask the known public Qatar GIS host what it publishes (used by /api/sources/status)."""
    out = []
    for host in PROBE_HOSTS:
        rec: dict = {"host": host, "reachable": False, "parcel_like_services": []}
        try:
            root = httpx.get(host, params={"f": "json"}, timeout=25, headers={"User-Agent": USER_AGENT}).json()
            names = [s["name"] for s in root.get("services", [])]
            for folder in root.get("folders", []):
                j = httpx.get(f"{host}/{folder}", params={"f": "json"}, timeout=25, headers={"User-Agent": USER_AGENT}).json()
                names += [s["name"] for s in j.get("services", [])]
            rec.update(reachable=True, n_services=len(names), parcel_like_services=[n for n in names if any(k in n.lower() for k in ("parcel", "cadast", "plot"))])
        except Exception as exc:  # noqa: BLE001
            rec["error"] = str(exc)[:160]
        out.append(rec)
    return out
