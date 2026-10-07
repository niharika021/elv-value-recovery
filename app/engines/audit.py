"""Audit pack: one JSON record per vehicle, built only from engine outputs.

Order matters: active grading rules (baseline, or Gemini's where an engineer approved it) ->
engineer part reviews -> dismantle-stage compliance -> harvest plan (blocked vehicles untouched,
engineer exclude / require applied) -> value -> full compliance on what was actually harvested,
with C08 judged on the decision log -> open items -> sign-off and next action.
Every number comes from an engine; engineers change outcomes only through recorded decisions
(app/engines/decisions.py); the agents explain the pack, they never edit it.

Run:  python -m app.engines.audit [capacity_minutes]   -> out/audit/V01.json ... + month summary
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd

from app.engines.compliance import check_month, dismantle_blocked, month_summary
from app.engines.decisions import (Decision, DecisionError, DecisionStore, apply_part_reviews,
                                   harvest_instructions, latest, sign_off_for, validate_shape)
from app.engines.grading import DATA, grade_inspections
from app.engines.rule_check import active_rules, check_rule, gemini_rules, snapshot_rule
from app.engines.planner import PlanError, candidates, plan_harvest
from app.engines.value import UNIT_OF, value_month

OUT = Path(__file__).resolve().parents[2] / "out" / "audit"


def _clean(x):
    """JSON-safe: numpy scalars to Python, NaN to None."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if hasattr(x, "item"):
        x = x.item()
    if isinstance(x, float) and x != x:
        return None
    return x


def decided_grades(decisions: list[Decision]) -> pd.DataFrame:
    """Grades under the active rules, with engineer part reviews applied and each part's rule source."""
    rules, source = active_rules(decisions)
    g = apply_part_reviews(grade_inspections(rules=rules), decisions)
    g["rule_source"] = g.part_no.map(source).fillna("no approved rule")
    return g


def build_month(capacity_minutes: int | None = None, decisions: list[Decision] | None = None) -> dict[str, dict]:
    decisions = decisions or []
    grades = decided_grades(decisions)
    blocked = dismantle_blocked(check_month(None, grades))
    exclude, require = harvest_instructions(decisions)
    plan = plan_harvest(capacity_minutes=capacity_minutes, blocked=blocked, exclude=exclude, require=require)
    values = {v.vehicle_id: v for v in value_month(plan.harvests, grades=grades)}
    compliance = check_month(plan.harvests, grades, decisions=decisions)
    veh = pd.read_csv(DATA / "vehicles.csv").set_index("vehicle_id")
    rule_sources = sorted(pd.read_csv(DATA / "compliance_rules.csv").source.unique())

    packs = {}
    for vid, v in values.items():
        c = compliance[vid]
        units = {UNIT_OF[h] for h in v.harvest if h in UNIT_OF}
        g = grades[(grades.vehicle_id == vid) & grades.unit_type.isin(units)]
        review = g[g.needs_review]
        open_items = (
            [f"compliance {r.rule_id} ({r.severity}, blocks {r.stage}): {r.detail}" for r in c.fails]
            + [f"engineer review {p.part_no}: {p.reason}" for p in review.itertuples()]
        )
        packs[vid] = _clean(dict(
            vehicle_id=vid,
            vehicle=veh.loc[vid].to_dict(),
            compliance=dict(status=c.status, can_dismantle=c.can_dismantle, can_release=c.can_release,
                            rules=[r.__dict__ for r in c.results]),
            plan=dict(capacity_minutes=capacity_minutes, harvest=list(v.harvest), minutes=v.harvest_minutes,
                      left_on_vehicle=plan.dropped[plan.dropped.vehicle_id == vid]
                      .drop(columns="vehicle_id").to_dict("records")),
            value=dict(offer=v.offer, offer_scrap_only=v.offer_scrap_only, informal_offer=v.informal_offer,
                       gap=v.gap, gap_closed_pct=round(v.gap_closed_pct, 1), metal_value=v.metal_value,
                       always_removed_value=v.always_removed_value, epr=v.epr, harvest_gain=v.harvest_gain,
                       revenue=v.revenue, processing=v.processing, margin=v.margin,
                       steel_to_recycler_kg=v.steel_to_recycler_kg, co2_avoided_kg=v.co2_avoided_kg),
            components=v.lines.to_dict("records"),
            grading=g.drop(columns=["vehicle_id"]).to_dict("records"),
            open_items=open_items,
            decisions=[asdict(d) for d in decisions if d.vehicle_id == vid],
            approval=_approval(vid, open_items, decisions, set(g.part_no), c),
            sources=dict(
                grading_rules="per part: the baseline reference rule, or Gemini's reading where an engineer "
                              "approved it (see each grading row's rule_source)",
                compliance_rules=rule_sources,
                data=["vehicles.csv", "components.csv", "inspections.csv", "market_prices.csv",
                      "part_market.csv", "compliance_evidence.csv", "carbon_factors.csv"],
                disclaimer="Synthetic hackathon data; the rule pack is a demo summary, not legal advice.",
            ),
        ))
    return packs


