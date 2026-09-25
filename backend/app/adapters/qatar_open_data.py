"""State of Qatar Open Data (Opendatasoft v2.1 API, no key required).

Datasets used
  production-area-and-average-yield-of-crops   fields: year, crop, production (t), area (ha), yield (t/ha)
  cropped-area-and-production-of-crops-in-greenhouses   fields: year, crops, area (ha), production (t)

We never trust a reported value blindly: yield is recomputed as production/area and a record is
rejected (with the reason kept for the UI) when it disagrees with the reported yield by more than 10 %
or is a robust outlier for the crop. If nothing usable remains, the result is None (missing) - never a guess.
"""
from __future__ import annotations

import statistics
from typing import Any

import httpx

from .base import USER_AGENT, cached_fetch
from ..units import t_per_ha_to_kg_per_m2

API = "https://www.data.gov.qa/api/explore/v2.1/catalog/datasets"
DS_OPEN = "production-area-and-average-yield-of-crops"
DS_GH = "cropped-area-and-production-of-crops-in-greenhouses"
PAGE_URL = "https://www.data.gov.qa/explore/dataset/{}/"


def _fetch_all(dataset: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        r = httpx.get(f"{API}/{dataset}/records", params={"limit": 100, "offset": offset}, timeout=60, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        j = r.json()
        rows.extend(j["results"])
        offset += 100
        if offset >= j["total_count"]:
            break
    return rows


def get_dataset(dataset: str, force: bool = False) -> tuple[list[dict], dict]:
    rows, meta = cached_fetch("qatar_od", dataset, lambda: _fetch_all(dataset), ttl_days=30, force=force)
    meta = {**meta, "source_url": PAGE_URL.format(dataset), "dataset": dataset}
    return rows, meta


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def robust_yield(observations: list[dict]) -> dict:
    """observations: [{year, area_ha, production_t, reported_t_ha|None}] -> median yield with an audit trail."""
    accepted, rejected = [], []
    for o in observations:
        a, p = o["area_ha"], o["production_t"]
        if not a or not p or a <= 0 or p <= 0:
            rejected.append({"year": o["year"], "reason": "missing or zero area/production"})
            continue
        y = p / a
        rep = o.get("reported_t_ha")
        if rep is not None and abs(rep - y) / y > 0.10:
            rejected.append({"year": o["year"], "reason": f"reported yield {rep} t/ha disagrees with production/area = {y:.2f} t/ha"})
            continue
        accepted.append({"year": o["year"], "t_ha": y, "area_ha": a, "production_t": p})
    if len(accepted) >= 3:
        med = statistics.median(x["t_ha"] for x in accepted)
        keep = []
        for x in accepted:
            if x["t_ha"] < med / 4 or x["t_ha"] > med * 4:
                rejected.append({"year": x["year"], "reason": f"outlier vs median {med:.1f} t/ha ({x['t_ha']:.2f} t/ha)"})
            else:
                keep.append(x)
        accepted = keep
    if not accepted:
        return {"t_ha": None, "kg_m2": None, "years_used": [], "rejected": rejected, "n": 0}
    ys = [x["t_ha"] for x in accepted]
    med = statistics.median(ys)
    return {"t_ha": med, "kg_m2": t_per_ha_to_kg_per_m2(med), "min_t_ha": min(ys), "max_t_ha": max(ys),
            "years_used": sorted(x["year"] for x in accepted), "rejected": rejected, "n": len(accepted)}


def open_field_yield(names: list[str], force: bool = False) -> tuple[dict, dict]:
    rows, meta = get_dataset(DS_OPEN, force)
    obs = [{"year": r["year"], "area_ha": _num(r.get("area")), "production_t": _num(r.get("production")), "reported_t_ha": _num(r.get("yield"))}
           for r in rows if r.get("crop") in names]
    return robust_yield(obs), meta


def greenhouse_yield(names: list[str], force: bool = False) -> tuple[dict, dict]:
    rows, meta = get_dataset(DS_GH, force)
    obs = [{"year": r["year"], "area_ha": _num(r.get("area")), "production_t": _num(r.get("production")), "reported_t_ha": None}
           for r in rows if r.get("crops") in names]
    return robust_yield(obs), meta
