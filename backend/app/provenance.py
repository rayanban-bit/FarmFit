"""Provenance handling: every number that reaches the UI carries a source record.

A `Param` is a value + unit + source id. Missing data is represented explicitly (value=None,
status='missing') and is never silently replaced by an invented number.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CACHE_DIR = DATA_DIR / "cache"

TYPES = {
    "official_qatar": "Official Qatar data",
    "official_dataset": "Official dataset",
    "scientific_model": "Scientific model",
    "peer_reviewed": "Peer-reviewed research",
    "open_dataset": "Open dataset",
    "vendor_data": "Vendor data",
    "user_supplied": "User supplied",
    "unverified": "Unverified",
}


def today() -> str:
    return date.today().isoformat()


def load_json(name: str) -> dict:
    with open(DATA_DIR / name, "r", encoding="utf-8") as fh:
        return json.load(fh)


_REGISTRY: dict | None = None


def registry() -> dict:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_json("sources.json")["sources"]
    return _REGISTRY


def source(src_id: str) -> dict:
    reg = registry()
    if src_id not in reg:
        raise KeyError(f"Unknown provenance source id '{src_id}' (not in data/sources.json)")
    return reg[src_id]


@dataclass
class Row:
    """One line of the 'Data & assumptions' panel."""

    key: str
    label: str
    value: Any
    unit: str
    source: str
    url: str
    date: str
    type: str  # one of TYPES keys
    status: str  # e.g. live, cached, missing, placeholder, transcribed_verify, user
    note: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type_label"] = TYPES.get(self.type, self.type)
        return d


def row_from_param(key: str, label: str, param: dict, value: Any = None, *, override_user: bool = False) -> Row:
    """Build a panel row from a catalog leaf {value, unit, src}."""
    src_id = "user" if override_user else param["src"]
    s = source(src_id)
    v = param.get("value") if value is None else value
    return Row(
        key=key,
        label=label,
        value=v,
        unit=param.get("unit", ""),
        source=s["name"],
        url=s.get("url", ""),
        date=s.get("retrieved", "n/a"),
        type=s["type"],
        status="missing" if v is None else s.get("status", ""),
        note=s.get("note", ""),
    )


def missing_row(key: str, label: str, unit: str, why: str, src_id: str = "user") -> Row:
    s = source(src_id)
    return Row(key, label, None, unit, s["name"], s.get("url", ""), "n/a", s["type"], "missing", why)


def deep_merge(base: dict, patch: dict) -> dict:
    out = json.loads(json.dumps(base))

    def rec(dst: dict, src: dict) -> None:
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict) and "src" not in v:
                rec(dst[k], v)
            else:
                dst[k] = v

    rec(out, patch)
    return out
