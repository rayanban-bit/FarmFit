"""FastAPI service: Next.js -> FastAPI -> live data adapters / AquaCrop / OR-Tools -> solution -> Next.js."""
from __future__ import annotations

import json
import queue
import threading
import traceback

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import catalog as catalog_mod, pipeline
from .exploration import exploration_area
from .site import site_summary
from .adapters import cadastre
from .adapters.base import AdapterUnavailable
from .provenance import TYPES, registry
from pydantic import BaseModel

from .schemas import OptimizeRequest, PlotSpec

app = FastAPI(title="FarmFit optimizer service", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/catalog")
def get_catalog() -> dict:
    """Catalog plus the list of required inputs that currently have no value."""
    base = catalog_mod.base_catalog()
    resolved, missing = catalog_mod.resolve(base, None, accept_planning_profile=False)
    return {**base, "sources": registry(), "types": TYPES, "problems": catalog_mod.validate(base),
            "missing_inputs": missing}


@app.get("/api/parcels")
def parcels(
    bbox: str = Query(..., description="minx,miny,maxx,maxy in WGS84 - the current map view"),
    min_area_m2: float = Query(0.0, ge=0, description="ignore plots smaller than this registered area"),
    limit: int = Query(300, ge=1, le=400),
) -> dict:
    """Live cadastral plots from the State of Qatar CadastrePlots FeatureServer, as WGS84 GeoJSON."""
    try:
        box = tuple(float(x) for x in bbox.split(","))
        if len(box) != 4:
            raise ValueError("bbox needs 4 comma-separated numbers")
        fc, meta = cadastre.query_bbox(box, min_area_m2=min_area_m2, limit=limit)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AdapterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Qatar cadastral service unavailable: {exc}") from exc
    return {"mode": "live", "label": "State of Qatar - approved cadastral plot boundaries",
            "source_url": meta["source_url"], "status": meta["status"], "retrieved_at": meta.get("retrieved_at"),
            "truncated": bool(fc.get("exceededTransferLimit")), "count": len(fc["features"]), "featureCollection": fc}


@app.get("/api/parcels/by-id")
def parcels_by_id(ids: str = Query(..., description="comma-separated PIN (or OBJECTID) values")) -> dict:
    try:
        fc, meta = cadastre.query_by_ids(ids.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AdapterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Qatar cadastral service unavailable: {exc}") from exc
    return {"mode": "live", "count": len(fc["features"]), "source_url": meta["source_url"], "featureCollection": fc}


@app.get("/api/parcels/describe")
def parcels_describe() -> dict:
    """Live layer metadata (fields, geometry type, native SR) read from the service itself."""
    try:
        meta, m = cadastre.describe()
        return {**meta, "source_url": m["source_url"], "status": m["status"]}
    except AdapterUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class SiteRequest(BaseModel):
    plots: list[PlotSpec]
    crops: list[str] = []


@app.post("/api/site-summary")
def site(req: SiteRequest) -> dict:
    """What the app works out by itself from the selected plots, with the source and date of each fact."""
    try:
        return site_summary(req.plots, req.crops)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/exploration-area")
def exploration(force: bool = Query(False, description="recompute instead of using the cached choice")) -> dict:
    """Where to open the map: the best agricultural cluster found in the LIVE cadastre, with its reasons."""
    try:
        data, meta = exploration_area(force=force)
        return {**data, "status": meta["status"], "retrieved_at": meta.get("retrieved_at")}
    except AdapterUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Could not identify an exploration area: {exc}") from exc


@app.get("/api/sources/status")
def sources_status() -> dict:
    """Live reachability of every external source, for the audit panel."""
    return {
        "cadastre": cadastre.status(),
        "keyless_public_apis": ["NASA POWER", "Qatar Open Data (Opendatasoft)", "ISRIC SoilGrids WCS", "OpenStreetMap Overpass"],
        "credentials_required": [],
    }


@app.get("/api/context")
def context(lon: float, lat: float) -> dict:
    """OpenStreetMap market / road context for a plot centroid. Informational only, not an optimizer input."""
    from .adapters import osm
    try:
        data, meta = osm.nearest_access(lon, lat)
        return {"available": True, "data": data, "meta": {k: meta.get(k) for k in ("status", "retrieved_at", "source_url")},
                "attribution": "(c) OpenStreetMap contributors, ODbL"}
    except AdapterUnavailable as exc:
        return {"available": False, "error": str(exc)[:200]}


def _run(req: OptimizeRequest, emit):
    ctx = pipeline.prepare_context(req, emit)
    return pipeline.solve_scenario(ctx, req.scenario, emit)


@app.post("/api/optimize")
def optimize(req: OptimizeRequest) -> dict:
    try:
        return _run(req, lambda _e: None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/optimize/stream")
def optimize_stream(req: OptimizeRequest) -> StreamingResponse:
    """NDJSON stream: {event: stage|iteration|result|error}. Iteration events are the real Dinkelbach MIP solves."""
    q: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            q.put({"event": "result", "data": _run(req, q.put)})
        except Exception as exc:  # noqa: BLE001
            q.put({"event": "error", "message": str(exc), "trace": traceback.format_exc()[-800:]})
        finally:
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            item = q.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/scenarios/compare")
def compare(req: OptimizeRequest) -> dict:
    """Re-run the SAME optimizer for every scenario on the same prepared data."""
    try:
        ctx = pipeline.prepare_context(req)
        return {"scenarios": {sid: pipeline.solve_scenario(ctx, sid, with_context=False) for sid in ctx.cat["scenarios"]}}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
