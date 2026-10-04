"""Audit pack: one JSON record per vehicle, built only from engine outputs.

Order matters: dismantle-stage compliance -> harvest plan (blocked vehicles untouched) ->
value -> full compliance on what was actually harvested -> open items for the engineer.
Every number comes from an engine; the agents (Day 8) explain the pack, they never edit it.

Run:  python -m app.engines.audit [capacity_minutes]   -> out/audit/V01.json ... + month summary
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from app.engines.compliance import check_month, dismantle_blocked, month_summary
from app.engines.grading import DATA, grade_inspections
from app.engines.planner import plan_harvest
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


def build_month(capacity_minutes: int | None = None) -> dict[str, dict]:
    grades = grade_inspections()
    blocked = dismantle_blocked(check_month(None, grades))
    plan = plan_harvest(capacity_minutes=capacity_minutes, blocked=blocked)
    values = {v.vehicle_id: v for v in value_month(plan.harvests)}
    compliance = check_month(plan.harvests, grades)
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
            approval=dict(status="pending" if open_items else "ready", engineer=None, signed_at=None),
            sources=dict(
                grading_rules="data/grading_rules_reference.csv (Gemini-read rules await engineer approval)",
                compliance_rules=rule_sources,
                data=["vehicles.csv", "components.csv", "inspections.csv", "market_prices.csv",
                      "part_market.csv", "compliance_evidence.csv", "carbon_factors.csv"],
                disclaimer="Synthetic hackathon data; the rule pack is a demo summary, not legal advice.",
            ),
        ))
    return packs


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
