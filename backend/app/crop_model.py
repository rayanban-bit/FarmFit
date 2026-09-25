"""Crop x technique physical model: growing windows, cycle schedule, monthly water and energy.

Everything here is a deterministic function of (climate, crop params, technique params) - no learned scores.

1. Thermal window (which months can the crop be grown?)
   A month is feasible when the monthly-mean daily maximum (minus the technique's cooling effect) does not
   exceed the crop's upper limit and the monthly-mean daily minimum (plus heating effect) is not below the
   crop's lower limit. Fully controlled systems (vertical) are feasible all year.
2. Schedule: the longest run of feasible months (circular) is the operating window; back-to-back cycles of
   (cycle + turnaround) days are placed from its first day, up to the yield entry's max_cycles.
3. Water (m3/m2/month): crop ET (FAO-56 single Kc x ET0) minus effective rain (open field only) divided by
   irrigation efficiency and multiplied by the technique water coefficient, plus evaporative-cooling water.
   For open-field tomato the AquaCrop irrigation series replaces the Kc method (see aquacrop_model.py).
4. Energy (kWh/m2/month): annual figure x operating fraction, shaped by cooling degree-days.
5. Salinity: Maas-Hoffman relative yield  Yr = 1 - s/100 * (ECe - threshold), clipped to [0, 1].
"""
from __future__ import annotations

MONTH_DAYS = [31, 28.25, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def feasible_months(clim: dict, temp: dict, cooling_delta: float, heating_delta: float, controlled: bool) -> list[bool]:
    if controlled:
        return [True] * 12
    out = []
    for m in range(12):
        tmax_eff = clim["tmax"][m] - cooling_delta
        tmin_eff = clim["tmin"][m] + heating_delta
        out.append(tmax_eff <= temp["tmax_mean"] and tmin_eff >= temp["tmin_mean"])
    return out


def longest_run(flags: list[bool]) -> tuple[int, int] | None:
    """(start_month_index, n_months) of the longest circular run of True; None if none."""
    if not any(flags):
        return None
    if all(flags):
        return 0, 12
    best = (0, 0)
    for s in range(12):
        if not flags[s] or flags[(s - 1) % 12]:
            continue  # only start at run beginnings
        n = 0
        while flags[(s + n) % 12] and n < 12:
            n += 1
        if n > best[1]:
            best = (s, n)
    return best


def kc_at(day: int, stage_days: list[float], kc: list[float]) -> float:
    """FAO-56 piecewise Kc curve: constant ini, linear development, constant mid, linear late decline."""
    ini, dev, mid, late = stage_days
    kc_ini, kc_mid, kc_end = kc
    if day < ini:
        return kc_ini
    if day < ini + dev:
        return kc_ini + (kc_mid - kc_ini) * (day - ini) / dev
    if day < ini + dev + mid:
        return kc_mid
    return kc_mid + (kc_end - kc_mid) * min(1.0, (day - ini - dev - mid) / late)


def scale_stages(stage_days: list[float], cycle_days: float) -> list[float]:
    tot = sum(stage_days)
    return [d * cycle_days / tot for d in stage_days]


def build_schedule(clim: dict, temp: dict, cooling_delta: float, heating_delta: float, controlled: bool,
                   cycle_days: float, turnaround_days: float, max_cycles: int) -> dict | None:
    flags = feasible_months(clim, temp, cooling_delta, heating_delta, controlled)
    run = longest_run(flags)
    if run is None:
        return None
    start, n_months = run
    run_months = [(start + i) % 12 for i in range(n_months)]
    run_days = sum(MONTH_DAYS[m] for m in run_months)
    per_cycle = cycle_days + turnaround_days
    cycles = int(min(max_cycles, (run_days + turnaround_days) // per_cycle))
    if cycles < 1:
        return None
    return {"feasible_months": flags, "start_month": start, "run_months": run_months, "run_days": run_days, "cycles": cycles,
            "cycle_days": cycle_days, "turnaround_days": turnaround_days}


def monthly_water_kc(clim: dict, sched: dict, stage_days: list[float], kc: list[float], irrigation_eff: float,
                     water_coeff: float, extra_m3_m2_year: float, use_rain: bool, rain_fraction: float) -> list[float]:
    """m3/m2 per calendar month for the whole operating year (all cycles).

    irrigation_eff is the fraction of applied water that reaches the crop, so it must be > 0: at zero the
    water needed to deliver any net requirement is infinite, which is physically meaningless rather than a
    number to approximate. Callers validate this up front; the check here documents the precondition.
    """
    if not irrigation_eff > 0:
        raise ValueError(f"irrigation efficiency must be greater than 0, got {irrigation_eff}")
    water = [0.0] * 12
    stages = scale_stages(stage_days, sched["cycle_days"])
    month_cursor = 0  # index into run_months
    day_in_month = 0.0
    run_months = sched["run_months"]
    per_cycle = sched["cycle_days"] + sched["turnaround_days"]
    for c in range(sched["cycles"]):
        # advance calendar cursor to the start of cycle c
        t0 = c * per_cycle
        mi, dleft = _locate(run_months, t0)
        for d in range(int(round(sched["cycle_days"]))):
            if dleft <= 0:
                mi += 1
                dleft = MONTH_DAYS[run_months[mi % len(run_months)]]
            m = run_months[mi % len(run_months)]
            et0 = clim["et0_mm_day"][m]
            etc = kc_at(d, stages, kc) * et0
            pe = (clim["rain_mm_month"][m] * rain_fraction / MONTH_DAYS[m]) if use_rain else 0.0
            net = max(0.0, etc - pe)
            water[m] += net / irrigation_eff * water_coeff / 1000.0
            dleft -= 1
    if extra_m3_m2_year > 0:
        tot_days = sched["run_days"]
        for m in run_months:
            water[m] += extra_m3_m2_year * (tot_days / 365.0) * MONTH_DAYS[m] / tot_days
    return water


def _locate(run_months: list[int], offset_days: float) -> tuple[int, float]:
    """Return (index into run_months, days remaining in that month) at a given day offset from the run start."""
    i, remaining = 0, offset_days
    while True:
        md = MONTH_DAYS[run_months[i % len(run_months)]]
        if remaining < md:
            return i, md - remaining
        remaining -= md
        i += 1


def monthly_energy(clim: dict, sched: dict, annual_kwh_m2: float, cooling_share: float) -> list[float]:
    """kWh/m2 per calendar month. Baseload spreads by days; the cooling share follows cooling degree-days (T > 20 C)."""
    run_months = sched["run_months"]
    frac = sched["run_days"] / 365.0
    total = annual_kwh_m2 * frac
    energy = [0.0] * 12
    days = {m: MONTH_DAYS[m] for m in run_months}
    d_tot = sum(days.values())
    cdd = {m: max(0.0, clim["tmean"][m] - 20.0) * days[m] for m in run_months}
    c_tot = sum(cdd.values())
    for m in run_months:
        base = (1 - cooling_share) * days[m] / d_tot
        cool = cooling_share * (cdd[m] / c_tot if c_tot > 0 else days[m] / d_tot)
        energy[m] = total * (base + cool)
    return energy


def salinity_factor(ec_ds_m: float | None, threshold: float, slope_pct: float) -> float:
    """Maas-Hoffman relative yield. None (EC unknown) -> 1.0, and the UI states that no salinity penalty was applied."""
    if ec_ds_m is None or ec_ds_m <= threshold:
        return 1.0
    return max(0.0, min(1.0, 1.0 - slope_pct / 100.0 * (ec_ds_m - threshold)))
