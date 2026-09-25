"""Site summary: what FarmFit determines automatically from the selected cadastral plots.

Shown before the user runs the optimizer so they can see which inputs they do NOT have to supply. Every fact
carries a state — "verified" (retrieved from an authoritative source), "estimate" (a labelled planning figure)
or "unavailable" — together with its source and retrieval date. Nothing is guessed to fill a field: a plot
whose weather or soil could not be retrieved says so, and soil salinity is always reported as unavailable
because no parcel-level EC dataset exists for Qatar.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import catalog as catalog_mod, climate
from .adapters import nasa_power, qatar_open_data as qod, soilgrids
from .adapters.base import AdapterUnavailable
from .pipeline import MIN_OBS, MONTH_NAMES, PlotCtx
from .provenance import source, today
from .schemas import PlotSpec
from .units import geometry_area_m2, geometry_centroid


def _fact(key, label, value, unit, state, src, url, date, note):
    return {"key": key, "label": label, "value": value, "unit": unit, "state": state,
            "source": src, "url": url, "date": date, "note": note}


def _load(pc: PlotCtx) -> None:
    try:
        df, meta = nasa_power.get_daily(pc.lon, pc.lat)
        pc.df, pc.weather_meta, pc.cell = df, meta, (meta["query_lon"], meta["query_lat"])
        pc.clim = climate.monthly_climatology(df, meta["query_lat"])
    except AdapterUnavailable as exc:
        pc.weather_error = str(exc)
    try:
        pc.soil, pc.soil_meta = soilgrids.get_soil(pc.lon, pc.lat)
    except AdapterUnavailable as exc:
        pc.soil_error = str(exc)


def _plot_facts(pc: PlotCtx) -> list[dict]:
    s_cad, s_np, s_sg = source("qatar_cadastre"), source("nasa_power"), source("soilgrids")
    registered = pc.registered_area_m2
    facts = [
        _fact("area", "Plot area", round(pc.area_m2), "m2",
              "verified" if registered else "estimate",
              s_cad["name"] if registered else "Computed from the plot boundary",
              s_cad["url"] if registered else "", today(),
              f"Officially registered area (PDAREA). Geodesic area recomputed from the boundary: "
              f"{pc.geodesic_area_m2:,.0f} m2." if registered else "Spherical area of the supplied polygon."),
        _fact("location", "Plot centroid", f"{pc.lat:.4f}, {pc.lon:.4f}", "lat, lon", "verified",
              s_cad["name"], s_cad["url"], today(), "Used to look up weather and soil for this plot."),
    ]
    if pc.clim is not None:
        wm = pc.weather_meta
        et0 = sum(a * b for a, b in zip(pc.clim["et0_mm_day"], pc.clim["days"]))
        hottest = max(range(12), key=lambda m: pc.clim["tmax"][m])
        facts += [
            _fact("et0", "Reference evapotranspiration (ET0)", round(et0), "mm/year", "verified",
                  "FAO-56 Penman-Monteith computed from NASA POWER", source("fao56")["url"], wm["retrieved_at"],
                  "Drives every irrigation and water-use calculation."),
            _fact("temps", f"Hottest month ({MONTH_NAMES[hottest]}) mean daily maximum",
                  round(pc.clim["tmax"][hottest], 1), "deg C", "verified", s_np["name"], wm["source_url"],
                  wm["retrieved_at"],
                  f"Decides which months each crop can be grown. {wm['n_days']} days of record for this cell."),
            _fact("rain", "Annual rainfall", round(sum(pc.clim["rain_mm_month"])), "mm/year", "verified",
                  s_np["name"], wm["source_url"], wm["retrieved_at"],
                  "Credited against open-field irrigation only."),
        ]
    else:
        facts.append(_fact("climate", "Weather", None, "", "unavailable", s_np["name"], "", "",
                           pc.weather_error or "not retrieved"))
    if pc.soil and pc.soil.get("texture_class"):
        sm = pc.soil_meta
        facts += [
            _fact("texture", "Soil texture", pc.soil["texture_class"], "USDA class", "verified", s_sg["name"],
                  s_sg["url"], sm["retrieved_at"], "Selects the AquaCrop soil file for open-field simulation."),
            _fact("ph", "Soil pH", round(pc.soil["phh2o"], 1) if pc.soil.get("phh2o") is not None else None, "pH",
                  "verified" if pc.soil.get("phh2o") is not None else "unavailable", s_sg["name"], s_sg["url"],
                  sm["retrieved_at"], "0-100 cm depth-weighted mean."),
        ]
    else:
        facts.append(_fact("soil", "Soil properties", None, "", "unavailable", s_sg["name"], "", "",
                           pc.soil_error or "not retrieved"))
    facts.append(_fact("soil_ec", "Soil salinity (ECe)", None, "dS/m", "unavailable",
                       "No parcel-level salinity dataset exists for Qatar", "", "",
                       "SoilGrids publishes no salinity layer. Enter a laboratory measurement to apply a "
                       "salinity yield penalty; leave it blank and none is applied."))
    return facts


def _yield_rows(cat: dict, crops: list[str]) -> list[dict]:
    rows: list[dict] = []
    for cid in crops:
        crop = cat["crops"].get(cid)
        if not crop:
            continue
        for tid, entry in (crop.get("yields") or {}).items():
            if entry is None:
                continue
            base = {"crop": cid, "crop_name": crop["name"], "technique": tid,
                    "technique_name": cat["techniques"][tid]["name"], "unit": "kg/m2/cycle"}
            if entry.get("dynamic"):
                names = crop["qatar_names"].get(entry["dynamic"], [])
                fn = qod.open_field_yield if entry["dynamic"] == "open_field" else qod.greenhouse_yield
                src = source(entry["src"])
                try:
                    res, meta = fn(names)
                except AdapterUnavailable as exc:
                    rows.append({**base, "state": "unavailable", "value": None, "source": src["name"],
                                 "url": src["url"], "date": "", "note": str(exc)[:160]})
                    continue
                ok = res["n"] >= MIN_OBS and res["kg_m2"] is not None
                rows.append({**base, "state": "verified" if ok else "unavailable",
                             "value": round(res["kg_m2"], 2) if ok else None, "source": src["name"],
                             "url": src["url"], "date": meta["retrieved_at"],
                             "note": (f"Median of {res['n']} year(s) {res['years_used'][0]}-{res['years_used'][-1]}."
                                      if ok else
                                      f"Only {res['n']} usable year(s) in the official series; at least {MIN_OBS} are "
                                      "required, so this combination is excluded unless you supply a yield.")})
            else:
                has = entry.get("profile_value") is not None
                rows.append({**base, "state": "estimate" if has else "unavailable",
                             "value": entry.get("profile_value"), "source": "No official Qatar figure for this system",
                             "url": "", "date": "",
                             "note": entry.get("profile_note")
                             or ("Editable estimate - replace it with a figure from your own records or a supplier."
                                 if has else "Enter a yield from your own records or a supplier quotation.")})
    return rows


def site_summary(plots: list, crops: list[str]) -> dict:
    specs = [p if isinstance(p, PlotSpec) else PlotSpec(**p) for p in plots]
    cells: list[PlotCtx] = []
    for p in specs:
        geodesic = geometry_area_m2(p.geometry)
        area = float(p.registered_area_m2) if p.registered_area_m2 else geodesic
        lon, lat = geometry_centroid(p.geometry)
        cells.append(PlotCtx(p.id, p.name or p.id, p.geometry, p.source or "user supplied geometry",
                             area, geodesic, p.registered_area_m2, area, lon, lat))
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(cells)))) as ex:
        list(ex.map(_load, cells))

    cat = catalog_mod.base_catalog()
    return {
        "plots": [{"plot_id": pc.id, "name": pc.name, "area_m2": pc.area_m2,
                   "registered_area_m2": pc.registered_area_m2, "centroid": [pc.lon, pc.lat],
                   "geometry_source": pc.geometry_source, "facts": _plot_facts(pc)} for pc in cells],
        "yields": _yield_rows(cat, crops),
        "total_area_m2": sum(pc.area_m2 for pc in cells),
    }
