"""Small synthetic problems for solver tests (no network, no catalog)."""
from __future__ import annotations

from app.optimizer import GroupIn, Limits, Option, PlotIn, Problem, TechIn


def flat(x: float) -> list[float]:
    return [x / 12.0] * 12


def make_problem(**limit_kw) -> Problem:
    """Two techniques sharing one infrastructure group; three options; one plot of 10 000 m2 (usable)."""
    opts = [
        # crop, tech, rev, opex, capex, water/yr, energy/yr
        Option("tomato", "open", rev_m2=30.0, opex_m2=12.0, capex_m2=20.0, water_m=flat(1.2), energy_m=flat(2.0), yield_kg_m2=7.5),
        Option("lettuce", "open", rev_m2=20.0, opex_m2=8.0, capex_m2=20.0, water_m=flat(0.6), energy_m=flat(2.0), yield_kg_m2=2.9),
        Option("lettuce", "hydro", rev_m2=90.0, opex_m2=45.0, capex_m2=300.0, water_m=flat(0.2), energy_m=flat(60.0), yield_kg_m2=13.0),
    ]
    techs = {
        "open": TechIn("open", min_area_m2=500, fixed_capex=3000, fixed_opex=0, requires=["water"]),
        "hydro": TechIn("hydro", min_area_m2=500, fixed_capex=10000, fixed_opex=500, requires=["water", "plant"]),
    }
    groups = {"water": GroupIn("water", 15000, 600), "plant": GroupIn("plant", 60000, 3000)}
    lim = Limits(**{"budget": 5e6, "water_year": 1e6, "energy_year": 1e7, "min_block_m2": 100, **limit_kw})
    return Problem([PlotIn("P1", 10_000.0)], opts, techs, groups, lim)
