"""State of Qatar Open Data (Opendatasoft v2.1 API, no key required).

Datasets used
  production-area-and-average-yield-of-crops   fields: year, crop, production (t), area (ha), yield (t/ha)
  cropped-area-and-production-of-crops-in-greenhouses   fields: year, crops, area (ha), production (t)

We never trust a reported value blindly: yield is recomputed as production/area and a record is
rejected (with the reason kept for the UI) when it disagrees with the reported yield by more than 10 %
or is a robust outlier for the crop. If nothing usable remains, the result is None (missing) - never a guess.

IMPORTANT - what "production-area-and-average-yield-of-crops" actually measures
------------------------------------------------------------------------------
Despite its use here originally, that dataset is TOTAL national production across every growing system,
not open-field production. Comparing it with the greenhouse dataset makes this unambiguous: for cucumber
in 2021 it reports 184.0 ha / 21,848 t while the greenhouse dataset alone reports 181.8 ha / 21,812 t -
the same cucumbers. Feeding the total to the open-field option gave open-field cucumber a greenhouse
yield (102.6 t/ha) at open-field cost, a phantom option roughly six times better than anything real.

Genuine open-field figures are therefore derived by subtraction, using only official data:

    open-field area       = total area       - greenhouse area
    open-field production = total production - greenhouse production

Sanity-checked per year (see `decomposed_open_field_yield`). Where the remaining open-field area is
negligible the crop is reported as effectively entirely protected in Qatar, which is a finding, not a gap.
Crops absent from the greenhouse dataset cannot be decomposed; their total is used and labelled as such.
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


# A field vegetable yielding under 1 t/ha, or a single crop occupying thousands of hectares in a country
# with ~15,000 ha of cropland in total, indicates the area and production columns were transposed. The
# 2023-2025 rows of the crops dataset do exactly that (tomato 2023: 27,682 ha producing 382 t).
IMPLAUSIBLE_MIN_T_HA = 1.0
IMPLAUSIBLE_MAX_AREA_HA = 3_000.0


def _transposed(area_ha: float, production_t: float) -> str | None:
    if area_ha > IMPLAUSIBLE_MAX_AREA_HA:
        return f"area of {area_ha:,.0f} ha exceeds Qatar's total cropland; columns appear transposed"
    if production_t / area_ha < IMPLAUSIBLE_MIN_T_HA:
        return f"implied yield {production_t / area_ha:.2f} t/ha is not physically plausible for a field crop"
    return None


def robust_yield(observations: list[dict]) -> dict:
    """observations: [{year, area_ha, production_t, reported_t_ha|None}] -> median yield with an audit trail."""
    accepted, rejected = [], []
    for o in observations:
        a, p = o["area_ha"], o["production_t"]
        if not a or not p or a <= 0 or p <= 0:
            rejected.append({"year": o["year"], "reason": "missing or zero area/production"})
            continue
        bad = _transposed(a, p)
        if bad:
            rejected.append({"year": o["year"], "reason": bad})
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


def _by_year(rows: list[dict], crop_field: str, names: list[str]) -> dict[str, tuple[float, float]]:
    """{year: (area_ha, production_t)} for the requested crop names, summed when several names map to one crop."""
    out: dict[str, tuple[float, float]] = {}
    for r in rows:
        if r.get(crop_field) not in names:
            continue
        a, p = _num(r.get("area")), _num(r.get("production"))
        if not a or not p or a <= 0 or p <= 0:
            continue
        year = str(r.get("year"))
        pa, pp = out.get(year, (0.0, 0.0))
        out[year] = (pa + a, pp + p)
    return out


def decomposed_open_field_yield(total_names: list[str], greenhouse_names: list[str], force: bool = False) -> tuple[dict, dict]:
    """Open-field yield as (total - greenhouse), per year, from the two official datasets.

    Returns the usual robust_yield shape plus:
      method                 how the figure was obtained
      effectively_protected  True when almost no open-field area remains for this crop in Qatar
      open_field_share       median share of cropped area that is NOT greenhouse
    """
    tot_rows, meta = get_dataset(DS_OPEN, force)
    if not greenhouse_names:
        # No greenhouse series exists for this crop, so the total cannot be decomposed. The total is used
        # and labelled, rather than silently presented as an open-field measurement.
        obs = [{"year": r["year"], "area_ha": _num(r.get("area")), "production_t": _num(r.get("production")),
                "reported_t_ha": _num(r.get("yield"))} for r in tot_rows if r.get("crop") in total_names]
        res = robust_yield(obs)
        res.update(method="total national production; no greenhouse series exists for this crop, so protected "
                          "cultivation could not be separated out",
                   effectively_protected=False, open_field_share=None, decomposed=False)
        return res, meta

    gh_rows, gh_meta = get_dataset(DS_GH, force)
    tot = _by_year(tot_rows, "crop", total_names)
    gh = _by_year(gh_rows, "crops", greenhouse_names)

    obs: list[dict] = []
    rejected: list[dict] = []
    shares: list[float] = []
    for year in sorted(tot):
        ta, tp = tot[year]
        bad = _transposed(ta, tp)
        if bad:
            rejected.append({"year": year, "reason": f"total record unusable: {bad}"})
            continue
        if year not in gh:
            rejected.append({"year": year, "reason": "no greenhouse record for this year, so the open-field "
                                                     "share cannot be separated from the national total"})
            continue
        ga, gp = gh[year]
        if ga > ta * 1.01 or gp > tp * 1.01:
            rejected.append({"year": year, "reason": f"greenhouse figures ({ga:,.1f} ha / {gp:,.0f} t) exceed the "
                                                     f"national total ({ta:,.1f} ha / {tp:,.0f} t); not reconcilable"})
            continue
        oa, op = ta - ga, tp - gp
        shares.append(oa / ta if ta > 0 else 0.0)
        if oa < 1.0 or op <= 0:
            rejected.append({"year": year, "reason": f"only {oa:,.1f} ha open field remains of {ta:,.1f} ha: this "
                                                     "crop is effectively grown entirely under protection in Qatar"})
            continue
        obs.append({"year": year, "area_ha": oa, "production_t": op, "reported_t_ha": None})

    res = robust_yield(obs)
    res["rejected"] = rejected + res["rejected"]
    share = statistics.median(shares) if shares else None
    res.update(
        method="official national total minus the official greenhouse dataset, per year",
        effectively_protected=bool(shares) and share is not None and share < 0.05,
        open_field_share=share,
        decomposed=True,
    )
    return res, {**meta, "greenhouse_meta": gh_meta}
