"""Web app: a JSON API over the engines plus a static front end (no build step).

The API serves the same read-only tool outputs the agents use, so the screen and the agents
always agree. Nothing here changes a number; engineer decisions arrive with the inbox (Day 10).

Run:  python -m uvicorn app.web.server:app --port 8080     -> http://localhost:8080
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.elv_agent import tools

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="ELV Value Recovery Planner", docs_url="/api/docs", openapi_url="/api/openapi.json")


def _or_404(result: dict) -> dict:
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/month")
def month() -> dict:
    return tools.month_overview()


@app.get("/api/vehicles/{vehicle_id}")
def vehicle(vehicle_id: str) -> dict:
    vid = tools._vid(vehicle_id)
    if not vid:
        raise HTTPException(status_code=404, detail=f"No vehicle {vehicle_id!r}")
    return tools._packs()[vid]


@app.get("/api/review-queue")
def review_queue() -> dict:
    return tools.review_queue()


@app.get("/api/what-if")
def what_if(capacity_minutes: int = Query(..., ge=0, le=100_000)) -> dict:
    return _or_404(tools.plan_what_if(capacity_minutes))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
