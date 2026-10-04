"""Read-only tools for the ELV agents. Every figure comes from an engine; no tool changes anything.

Each tool returns a dict with what the agent needs to explain one thing, and nothing it could
use to approve, override or re-price. Engineer decisions happen outside the agents.
"""
from __future__ import annotations

import pandas as pd

from app.engines.audit import _clean, build_month
from app.engines.compliance import dismantle_blocked
from app.engines.decisions import JsonlStore
from app.engines.grading import DATA
from app.engines.planner import plan_harvest
from app.engines.value import month_table, value_month

VEHICLES = [f"V{i:02d}" for i in range(1, 13)]


STORE = JsonlStore()   # engineer decisions; Firestore on Cloud Run
_cache: dict = {}


def _packs() -> dict[str, dict]:
    """Audit packs with every recorded engineer decision applied; rebuilt when the log changes."""
    v = STORE.version()
    if _cache.get("version") != v:
        _cache.update(version=v, packs=build_month(decisions=STORE.all()))
    return _cache["packs"]


def _vid(vehicle_id: str) -> str | None:
    v = str(vehicle_id).strip().upper()
    if v.startswith("V") and v[1:].isdigit():
        v = f"V{int(v[1:]):02d}"
    return v if v in VEHICLES else None


def _unknown(vehicle_id: str) -> dict:
    return {"error": f"No vehicle {vehicle_id!r}. Vehicles are {VEHICLES[0]} to {VEHICLES[-1]}."}


# ---- coordinator ---------------------------------------------------------------------------

def month_overview() -> dict:
    """Every vehicle this month: owner offer (INR), scrap-only offer, informal scrapper's offer,
    gap to the informal offer before harvesting (scrap-only) and after, compliance status, parts harvested, open items and approval status.
    Includes month totals."""
    rows = [dict(vehicle_id=k, segment=p["vehicle"]["segment"], condition=p["vehicle"]["condition"],
                 offer_inr=p["value"]["offer"], offer_scrap_only_inr=p["value"]["offer_scrap_only"],
                 informal_offer_inr=p["value"]["informal_offer"],
                 gap_scrap_only_inr=p["value"]["informal_offer"] - p["value"]["offer_scrap_only"],
                 gap_inr=p["value"]["gap"],
                 gap_closed_pct=p["value"]["gap_closed_pct"], compliance=p["compliance"]["status"],
                 parts_harvested=len(p["plan"]["harvest"]), open_items=len(p["open_items"]),
                 approval=p["approval"]["status"]) for k, p in _packs().items()]
    t = pd.DataFrame(rows)
    before = (t.informal_offer_inr - t.offer_scrap_only_inr).mean()
    return _clean(dict(vehicles=rows, month=dict(
        average_gap_scrap_only_inr=round(before), average_gap_inr=round(t.gap_inr.mean()),
        gap_closed_pct=round(100 * (1 - t.gap_inr.mean() / before)),
        steel_to_recycler_kg=round(sum(p["value"]["steel_to_recycler_kg"] for p in _packs().values())),
        co2_avoided_kg=round(sum(p["value"]["co2_avoided_kg"] for p in _packs().values())),
        blocked_before_dismantling=sorted(dismantle_blocked()))))


def vehicle_value(vehicle_id: str) -> dict:
    """One vehicle's offer and how it is built (metal, battery and converter, EPR certificate,
    harvest gain, processing cost, margin), each component's harvest decision with its reason,
    parts left on the vehicle and why, steel to the recycler and CO2 avoided."""
    vid = _vid(vehicle_id)
    if not vid:
        return _unknown(vehicle_id)
    p = _packs()[vid]
    comps = [{k: c.get(k) for k in ("component", "grade", "sale_value", "labour", "scrap_lost", "net",
                                      "status", "why", "harvested", "teardown", "reusable_high_demand")}
             for c in p["components"]]
    return _clean(dict(vehicle_id=vid, vehicle=p["vehicle"], value=p["value"], plan=p["plan"], components=comps))


def plan_what_if(capacity_minutes: int) -> dict:
    """Re-plan the month with a limit on technician minutes for harvesting. Returns parts pulled,
    harvest gain, gap closed and the parts left on vehicles because of the limit. Vehicles that
    fail a dismantle-stage compliance rule stay blocked."""
    if capacity_minutes < 0:
        return {"error": "capacity_minutes must be 0 or more"}
    from app.engines.decisions import harvest_instructions
    blocked = dismantle_blocked()
    exclude, require = harvest_instructions(STORE.all())
    plan = plan_harvest(capacity_minutes=capacity_minutes, blocked=blocked, exclude=exclude, require=require)
    t = month_table(value_month(plan.harvests, with_grading=False))
    before = (t.informal - t.offer_scrap_only).mean()
    left = plan.dropped[plan.dropped.why == "labour capacity"]
    return _clean(dict(capacity_minutes=capacity_minutes, minutes_used=plan.minutes,
                       parts_harvested=int(sum(map(len, plan.harvests.values()))),
                       harvest_gain_inr=round(plan.gain), gap_closed_pct=round(100 * (1 - t.gap.mean() / before)),
                       blocked_before_dismantling=sorted(blocked),
                       offers_inr=dict(zip(t.vehicle, t.offer)),
                       left_for_capacity=left[["vehicle_id", "component", "net", "minutes"]].to_dict("records")))


