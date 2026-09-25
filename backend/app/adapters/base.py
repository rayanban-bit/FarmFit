"""Shared adapter plumbing: local JSON cache, retrieval metadata and explicit failure (never invented data)."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..provenance import CACHE_DIR

USER_AGENT = "farmfit-mvp/0.1 (hackathon prototype; contact: see README)"


class AdapterUnavailable(RuntimeError):
    """A live source could not be reached and no cached copy exists. Callers must show this, not fake data."""


def _path(kind: str, key: Any) -> Path:
    digest = hashlib.sha1(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{kind}_{digest}.json"


def cached_fetch(kind: str, key: Any, fetch: Callable[[], Any], ttl_days: float | None = 30.0, force: bool = False) -> tuple[Any, dict]:
    """Return (payload, meta). meta.status is 'live', 'cached' or 'stale_cache' and always has retrieved_at."""
    p = _path(kind, key)
    cached = None
    if p.exists():
        try:
            cached = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None
    if cached and not force:
        age_days = (time.time() - p.stat().st_mtime) / 86400
        if ttl_days is None or age_days <= ttl_days:
            return cached["payload"], {**cached["meta"], "status": "cached"}
    try:
        payload = fetch()
    except Exception as exc:  # noqa: BLE001 - network / parse errors are all "unavailable"
        if cached:
            return cached["payload"], {**cached["meta"], "status": "stale_cache", "error": str(exc)[:200]}
        raise AdapterUnavailable(f"{kind}: {exc}") from exc
    meta = {"retrieved_at": datetime.now(timezone.utc).date().isoformat(), "key": key}
    p.write_text(json.dumps({"meta": meta, "payload": payload}), encoding="utf-8")
    return payload, {**meta, "status": "live"}