def _approval(vid: str, open_items: list[str], decisions: list[Decision], parts: set[str], c) -> dict:
    """Sign-off state and the vehicle's next action. Nothing is released before sign-off."""
    s = sign_off_for(vid, decisions, parts)
    if not c.can_dismantle:
        blocks = ", ".join(r.rule_id for r in c.fails if r.stage == "dismantle")
        nxt = f"Hold: compliance blocks dismantling ({blocks}); close with evidence"
    elif s:
        nxt = "Released: dismantle and dispatch per the approved plan"
    elif open_items:
        nxt = f"Hold: resolve {len(open_items)} open item(s), then sign off"
    else:
        nxt = "Awaiting engineer sign-off"
    if s:
        return dict(status="signed", engineer=s.engineer, signed_at=s.at, next_action=nxt)
    return dict(status="pending" if open_items else "ready", engineer=None, signed_at=None, next_action=nxt)


def decision_outcomes(decisions: list[Decision], packs: dict[str, dict]) -> dict[str, str]:
    """What each decision led to, read back from the engines' current state (decision id -> text)."""
    current = {d.key: d.id for d in latest(decisions).values()}
    _, source = active_rules(decisions)
    out = {}
    for d in decisions:
        if current.get(d.key) != d.id:
            out[d.id] = "superseded by a later decision"
        elif d.kind == "rule_review":
            out[d.id] = f"{d.target} is graded with: {source.get(d.target, 'no approved rule')}"
        elif d.vehicle_id not in packs:
            out[d.id] = "vehicle not in this month"
        elif d.kind == "part_review":
            row = next((g for g in packs[d.vehicle_id]["grading"] if g["part_no"] == d.target), None)
            out[d.id] = (f"{row['status']}; verdict {row['verdict']}; next: {row['next_action']}" if row
                         else "part no longer on a harvested unit")
        elif d.kind == "harvest":
            p = packs[d.vehicle_id]
            where = "harvested" if d.target in p["plan"]["harvest"] else "left on the vehicle"
            out[d.id] = f"{d.target} {where}; offer now INR {p['value']['offer']:,}"
        else:
            a = packs[d.vehicle_id]["approval"]
            out[d.id] = f"{a['status']}; next: {a['next_action']}"
    return out