def decision_log(vehicle_id: str = "") -> dict:
    """Engineer decisions recorded in the approval inbox (all vehicles, or one): who decided what,
    when, why, and what the engine said at the time. Decisions are made by engineers, never by agents."""
    vid = _vid(vehicle_id) if vehicle_id else None
    if vehicle_id and not vid:
        return _unknown(vehicle_id)
    ds = [d for d in STORE.all() if vid is None or d.vehicle_id == vid]
    return _clean(dict(count=len(ds), decisions=[dict(at=d.at, engineer=d.engineer, kind=d.kind, vehicle_id=d.vehicle_id,
                                                      target=d.target, action=d.action, reason=d.reason, context=d.context)
                                                 for d in ds]))


# ---- inspection agent ----------------------------------------------------------------------

def vehicle_grading(vehicle_id: str) -> dict:
    """Teardown grading for a vehicle's harvested starter and alternator: each part's measured
    value, drawing limit, drawing number, verdict (reuse / replace / refurbish / scrap), margin
    left, flags, the engine's reason and the inspector's note."""
    vid = _vid(vehicle_id)
    if not vid:
        return _unknown(vehicle_id)
    keep = ("unit_type", "part_no", "measure", "measured_value", "limit", "drawing_no", "verdict", "margin",
            "flags", "needs_review", "reason", "inspector_note")
    g = [{k: r.get(k) for k in keep} for r in _packs()[vid]["grading"]]
    return _clean(dict(vehicle_id=vid, parts=g, note=None if g else "no starter or alternator harvested"))


def review_queue() -> dict:
    """Every part this month waiting for an engineer's decision, with why it was flagged."""
    items = [dict(vehicle_id=k, part_no=g["part_no"], verdict=g["verdict"], flags=g["flags"], reason=g["reason"],
                  inspector_note=g["inspector_note"])
             for k, p in _packs().items() for g in p["grading"] if g["needs_review"]]
    return _clean(dict(count=len(items), parts=items))


def drawing_rule(part_no: str) -> dict:
    """A part's grading rule as Gemini read it from the drawing (with its verbatim quote and
    whether it passed the fixed checks), beside the reference rule the engine grades with today."""
    pn = str(part_no).strip().upper()
    ref = pd.read_csv(DATA / "grading_rules_reference.csv").set_index("part_no")
    if pn not in ref.index:
        return {"error": f"No part {part_no!r}. Parts are STR-01..STR-10 and ALT-01..ALT-10."}
    out = dict(part_no=pn, reference=ref.loc[pn].to_dict())
    f = DATA / "extracted" / "rules_gemini.csv"
    if f.exists():
        g = pd.read_csv(f).set_index("part_no")
        if pn in g.index:
            out["gemini"] = g.loc[pn][["limit_type", "limit_1", "limit_2", "verdict_if_fail", "evidence",
                                       "status", "problems", "source", "approved_by"]].to_dict()
    return _clean(out)


# ---- compliance agent ----------------------------------------------------------------------

def vehicle_compliance(vehicle_id: str) -> dict:
    """Every compliance rule for one vehicle: pass / fail / n/a, severity, the stage a failure
    blocks (dismantle or release), the evidence detail, the check and its source document."""
    vid = _vid(vehicle_id)
    if not vid:
        return _unknown(vehicle_id)
    c = _packs()[vid]["compliance"]
    return _clean(dict(vehicle_id=vid, **c, disclaimer="Demo rule pack summary, not legal advice."))


def compliance_overview() -> dict:
    """Compliance status of every vehicle this month, with the failing rules."""
    return _clean(dict(vehicles=[dict(vehicle_id=k, status=p["compliance"]["status"],
                                      can_dismantle=p["compliance"]["can_dismantle"],
                                      can_release=p["compliance"]["can_release"],
                                      fails=[f"{r['rule_id']} ({r['severity']}, blocks {r['stage']}): {r['detail']}"
                                             for r in p["compliance"]["rules"] if r["status"] == "fail"])
                                 for k, p in _packs().items()]))
