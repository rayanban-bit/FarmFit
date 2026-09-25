"""Cash-flow finance model. Deterministic, undiscounted (per the challenge brief).

Definitions (H = horizon in years, default 5):
    revenue      R  = sum(yield_kg * price)                         [QAR/year]
    opex         O  = variable + fixed operating cost               [QAR/year]
    profit       P  = R - O                                         [QAR/year]
    capex        C                                                  [QAR, Year 0]
    cash flows   CF0 = -C ; CF1..H = P
    cumulative   S_H = sum CF = H*P - C
    ROI_H        = S_H / C                (net gain over the horizon per QAR invested)
    payback      = C / P years when P > 0, else None (never)  -- NOT the same thing as ROI
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


def cash_flows(capex: float, annual_profit: float, years: int = 5) -> list[float]:
    return [-capex] + [annual_profit] * years


def cumulative(cfs: list[float]) -> list[float]:
    out, s = [], 0.0
    for c in cfs:
        s += c
        out.append(s)
    return out


def net_gain(capex: float, annual_profit: float, years: int = 5) -> float:
    return years * annual_profit - capex


def roi(capex: float, annual_profit: float, years: int = 5) -> float | None:
    if capex <= 0:
        return None
    return net_gain(capex, annual_profit, years) / capex


def payback_years(capex: float, annual_profit: float) -> float | None:
    """Simple payback for constant annual profit; None when the investment never pays back."""
    if capex <= 0:
        return 0.0
    if annual_profit <= 0:
        return None
    return capex / annual_profit


@dataclass
class Summary:
    revenue: float
    opex: float
    profit: float
    capex: float
    water_m3: float
    energy_kwh: float
    horizon_years: int
    roi: float | None
    payback_years: float | None
    net_gain: float
    cash_flows: list[float]
    cumulative_cash_flow: list[float]

    def to_dict(self) -> dict:
        return asdict(self)


def summarise(revenue: float, opex: float, capex: float, water_m3: float, energy_kwh: float, years: int = 5) -> Summary:
    profit = revenue - opex
    cfs = cash_flows(capex, profit, years)
    return Summary(
        revenue=revenue,
        opex=opex,
        profit=profit,
        capex=capex,
        water_m3=water_m3,
        energy_kwh=energy_kwh,
        horizon_years=years,
        roi=roi(capex, profit, years),
        payback_years=payback_years(capex, profit),
        net_gain=net_gain(capex, profit, years),
        cash_flows=cfs,
        cumulative_cash_flow=cumulative(cfs),
    )
