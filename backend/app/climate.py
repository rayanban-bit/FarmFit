"""Climate processing: FAO-56 Penman-Monteith reference ET0 and monthly climatology from NASA POWER data.

ET0 (FAO-56 eq. 6):  ET0 = [0.408 D (Rn - G) + g 900/(T+273) u2 (es - ea)] / [D + g (1 + 0.34 u2)],   G = 0 (daily)
Inputs are NASA POWER daily Tmax/Tmin, RH2M, WS2M (already at 2 m), ALLSKY_SFC_SW_DWN (Rs).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

GSC = 0.0820  # MJ m-2 min-1
SIGMA = 4.903e-9  # MJ K-4 m-2 day-1


def sat_vp(t_c):
    return 0.6108 * np.exp(17.27 * t_c / (t_c + 237.3))


def extraterrestrial_radiation(lat_deg: float, doy) -> np.ndarray:
    """Ra, MJ m-2 day-1 (FAO-56 eq. 21)."""
    phi = math.radians(lat_deg)
    j = np.asarray(doy, dtype=float)
    dr = 1 + 0.033 * np.cos(2 * math.pi * j / 365)
    delta = 0.409 * np.sin(2 * math.pi * j / 365 - 1.39)
    ws = np.arccos(np.clip(-math.tan(phi) * np.tan(delta), -1, 1))
    return (24 * 60 / math.pi) * GSC * dr * (ws * math.sin(phi) * np.sin(delta) + math.cos(phi) * np.cos(delta) * np.sin(ws))


def et0_daily(df: pd.DataFrame, lat_deg: float, elevation_m: float = 20.0) -> pd.Series:
    """FAO-56 PM ET0 (mm/day) for a DataFrame with tmax, tmin, tmean, rs, rh, ws columns.

    Elevation default 20 m is an approximation for Qatar (flat, low-lying); it only enters the psychrometric
    constant and clear-sky radiation weakly.
    """
    tmax, tmin, tmean = df["tmax"].to_numpy(), df["tmin"].to_numpy(), df["tmean"].to_numpy()
    rs, rh, u2 = df["rs"].to_numpy(), df["rh"].to_numpy(), df["ws"].to_numpy()
    doy = df.index.dayofyear.to_numpy()
    p = 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26
    gamma = 0.000665 * p
    es = (sat_vp(tmax) + sat_vp(tmin)) / 2
    ea = rh / 100.0 * es  # eq. 19 variant using mean RH
    delta = 4098 * sat_vp(tmean) / (tmean + 237.3) ** 2
    ra = extraterrestrial_radiation(lat_deg, doy)
    rso = (0.75 + 2e-5 * elevation_m) * ra
    rns = 0.77 * rs
    ratio = np.clip(rs / np.maximum(rso, 1e-6), 0.3, 1.0)
    rnl = SIGMA * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2) * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0))) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    num = 0.408 * delta * rn + gamma * 900 / (tmean + 273) * u2 * (es - ea)
    den = delta + gamma * (1 + 0.34 * u2)
    return pd.Series(np.maximum(num / den, 0.0), index=df.index, name="et0")


def monthly_climatology(df: pd.DataFrame, lat_deg: float) -> dict:
    """Long-term monthly means over the retrieved years (index 0 = January)."""
    d = df.copy()
    d["et0"] = et0_daily(d, lat_deg)
    g = d.groupby(d.index.month)
    years = max(1, d.index.year.nunique())
    rain_month = d["rain"].groupby(d.index.month).sum() / years
    days = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return {
        "tmax": [float(g["tmax"].mean().loc[m]) for m in range(1, 13)],
        "tmin": [float(g["tmin"].mean().loc[m]) for m in range(1, 13)],
        "tmean": [float(g["tmean"].mean().loc[m]) for m in range(1, 13)],
        "et0_mm_day": [float(g["et0"].mean().loc[m]) for m in range(1, 13)],
        "rain_mm_month": [float(rain_month.loc[m]) for m in range(1, 13)],
        "days": days,
        "years": years,
    }
