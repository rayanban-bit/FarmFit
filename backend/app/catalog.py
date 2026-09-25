"""Catalog loading, user overrides, and REQUIRED-INPUT resolution.

Core rule of this prototype: a parameter with no defensible source is never silently invented.
Such a leaf carries `required_input: true` and `value: null`. It can only become a number in two ways:

  1. the user types it            -> provenance becomes `user`        (User supplied)
  2. the user explicitly ticks    -> provenance becomes `planning_profile`
     "use unverified planning        (Unverified - accepted by user), and only for leaves that
      defaults"                      actually carry a `profile_value`

Anything still unresolved stays `None`, and `missing_for(crop, technique)` reports it, so the pipeline
can exclude that crop x technique with a precise reason instead of guessing.
"""
from __future__ import annotations

import copy

from .provenance import load_json, source

# Which leaves a given crop x technique actually needs before it can be priced and solved.
CROP_REQUIRED = ["price_qar_kg", "seedlings_qar_m2_cycle", "nutrients_qar_m2_cycle", "cycle_days"]
TECH_REQUIRED = ["capex_qar_m2", "fixed_capex_qar", "water_coefficient", "irrigation_efficiency",
                 "extra_water_m3_m2_year", "energy_kwh_m2_year", "cooling_delta_c", "heating_delta_c"]
TECH_OPEX_COMPONENTS = ["labour_qar_m2_year", "maintenance_qar_m2_year"]
GROUP_REQUIRED = ["fixed_capex_qar", "fixed_opex_qar_year"]
TARIFF_REQUIRED = ["electricity_qar_kwh", "water_qar_m3"]

# Inputs a grower genuinely decides or knows are "essential" and are asked for directly. Everything else is
# an engineering or accounting assumption: it lives under "Advanced assumptions", pre-filled with a clearly
# labelled estimate where one exists, and is never presented as a sourced figure.
ESSENTIAL: set[tuple[str, str]] = {("crops", "price_qar_kg")}


def tier_of(kind: str, field: str) -> str:
    return "essential" if (kind, field) in ESSENTIAL else "advanced"


def base_catalog() -> dict:
    return {
        "crops": load_json("crops.json")["crops"],
        "techniques": load_json("techniques.json")["techniques"],
        "groups": load_json("infrastructure.json")["groups"],
        "scenarios": load_json("scenarios.json")["scenarios"],
        "defaults": {k: v for k, v in load_json("defaults.json").items() if not k.startswith("_")},
    }


def is_required(leaf: object) -> bool:
    return isinstance(leaf, dict) and bool(leaf.get("required_input"))


def _set_user(leaf: dict, value: float) -> None:
    leaf["value"] = float(value)
    leaf["src"] = "user"
    leaf["resolved_by"] = "user"


def _set_profile(leaf: dict) -> None:
    leaf["value"] = float(leaf["profile_value"])
    leaf["src"] = "planning_profile"
    leaf["resolved_by"] = "planning_profile"


def _leaves(cat: dict):
    """Yield (owner_kind, owner_id, field_path, leaf) for every required-input leaf in the catalog."""
    for cid, c in cat["crops"].items():
        for f in CROP_REQUIRED:
            if is_required(c.get(f)):
                yield "crops", cid, f, c[f]
        for tid, y in (c.get("yields") or {}).items():
            if is_required(y):
                yield "yields", cid, tid, y
    for tid, t in cat["techniques"].items():
        for f in TECH_REQUIRED:
            if is_required(t.get(f)):
                yield "techniques", tid, f, t[f]
        for f in TECH_OPEX_COMPONENTS:
            leaf = (t.get("opex_components") or {}).get(f)
            if is_required(leaf):
                yield "techniques", tid, f"opex_components.{f}", leaf
    for gid, g in cat["groups"].items():
        for f in GROUP_REQUIRED:
            if is_required(g.get(f)):
                yield "infrastructure", gid, f, g[f]
    for f in TARIFF_REQUIRED:
        if is_required(cat["defaults"].get(f)):
            yield "defaults", "defaults", f, cat["defaults"][f]


