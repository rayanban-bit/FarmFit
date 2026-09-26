from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlotSpec(BaseModel):
    id: str
    name: str | None = None
    geometry: dict  # GeoJSON Polygon / MultiPolygon (WGS84)
    source: str | None = None  # e.g. "Live cadastral service"
    registered_area_m2: float | None = None  # official PDAREA from the cadastre, when available


class Constraints(BaseModel):
    budget_qar: float = Field(gt=0)
    water_m3_year: float = Field(gt=0)
    energy_kwh_year: float = Field(gt=0)
    soil_ec_ds_m: float | None = None  # measured ECe; None = unknown -> no salinity penalty, shown as missing
    access_fraction: float = Field(0.08, ge=0, lt=0.5)
    min_land_utilisation: float = Field(0.95, ge=0, le=1)
    # Portfolio-composition rules. They restrict the feasible set only; the solver still chooses every area,
    # and any rule that cannot be met is relaxed in a stated order and reported.
    min_distinct_combos: int = Field(3, ge=0, le=12)
    min_combo_area_share: float = Field(0.05, ge=0, le=0.5)
    min_distinct_techniques: int = Field(2, ge=0, le=4)
    min_distinct_crops: int = Field(3, ge=0, le=8)
    min_crop_area_share: float = Field(0.05, ge=0, le=0.5)
    # Optional delivery-rate limits: the most that can be drawn in one month. Leave them unset when only
    # the annual volume constrains you - that is what an annual quota means, and inventing a monthly cap
    # from it silently discards the rest of the allowance.
    water_peak_m3_month: float | None = Field(None, gt=0)
    energy_peak_kwh_month: float | None = Field(None, gt=0)
    min_block_m2: float = Field(100.0, ge=1)
    max_crop_share: float = Field(1.0, gt=0, le=1)
    objective: Literal["roi", "net_profit"] = "roi"
    # "portfolio" keeps the composition rules below; "economic" drops them and optimises the objective alone.
    # Both are the same model and the same solver - only the feasible set differs.
    mode: Literal["portfolio", "economic"] = "portfolio"
    horizon_years: int = Field(5, ge=1, le=30)


class OptimizeRequest(BaseModel):
    plots: list[PlotSpec] = Field(min_length=1)
    crops: list[str] = Field(min_length=1)
    techniques: list[str] = Field(min_length=1)
    constraints: Constraints
    prices: dict[str, float] = {}  # crop id -> QAR/kg (user supplied)
    electricity_qar_kwh: float | None = None
    water_qar_m3: float | None = None
    scenario: str = "normal"
    overrides: dict[str, Any] = {}
    # When true the user has explicitly accepted the UNVERIFIED planning profile for required inputs
    # that still have no value. Every value it fills is labelled "Unverified - accepted by user".
    accept_planning_profile: bool = False
    include_context: bool = False  # OSM market/road context (informational only; fetched lazily via /api/context)
