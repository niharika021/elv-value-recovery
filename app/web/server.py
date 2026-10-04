"""Web app: a JSON API over the engines plus a static front end (no build step).

The API serves the same tool outputs the agents use, so the screen and the agents always agree.
The one write is POST /api/decisions: an engineer's decision, checked by the decision rules and
appended to the log. Nothing else changes a number.

Run:  python -m uvicorn app.web.server:app --port 8080     -> http://localhost:8080
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.elv_agent import tools
from app.engines.audit import record_decision
from app.engines.decisions import Decision, DecisionError

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


@app.get("/api/inbox")
def inbox() -> dict:
    """What is waiting for an engineer: flagged parts, vehicles ready to sign, recent decisions."""
    packs = tools._packs()
    return dict(
        reviews=tools.review_queue()["parts"],
        ready_to_sign=[dict(vehicle_id=k, offer=p["value"]["offer"], compliance=p["compliance"]["status"])
                       for k, p in packs.items() if p["approval"]["status"] == "ready"],
        signed=[dict(vehicle_id=k, **p["approval"]) for k, p in packs.items() if p["approval"]["status"] == "signed"],
        recent=tools.decision_log()["decisions"][-20:][::-1],
    )


@app.get("/api/decisions")
def decisions() -> dict:
    return tools.decision_log()


class DecisionIn(BaseModel):
    engineer: str = Field(..., max_length=80)
    kind: str
    vehicle_id: str
    action: str
    target: str = ""
    reason: str = Field("", max_length=500)


@app.post("/api/decisions", status_code=201)
def decide(body: DecisionIn) -> dict:
    vid = tools._vid(body.vehicle_id) or body.vehicle_id
    d = Decision(engineer=body.engineer.strip(), kind=body.kind, vehicle_id=vid, action=body.action,
                 target=body.target.strip(), reason=body.reason.strip())
    try:
        d = record_decision(tools.STORE, d)
    except DecisionError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return dict(decision=asdict(d), approval=tools._packs()[vid]["approval"])


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
