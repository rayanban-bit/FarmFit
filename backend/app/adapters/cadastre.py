"""State of Qatar approved cadastral plot boundaries - LIVE ArcGIS FeatureServer adapter.

Service (public, no authentication, Query capability only):
    https://services.gisqatar.org.qa/server/rest/services/Vector/CadastrePlots/FeatureServer/0

Verified against the live service on 2026-09-25:
  * layer name  "حدود الأراضي المساحية المعتمدة" (approved cadastral land boundaries), polygon layer
  * 254,289 features; maxRecordCount 2000; pagination supported
  * native spatial reference EPSG:2932 (QND 1995 / Qatar National Grid). We always query with
    inSR=4326 and outSR=4326 so the server reprojects to WGS84 lon/lat for web mapping.
  * f=geojson IS accepted by the /query operation (the service metadata only advertises JSON).
  * PDAREA is the officially registered plot area in m2 and agrees with a geodesic area computed
    from the returned WGS84 ring to about +0.2 % (projection/datum difference). Both are reported;
    the official PDAREA is what the UI treats as authoritative.

Field meanings used here: OBJECTID (stable feature id), PIN (plot identification number),
PDAREA (registered area, m2), PD_NO (planning-decision number), GFCODE, REF_NUMBER, COMMENTS.

The service metadata is read at runtime, so if the layer changes its fields this adapter adapts
instead of relying on hard-coded assumptions. Nothing here invents a parcel id or a boundary.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from .base import USER_AGENT, AdapterUnavailable, cached_fetch
from ..units import geometry_area_m2, geometry_centroid

DEFAULT_LAYER = "https://services.gisqatar.org.qa/server/rest/services/Vector/CadastrePlots/FeatureServer/0"
SOURCE_URL = DEFAULT_LAYER
TIMEOUT = 60.0
MAX_RECORDS = 400


def layer_url() -> str:
    """The cadastral layer URL. Overridable via QATAR_PARCEL_LAYER_URL without touching code."""
    return os.environ.get("QATAR_PARCEL_LAYER_URL", DEFAULT_LAYER).rstrip("/")


def _auth_params() -> dict:
    """The public service needs no token; one is sent only if the operator configured it."""
    tok = os.environ.get("QATAR_GIS_TOKEN")
    return {"token": tok} if tok else {}


def _get(url: str, params: dict | list) -> dict:
    items = list(params.items()) if isinstance(params, dict) else list(params)
    items += list(_auth_params().items())
    r = httpx.get(url, params=items, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError as exc:
        raise AdapterUnavailable(f"cadastre: non-JSON response from {url}") from exc
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise AdapterUnavailable(f"cadastre: ArcGIS error {err.get('code')}: {err.get('message')}")
    return data


def describe() -> tuple[dict, dict]:
    """Read the live layer metadata (fields, geometry type, SR, record limits). Cached for a day."""
    def fetch() -> dict:
        d = _get(layer_url(), {"f": "json"})
        return {
            "name": d.get("name"),
            "type": d.get("type"),
            "geometryType": d.get("geometryType"),
            "maxRecordCount": d.get("maxRecordCount"),
            "capabilities": d.get("capabilities"),
            "native_wkid": ((d.get("extent") or {}).get("spatialReference") or {}).get("latestWkid"),
            "fields": [{"name": f["name"], "type": f["type"], "alias": f.get("alias")} for f in (d.get("fields") or [])],
            "supportsPagination": (d.get("advancedQueryCapabilities") or {}).get("supportsPagination"),
        }

    meta_payload, meta = cached_fetch("cadastre_meta", layer_url(), fetch, ttl_days=1)
    return meta_payload, {**meta, "source_url": layer_url()}


def available_fields() -> set[str]:
    try:
        d, _ = describe()
        return {f["name"] for f in d["fields"]}
    except AdapterUnavailable:
        return set()


PREFERRED_FIELDS = ["OBJECTID", "PIN", "PDAREA", "PD_NO", "GFCODE", "REF_NUMBER", "COMMENTS", "STARTDATE"]


def _out_fields() -> str:
    have = available_fields()
    if not have:
        return "*"
    keep = [f for f in PREFERRED_FIELDS if f in have]
    return ",".join(keep) if keep else "*"


def _normalise(fc: dict, note: str) -> dict:
    """Attach id/name/area to each feature and drop anything without usable polygon geometry."""
    feats = []
    for f in fc.get("features") or []:
        geom = f.get("geometry")
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon") or not geom.get("coordinates"):
            continue
        props = dict(f.get("properties") or {})
        pin = props.get("PIN")
        oid = props.get("OBJECTID") or f.get("id")
        pid = str(pin if pin not in (None, 0) else oid)
        try:
            geodesic = geometry_area_m2(geom)
            lon, lat = geometry_centroid(geom)
        except (ValueError, KeyError, IndexError):
            continue
        registered = props.get("PDAREA")
        props.update({
            "id": pid,
            "name": f"Plot {pid}",
            # The raw ArcGIS attributes (OBJECTID, PIN, ...) are kept untouched, so our normalised keys
            # must not collide with them even case-insensitively: PowerShell and some .NET JSON parsers
            # refuse an object whose keys differ only by case. Hence object_id / plot_pin, not objectid / pin.
            "object_id": oid,
            "plot_pin": pin,
            "area_m2": float(registered) if isinstance(registered, (int, float)) and registered > 0 else geodesic,
            "registered_area_m2": registered,
            "geodesic_area_m2": geodesic,
            "centroid": [lon, lat],
            "data_status": "Live cadastral service",
            "source_note": note,
        })
        lower = [k.lower() for k in props]
        dupes = {k for k in lower if lower.count(k) > 1}
        if dupes:  # guards against a future service field colliding with a normalised key
            raise AdapterUnavailable(f"cadastre: property names collide case-insensitively: {sorted(dupes)}")
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def query_bbox(bbox: tuple[float, float, float, float], min_area_m2: float = 0.0, limit: int = MAX_RECORDS) -> tuple[dict, dict]:
    """Cadastral plots intersecting a WGS84 bbox (minx, miny, maxx, maxy), returned as WGS84 GeoJSON."""
    minx, miny, maxx, maxy = bbox
    if not (-180 <= minx < maxx <= 180 and -90 <= miny < maxy <= 90):
        raise ValueError("bbox must be minx,miny,maxx,maxy in WGS84 with minx<maxx and miny<maxy")
    where = f"PDAREA >= {int(min_area_m2)}" if min_area_m2 and "PDAREA" in available_fields() else "1=1"
    key = {"bbox": [round(v, 5) for v in bbox], "min_area": min_area_m2, "limit": limit, "layer": layer_url()}

    def fetch() -> dict:
        params = [
            ("where", where), ("geometry", f"{minx},{miny},{maxx},{maxy}"),
            ("geometryType", "esriGeometryEnvelope"), ("inSR", "4326"),
            ("spatialRel", "esriSpatialRelIntersects"), ("outFields", _out_fields()),
            ("outSR", "4326"), ("returnGeometry", "true"),
            ("resultRecordCount", str(limit)), ("f", "geojson"),
        ]
        raw = _get(f"{layer_url()}/query", params)
        out = _normalise(raw, "ArcGIS envelope query, outSR=4326")
        out["exceededTransferLimit"] = bool(raw.get("exceededTransferLimit"))
        return out

    fc, meta = cached_fetch("cadastre_bbox", key, fetch, ttl_days=7)
    return fc, {**meta, "source_url": layer_url(), "query": "esriGeometryEnvelope intersects, outSR=4326, f=geojson"}


def query_by_ids(ids: list[str]) -> tuple[dict, dict]:
    """Fetch specific plots by PIN (preferred) or OBJECTID - used to re-read a selection exactly."""
    clean = [str(i).strip() for i in ids if str(i).strip().isdigit()]
    if not clean:
        raise ValueError("no numeric plot ids supplied")
    have = available_fields()
    field = "PIN" if "PIN" in have else "OBJECTID"
    key = {"ids": sorted(clean), "field": field, "layer": layer_url()}

    def fetch() -> dict:
        params = [("where", f"{field} IN ({','.join(clean)})"), ("outFields", _out_fields()),
                  ("outSR", "4326"), ("returnGeometry", "true"),
                  ("resultRecordCount", str(MAX_RECORDS)), ("f", "geojson")]
        return _normalise(_get(f"{layer_url()}/query", params), f"ArcGIS attribute query on {field}")

    fc, meta = cached_fetch("cadastre_ids", key, fetch, ttl_days=7)
    return fc, {**meta, "source_url": layer_url(), "query": f"{field} IN (...)"}


def count(where: str = "1=1") -> int:
    d = _get(f"{layer_url()}/query", {"where": where, "returnCountOnly": "true", "f": "json"})
    return int(d.get("count", 0))


def status() -> dict:
    """Live reachability report for /api/sources/status - never raises."""
    rec: dict = {"endpoint": layer_url(), "requires_credentials": False, "token_configured": bool(os.environ.get("QATAR_GIS_TOKEN"))}
    try:
        meta, _ = describe()
        rec.update(reachable=True, layer_name=meta["name"], geometry_type=meta["geometryType"],
                   native_wkid=meta["native_wkid"], capabilities=meta["capabilities"], fields=len(meta["fields"]))
        try:
            rec["feature_count"] = count()
        except Exception as exc:  # noqa: BLE001
            rec["feature_count_error"] = str(exc)[:120]
    except Exception as exc:  # noqa: BLE001
        rec.update(reachable=False, error=str(exc)[:200])
    return rec