def resolve(cat: dict, overrides: dict | None, accept_planning_profile: bool = False) -> tuple[dict, list[dict]]:
    """Apply user overrides then (optionally) the unverified planning profile.

    Returns (resolved catalog, list of still-missing required inputs). Overrides always win over the
    profile, and a value the user types is always labelled `user`, never `planning_profile`.
    """
    out = copy.deepcopy(cat)
    ov = overrides or {}
    for kind, owner, field, leaf in _leaves(out):
        supplied = (ov.get(kind) or {}).get(owner, {}).get(field)
        if isinstance(supplied, (int, float)):
            _set_user(leaf, supplied)
        elif accept_planning_profile and leaf.get("profile_value") is not None:
            _set_profile(leaf)

    # Non-required leaves may also be edited by the user (they then become User supplied).
    for kind, store in (("crops", out["crops"]), ("techniques", out["techniques"]), ("infrastructure", out["groups"])):
        for oid, fields in (ov.get(kind) or {}).items():
            node = store.get(oid)
            if not node:
                continue
            for f, v in fields.items():
                if not isinstance(v, (int, float)):
                    continue
                target = node
                if f.startswith("opex_components."):
                    target = node.get("opex_components") or {}
                    f = f.split(".", 1)[1]
                if isinstance(target.get(f), dict) and target[f].get("value") != v:
                    _set_user(target[f], v)
    for f, v in (ov.get("defaults") or {}).items():
        if isinstance(v, (int, float)) and isinstance(out["defaults"].get(f), dict):
            _set_user(out["defaults"][f], v)
    for cid, ys in (ov.get("yields") or {}).items():
        for tid, v in ys.items():
            leaf = (out["crops"].get(cid, {}).get("yields") or {}).get(tid)
            if isinstance(leaf, dict) and isinstance(v, (int, float)):
                _set_user(leaf, v)
                leaf.pop("dynamic", None)

    missing = [
        {"kind": kind, "owner": owner, "field": field, "label": leaf.get("label", field), "unit": leaf.get("unit", ""),
         "has_profile_value": leaf.get("profile_value") is not None, "profile_value": leaf.get("profile_value"),
         "tier": tier_of(kind, field), "note": leaf.get("profile_note", "")}
        for kind, owner, field, leaf in _leaves(out)
        if leaf.get("value") is None
    ]
    return out, missing


def inventory(cat: dict) -> list[dict]:
    """Every required input with its current state, for the Advanced panel.

    state is "user" (typed), "estimate" (filled from the planning profile), or "unavailable" (no value and
    no estimate - a real quotation or measurement is needed, and anything depending on it stays excluded).
    """
    out: list[dict] = []
    for kind, owner, field, leaf in _leaves(cat):
        resolved = leaf.get("resolved_by")
        state = "user" if resolved == "user" else "estimate" if resolved == "planning_profile" else (
            "estimate_available" if leaf.get("profile_value") is not None else "unavailable")
        out.append({
            "kind": kind, "owner": owner, "field": field, "label": leaf.get("label", field),
            "unit": leaf.get("unit", ""), "value": leaf.get("value"), "profile_value": leaf.get("profile_value"),
            "state": state, "tier": tier_of(kind, field), "note": leaf.get("profile_note", ""),
        })
    return out


def missing_for(cat: dict, crop_id: str, tech_id: str) -> list[dict]:
    """Every required input that this crop x technique still needs. Empty = the scenario is supported."""
    out: list[dict] = []

    def add(leaf, what: str) -> None:
        if isinstance(leaf, dict) and leaf.get("value") is None:
            out.append({"label": leaf.get("label") or what, "unit": leaf.get("unit", ""), "what": what})

    crop = cat["crops"].get(crop_id)
    tech = cat["techniques"].get(tech_id)
    if crop is None or tech is None:
        return [{"label": f"unknown crop or technique ({crop_id} x {tech_id})", "unit": "", "what": "catalog"}]
    for f in CROP_REQUIRED:
        add(crop.get(f), f"{crop_id}.{f}")
    y = (crop.get("yields") or {}).get(tech_id)
    if y is not None and not y.get("dynamic"):
        add(y, f"{crop_id}.yield.{tech_id}")
    for f in TECH_REQUIRED:
        add(tech.get(f), f"{tech_id}.{f}")
    for f in TECH_OPEX_COMPONENTS:
        add((tech.get("opex_components") or {}).get(f), f"{tech_id}.{f}")
    for g in tech.get("requires", []):
        grp = cat["groups"].get(g, {})
        for f in GROUP_REQUIRED:
            add(grp.get(f), f"infrastructure.{g}.{f}")
    for f in TARIFF_REQUIRED:
        add(cat["defaults"].get(f), f"tariff.{f}")
    return out