def record_decision(store: DecisionStore, d: Decision, capacity_minutes: int | None = None) -> Decision:
    """Check a decision against the current engine state and append it, or raise DecisionError.
    The decision is stored with what the engine said at that moment."""
    validate_shape(d)
    past = store.all()
    if d.kind == "rule_review":
        d = replace(d, context=_clean(_check_rule_review(d, past)))
        store.append(d)
        return d
    packs = build_month(capacity_minutes, past)
    if d.vehicle_id not in packs:
        raise DecisionError(f"No vehicle {d.vehicle_id!r}.")
    p = packs[d.vehicle_id]

    if d.kind == "part_review":
        g = decided_grades(past)
        row = g[(g.vehicle_id == d.vehicle_id) & (g.part_no == d.target)]
        if row.empty:
            raise DecisionError(f"{d.vehicle_id} has no graded part {d.target!r}.")
        r = row.iloc[0]
        if d.action == f"override:{r.engine_verdict}":
            raise DecisionError(f"{r.engine_verdict!r} is already the engine's verdict; accept it instead.")
        context = dict(engine_verdict=r.engine_verdict, engine_reason=r.reason, flags=r["flags"],
                       measured_value=r.measured_value, limit=r.limit, drawing_no=r.drawing_no,
                       rule_source=r.rule_source, next_action_before=r.next_action)
    elif d.kind == "harvest":
        cands = candidates()
        if not ((cands.vehicle_id == d.vehicle_id) & (cands.component == d.target)).any():
            raise DecisionError(f"{d.target!r} on {d.vehicle_id} cannot be harvested (grade, missing or always removed).")
        exclude, require = harvest_instructions(past + [d])
        try:
            plan_harvest(cands, capacity_minutes=capacity_minutes,
                         blocked=dismantle_blocked(check_month(None, decided_grades(past))),
                         exclude=exclude, require=require)
        except PlanError as e:
            raise DecisionError(f"The plan cannot follow this: {e}") from e
        context = dict(offer_before=p["value"]["offer"], harvested_before=d.target in p["plan"]["harvest"])
    else:
        if p["approval"]["status"] == "signed":
            raise DecisionError(f"{d.vehicle_id} is already signed off by {p['approval']['engineer']}.")
        if p["open_items"]:
            raise DecisionError(f"{d.vehicle_id} still has {len(p['open_items'])} open item(s); resolve them first.")
        context = dict(offer=p["value"]["offer"], compliance=p["compliance"]["status"],
                       harvest=p["plan"]["harvest"])

    d = replace(d, context=_clean(context))
    store.append(d)
    return d


def _check_rule_review(d: Decision, past: list[Decision]) -> dict:
    """Approve only a Gemini reading that passed the fixed gates and still does; reject any reading.
    The approval stores the rule as approved, so later re-reads cannot change it unnoticed."""
    g = gemini_rules().get(d.target)
    if g is None:
        raise DecisionError(f"No Gemini reading for {d.target!r} to review.")
    prior = next((x for x in reversed(past) if x.kind == "rule_review" and x.target == d.target), None)
    snap = {k: (None if isinstance(v, float) and v != v else v) for k, v in g.items()}
    as_read = None
    if d.action == "approve":
        if g["status"] != "checked":
            raise DecisionError(f"{d.target}: Gemini's reading failed the fixed checks ({g['problems']}); "
                                "it cannot be approved. Reject it, or re-read the drawing.")
        bom = pd.read_csv(DATA / "bom.csv")
        b = bom[bom.part_no == d.target].iloc[0].to_dict()
        problems = check_rule({**snap, "measure": b["measure"]}, b)    # re-check against the drawing now
        if problems:
            raise DecisionError(f"{d.target}: the reading no longer passes the fixed checks ({'; '.join(problems)}).")
        try:
            as_read = snapshot_rule(snap, bom).describe()
        except Exception as e:  # noqa: BLE001 - any invalid rule must stay inactive
            raise DecisionError(f"{d.target}: not a valid grading rule ({e}).") from e
        if prior and prior.action == "approve" and prior.context.get("rule") == snap:
            raise DecisionError(f"{d.target}: this reading is already approved by {prior.engineer}.")
    elif prior and prior.action == "reject" and prior.context.get("rule") == snap:
        raise DecisionError(f"{d.target}: this reading is already rejected by {prior.engineer}.")
    _, source = active_rules(past)
    return dict(rule=snap, drawing_no=snap.get("drawing_no"), gates=g["status"], gate_problems=g["problems"],
                rule_as_read=as_read, active_before=source.get(d.target))


def write_month(packs: dict[str, dict], out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for vid, p in packs.items():
        (out / f"{vid}.json").write_text(json.dumps(p, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    cap = int(sys.argv[1]) if len(sys.argv) > 1 else None
    packs = build_month(cap)
    write_month(packs)
    pd.set_option("display.width", 200)
    print(pd.DataFrame([dict(vehicle=k, compliance=p["compliance"]["status"], offer=p["value"]["offer"],
                             parts=len(p["plan"]["harvest"]), open_items=len(p["open_items"]),
                             approval=p["approval"]["status"]) for k, p in packs.items()]).to_string(index=False))
    print(f"\n{len(packs)} audit packs -> {OUT}")
