"""Catalog loading (crops, techniques, infrastructure, scenarios, defaults) with user-editable overrides.

Overrides are plain numbers; any overridden leaf is relabelled provenance 'user' (User supplied) so the UI
can never present an edited assumption as a sourced value.
"""
from __future__ import annotations

import copy

from .provenance import load_json, source


def base_catalog() -> dict:
    return {
        "crops": load_json("crops.json")["crops"],
        "techniques": load_json("techniques.json")["techniques"],
        "groups": load_json("infrastructure.json")["groups"],
        "scenarios": load_json("scenarios.json")["scenarios"],
        "defaults": {k: v for k, v in load_json("defaults.json").items() if not k.startswith("_")},
    }


def _set(leaf: dict, value: float) -> None:
    leaf["value"] = float(value)
    leaf["src"] = "user"
    leaf.pop("dynamic", None)


def apply_overrides(cat: dict, overrides: dict | None) -> dict:
    """overrides = {crops: {id: {field: number}}, yields: {crop: {tech: number}}, techniques: {...}, infrastructure: {...}, defaults: {...}}"""
    out = copy.deepcopy(cat)
    ov = overrides or {}
    for cid, fields in (ov.get("crops") or {}).items():
        for f, v in fields.items():
            if cid in out["crops"] and isinstance(out["crops"][cid].get(f), dict) and isinstance(v, (int, float)):
                _set(out["crops"][cid][f], v)
    for cid, techs in (ov.get("yields") or {}).items():
        for tid, v in techs.items():
            entry = out["crops"].get(cid, {}).get("yields", {}).get(tid)
            if entry and isinstance(v, (int, float)):
                _set(entry, v)
    for tid, fields in (ov.get("techniques") or {}).items():
        for f, v in fields.items():
            if tid in out["techniques"] and isinstance(out["techniques"][tid].get(f), dict) and isinstance(v, (int, float)):
                _set(out["techniques"][tid][f], v)
    for gid, fields in (ov.get("infrastructure") or {}).items():
        for f, v in fields.items():
            if gid in out["groups"] and isinstance(out["groups"][gid].get(f), dict) and isinstance(v, (int, float)):
                _set(out["groups"][gid][f], v)
    for f, v in (ov.get("defaults") or {}).items():
        if f in out["defaults"] and isinstance(v, (int, float)):
            _set(out["defaults"][f], v)
    return out


def validate(cat: dict) -> list[str]:
    """Structural checks: every numeric leaf has a known provenance source; compatibility lists are consistent."""
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

    walk("crops", cat["crops"])
    walk("techniques", cat["techniques"])
    walk("groups", cat["groups"])
    walk("defaults", cat["defaults"])
    for tid, t in cat["techniques"].items():
        for cid in t["compatible_crops"]:
            if cid not in cat["crops"]:
                problems.append(f"technique {tid} lists unknown crop {cid}")
            elif cat["crops"][cid]["yields"].get(tid) is None:
                problems.append(f"technique {tid} lists crop {cid} but the crop has no yield entry for it")
        for g in t["requires"]:
            if g not in cat["groups"]:
                problems.append(f"technique {tid} requires unknown infrastructure group {g}")
    for cid, c in cat["crops"].items():
        for tid, y in c["yields"].items():
            if y is not None and cid not in cat["techniques"].get(tid, {}).get("compatible_crops", []):
                problems.append(f"crop {cid} has a yield entry for {tid} which does not list it as compatible")
    return problems