# Domain of every value that reaches the physical/financial model. A value outside its domain is rejected
# with a precise message rather than propagated into a division or a nonsensical cost.
def validate_values(cat: dict) -> list[str]:
    """Check resolved numbers are physically and financially meaningful. Returns a list of problems."""
    out: list[str] = []

    def check(node: dict | None, field: str, what: str, *, lo: float = 0.0, hi: float | None = None, strict_lo: bool = False) -> None:
        leaf = (node or {}).get(field)
        if not isinstance(leaf, dict):
            return
        v = leaf.get("value")
        if v is None:
            return  # unresolved required inputs are handled by missing_for(), not here
        label = leaf.get("label") or f"{what} {field}"
        if strict_lo and not v > lo:
            out.append(f"{label}: must be greater than {lo:g} (got {v:g})")
        elif not strict_lo and v < lo:
            out.append(f"{label}: must be at least {lo:g} (got {v:g})")
        elif hi is not None and v > hi:
            out.append(f"{label}: must be at most {hi:g} (got {v:g})")

    for cid, c in cat["crops"].items():
        check(c, "price_qar_kg", cid)
        check(c, "seedlings_qar_m2_cycle", cid)
        check(c, "nutrients_qar_m2_cycle", cid)
        check(c, "cycle_days", cid, strict_lo=True)
        check(c, "turnaround_days", cid)
        for tid, y in (c.get("yields") or {}).items():
            if isinstance(y, dict) and y.get("value") is not None and y["value"] < 0:
                out.append(f"{y.get('label') or f'{cid} yield ({tid})'}: must be at least 0 (got {y['value']:g})")
    for tid, t in cat["techniques"].items():
        # A zero irrigation efficiency would demand infinite water; a value above 1 would create water.
        check(t, "irrigation_efficiency", tid, strict_lo=True, hi=1.0)
        check(t, "capex_qar_m2", tid)
        check(t, "fixed_capex_qar", tid)
        check(t, "water_coefficient", tid)
        check(t, "extra_water_m3_m2_year", tid)
        check(t, "energy_kwh_m2_year", tid)
        check(t, "min_area_m2", tid)
        check(t, "cooling_share", tid, hi=1.0)
        for f in TECH_OPEX_COMPONENTS:
            check(t.get("opex_components"), f, tid)
    for gid, g in cat["groups"].items():
        check(g, "fixed_capex_qar", gid)
        check(g, "fixed_opex_qar_year", gid)
    d = cat["defaults"]
    check(d, "electricity_qar_kwh", "tariff")
    check(d, "water_qar_m3", "tariff")
    check(d, "effective_rain_fraction", "planning", hi=1.0)
    check(d, "access_fraction", "planning", hi=0.9)
    check(d, "horizon_years", "planning", strict_lo=True)
    return out


def validate(cat: dict) -> list[str]:
    """Structural checks: every provenance id resolves, and compatibility lists agree with the yield table."""
    problems: list[str] = []

    def walk(name: str, node) -> None:
        if isinstance(node, dict):
            if "value" in node and "src" in node:
                try:
                    source(node["src"])
                except KeyError:
                    problems.append(f"{name}: unknown source '{node['src']}'")
                return
            for k, v in node.items():
                walk(f"{name}.{k}", v)

    for key in ("crops", "techniques", "groups", "defaults"):
        walk(key, cat[key])
    for tid, t in cat["techniques"].items():
        for cid in t["compatible_crops"]:
            if cid not in cat["crops"]:
                problems.append(f"technique {tid} lists unknown crop {cid}")
            elif cat["crops"][cid]["yields"].get(tid) is None:
                problems.append(f"technique {tid} lists crop {cid} but that crop has no yield entry for it")
        for g in t["requires"]:
            if g not in cat["groups"]:
                problems.append(f"technique {tid} requires unknown infrastructure group {g}")
    for cid, c in cat["crops"].items():
        for tid, y in c["yields"].items():
            if y is not None and cid not in cat["techniques"].get(tid, {}).get("compatible_crops", []):
                problems.append(f"crop {cid} has a yield entry for {tid} which does not list it as compatible")
    return problems


# Backwards-compatible helper used by older callers/tests.
def apply_overrides(cat: dict, overrides: dict | None) -> dict:
    return resolve(cat, overrides, accept_planning_profile=False)[0]
