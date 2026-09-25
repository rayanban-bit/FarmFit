from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlotSpec(BaseModel):
    id: str
    name: str | None = None
    geometry: dict  # GeoJSON Polygon / MultiPolygon (WGS84)
    source: str | None = None  # e.g. "DEMO - illustrative geometry, not cadastral"


class Constraints(BaseModel):
    budget_qar: float = Field(gt=0)
    water_m3_year: float = Field(gt=0)
    energy_kwh_year: float = Field(gt=0)
    soil_ec_ds_m: float | None = None  # measured ECe; None = unknown -> no salinity penalty, shown as missing
    access_fraction: float = Field(0.08, ge=0, lt=0.5)
    min_land_utilisation: float = Field(0.8, ge=0, le=1)
    monthly_peak_factor: float = Field(2.0, ge=1.0, le=6.0)
    min_block_m2: float = Field(100.0, ge=1)
    max_crop_share: float = Field(1.0, gt=0, le=1)
    objective: Literal["roi", "net_profit"] = "roi"
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
    include_context: bool = False  # OSM market/road context (informational only; fetched lazily via /api/context)
