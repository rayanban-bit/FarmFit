"""FastAPI service: Next.js -> FastAPI -> data adapters / AquaCrop / OR-Tools -> solution -> Next.js."""
from __future__ import annotations

import json
import queue
import threading
import traceback

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import catalog as catalog_mod, pipeline
from .adapters import cadastre
from .provenance import TYPES, load_json, registry
from .schemas import OptimizeRequest

app = FastAPI(title="FarmFit optimizer service", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/catalog")
def get_catalog() -> dict:
    cat = catalog_mod.base_catalog()
    return {**cat, "sources": registry(), "types": TYPES, "problems": catalog_mod.validate(cat)}


@app.get("/api/parcels")
def parcels(bbox: str | None = Query(None, description="minx,miny,maxx,maxy (WGS84); only used for the live adapter")) -> dict:
    """Live ArcGIS parcels when QATAR_PARCEL_QUERY_URL is configured, otherwise the labelled demo GeoJSON."""
    if cadastre.live_configured() and bbox:
        try:
            box = tuple(float(x) for x in bbox.split(","))
            fc = cadastre.live_parcels(box)  # type: ignore[arg-type]
            return {"mode": "live", "label": "Live cadastral service", "featureCollection": fc}
        except Exception as exc:  # noqa: BLE001 - fall through to demo with the reason shown
            fc = cadastre.demo_parcels()
            return {"mode": "demo", "label": "DEMO geometry - live parcel service failed: " + str(exc)[:120], "featureCollection": fc}
    return {"mode": "demo", "label": "DEMO geometry - illustrative plots, not cadastral boundaries", "featureCollection": cadastre.demo_parcels()}


@app.get("/api/sources/status")
def sources_status() -> dict:
    return {"cadastre": {"live_configured": cadastre.live_configured(), "probe": cadastre.probe()},
            "notes": "NASA POWER, Qatar Open Data and SoilGrids WCS and OSM Overpass require no credentials."}


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
    """NDJSON stream: {event: stage|iteration|result|error, ...}. Iteration events are the real Dinkelbach MIP solves."""
    q: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            result = _run(req, q.put)
            q.put({"event": "result", "data": result})
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
        out = {}
        for sid in ctx.cat["scenarios"]:
            out[sid] = pipeline.solve_scenario(ctx, sid, with_context=False)
        return {"scenarios": out}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/context")
def context(lon: float, lat: float) -> dict:
    """OpenStreetMap market / road context for a plot centroid. Informational only (not an optimizer input)."""
    from .adapters import osm
    from .adapters.base import AdapterUnavailable
    try:
        data, meta = osm.nearest_access(lon, lat)
        return {"available": True, "data": data, "meta": {k: meta.get(k) for k in ("status", "retrieved_at", "source_url")},
                "attribution": "(c) OpenStreetMap contributors, ODbL"}
    except AdapterUnavailable as exc:
        return {"available": False, "error": str(exc)[:200]}
