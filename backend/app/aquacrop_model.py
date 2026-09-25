"""FAO AquaCrop integration (aquacrop Python package) for OPEN-FIELD crops with a shipped crop file.

Scope statement (shown in the UI): only open-field tomato is simulated - it is the only MVP crop that has a
calibrated AquaCrop crop file in the package. AquaCrop is NOT used for greenhouse, hydroponic or vertical
systems, nor for cucumber/lettuce/pepper/strawberry (no crop files -> we do not invent parameters).

Workflow: NASA POWER weather + FAO-56 ET0 + SoilGrids texture class -> AquaCrop seasons (planting date from the
thermal window) with soil-moisture-triggered irrigation -> attainable yield + daily irrigation.

Calibration: an uncalibrated AquaCrop crop file describes a well-managed attainable yield, which is several
times the Qatar statistical average. We therefore compute ONE national calibration factor
    k = median Qatar Open Data yield / AquaCrop yield at a fixed reference site (Doha-area POWER cell, sandy loam)
and report it openly. The yield used by the optimizer is k * (AquaCrop yield at the plot's climate cell and soil):
absolute level from official statistics, site/soil/climate response from the process model.
"""
from __future__ import annotations

import statistics
import warnings

import pandas as pd

from .adapters.base import cached_fetch
from .climate import et0_daily

REF_CELL = (51.25, 25.5)  # POWER cell centre used for calibration (lon, lat)
REF_SOIL = "SandyLoam"
FALLBACK_SOIL = "SandyLoam"


def _weather_frame(df: pd.DataFrame, lat: float) -> pd.DataFrame:
    et0 = et0_daily(df, lat)
    return pd.DataFrame({"MinTemp": df["tmin"].to_numpy(), "MaxTemp": df["tmax"].to_numpy(),
                         "Precipitation": df["rain"].to_numpy(), "ReferenceET": et0.to_numpy(), "Date": df.index})


def _simulate(weather: pd.DataFrame, plant_month: int, soil_class: str, first_year: int, last_year: int) -> dict:
    from aquacrop import AquaCropModel, Crop, InitialWaterContent, IrrigationManagement, Soil

    seasons = []
    w_end = weather["Date"].max()
    for yr in range(first_year, last_year + 1):
        plant = pd.Timestamp(year=yr, month=plant_month, day=1)
        start = plant - pd.Timedelta(days=15)
        end = plant + pd.Timedelta(days=230)
        if end > w_end or start < weather["Date"].min():
            continue
        crop = Crop("Tomato", planting_date=plant.strftime("%m/%d"))
        soil = Soil(soil_class)
        irr = IrrigationManagement(irrigation_method=1, SMT=[70, 70, 70, 70])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = AquaCropModel(start.strftime("%Y/%m/%d"), end.strftime("%Y/%m/%d"), weather, soil, crop,
                                  InitialWaterContent(value=["FC"]), irrigation_management=irr)
            model.run_model(till_termination=True)
        res = model.get_simulation_results().iloc[0]
        fl = model._outputs.water_flux.copy()  # daily; IrrDay = irrigation (mm); season_counter -1 = outside the growing season
        fl["date"] = start + pd.to_timedelta(fl["time_step_counter"], unit="D")
        fl = fl[fl["season_counter"] >= 0]
        monthly = [0.0] * 12
        for d, irr_mm in zip(fl["date"], fl["IrrDay"]):
            monthly[d.month - 1] += float(irr_mm)
        seasons.append({"year": yr, "fresh_t_ha": float(res["Fresh yield (tonne/ha)"]), "dry_t_ha": float(res["Dry yield (tonne/ha)"]),
                        "irrigation_mm": float(res["Seasonal irrigation (mm)"]), "monthly_irrigation_mm": monthly})
    if not seasons:
        raise RuntimeError("no complete AquaCrop season fits inside the weather record")
    return {
        "fresh_t_ha": statistics.median(s["fresh_t_ha"] for s in seasons),
        "irrigation_mm": statistics.median(s["irrigation_mm"] for s in seasons),
        "monthly_irrigation_mm": [statistics.mean(s["monthly_irrigation_mm"][m] for s in seasons) for m in range(12)],
        "seasons": [{k: v for k, v in s.items() if k != "monthly_irrigation_mm"} for s in seasons],
        "n_seasons": len(seasons),
    }


def simulate_cached(lon: float, lat: float, df: pd.DataFrame, plant_month: int, soil_class: str) -> tuple[dict, dict]:
    years = sorted(set(df.index.year))
    key = {"lon": lon, "lat": lat, "plant_month": plant_month, "soil": soil_class, "years": [years[0], years[-1]], "v": 2}
    return cached_fetch("aquacrop", key, lambda: _simulate(_weather_frame(df, lat), plant_month, soil_class, years[0], years[-1] - 1), ttl_days=None)


def tomato_open_field(plot_cell: tuple[float, float], plot_df: pd.DataFrame, plant_month: int, soil_class: str | None,
                      stat_yield_t_ha: float | None, ref_df: pd.DataFrame) -> dict:
    """Return the AquaCrop result for a plot plus the calibrated yield. Raises on failure (caller labels the fallback)."""
    soil = soil_class or FALLBACK_SOIL
    plot_sim, plot_meta = simulate_cached(plot_cell[0], plot_cell[1], plot_df, plant_month, soil)
    ref_sim, ref_meta = simulate_cached(REF_CELL[0], REF_CELL[1], ref_df, plant_month, REF_SOIL)
    k = None
    if stat_yield_t_ha and ref_sim["fresh_t_ha"] > 0:
        k = stat_yield_t_ha / ref_sim["fresh_t_ha"]
    return {
        "plot": plot_sim, "reference": ref_sim, "calibration_factor": k,
        "yield_t_ha_calibrated": plot_sim["fresh_t_ha"] * k if k is not None else None,
        "yield_t_ha_uncalibrated": plot_sim["fresh_t_ha"],
        "soil_class_used": soil, "soil_is_fallback": soil_class is None,
        "meta": {"status": plot_meta["status"], "retrieved_at": plot_meta.get("retrieved_at")},
    }
