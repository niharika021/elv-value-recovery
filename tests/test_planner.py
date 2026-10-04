import pandas as pd
import pytest

from app.engines.planner import PAISE, PlanError, candidates, plan_harvest
from app.engines.value import month_table, value_month


@pytest.fixture(scope="module")
def cands():
    return candidates()


@pytest.fixture(scope="module")
def default():
    return {v.vehicle_id: v for v in value_month(with_grading=False)}


def best_by_dp(cands, capacity):
    """Exact 0/1 knapsack by dynamic programming over minutes, in paise: the planner must match it."""
    best = [0] * (capacity + 1)
    for n, w in zip((cands.net * PAISE).round().astype(int), cands.minutes.astype(int)):
        if n <= 0:
            continue
        for c in range(capacity, w - 1, -1):
            best[c] = max(best[c], best[c - w] + n)
    return best[capacity] / PAISE


# ---- no limits = the value engine's default rule ---------------------------------------

def test_unlimited_plan_is_the_default_rule(cands, default):
    plan = plan_harvest(cands)
    for vid, v in default.items():
        assert set(plan.harvests[vid]) == set(v.harvest)
    assert plan.minutes == 1240 and plan.status == "OPTIMAL" and plan.dropped.empty


def test_never_picks_a_negative_part_unless_required(cands):
    plan = plan_harvest(cands)
    picked = {(v, c) for v, cs in plan.harvests.items() for c in cs}
    negative = {(v, c) for v, c, n in zip(cands.vehicle_id, cands.component, cands.net) if n <= 0}
    assert negative and not picked & negative


# ---- labour capacity: proven optimal -----------------------------------------------------

@pytest.mark.parametrize("capacity", [0, 37, 300, 620, 930, 1239, 5000])
def test_capacity_plan_is_optimal_and_within_capacity(cands, capacity):
    plan = plan_harvest(cands, capacity_minutes=capacity)
    assert plan.minutes <= capacity
    assert plan.gain == pytest.approx(best_by_dp(cands, capacity), abs=0.01)


def test_less_capacity_never_earns_more(cands):
    gains = [plan_harvest(cands, capacity_minutes=c).gain for c in (1240, 930, 620, 310, 0)]
    assert gains == sorted(gains, reverse=True)


def test_ties_prefer_fewer_minutes():
    c = pd.DataFrame(dict(vehicle_id=["V1", "V2"], component=["a", "b"], net=[500.0, 500.0],
                          minutes=[30, 10], status="harvestable"))
    assert plan_harvest(c, capacity_minutes=30).harvests == {"V1": (), "V2": ("b",)}


def test_same_input_same_plan(cands):
    assert plan_harvest(cands, capacity_minutes=620).harvests == plan_harvest(cands, capacity_minutes=620).harvests


# ---- blocked vehicles and engineer decisions --------------------------------------------

def test_blocked_vehicles_harvest_nothing(cands, default):
    plan = plan_harvest(cands, blocked={"V04", "V07"})
    assert plan.harvests["V04"] == plan.harvests["V07"] == ()
    assert set(plan.dropped.why) == {"vehicle blocked"}
    t = month_table(value_month(plan.harvests, with_grading=False)).set_index("vehicle")
    assert t.loc["V07", "offer"] == default["V07"].offer_scrap_only


def test_engineer_exclusion_is_respected(cands):
    plan = plan_harvest(cands, exclude={("V08", "alternator")})
    assert "alternator" not in plan.harvests["V08"]
    assert plan.dropped.set_index(["vehicle_id", "component"]).loc[("V08", "alternator"), "why"] == "engineer excluded"


def test_engineer_requirement_is_respected_even_at_a_loss(cands):
    plan = plan_harvest(cands, require={("V02", "radiator")})   # net -50
    assert "radiator" in plan.harvests["V02"]


def test_required_parts_beyond_capacity_are_refused(cands):
    with pytest.raises(PlanError):
        plan_harvest(cands, capacity_minutes=20, require={("V05", "ac_compressor")})   # 35 min


@pytest.mark.parametrize("kw", [
    dict(require={("V09", "alternator")}),                       # grade C: not a candidate
    dict(exclude={("V99", "ecu")}),                              # no such vehicle
    dict(require={("V02", "ecu")}, exclude={("V02", "ecu")}),
    dict(require={("V07", "alternator")}, blocked={"V07"}),
])
def test_contradictory_or_unknown_instructions_are_refused(cands, kw):
    with pytest.raises(PlanError):
        plan_harvest(cands, **kw)


# ---- the value engine prices the plan ---------------------------------------------------

def test_plan_gain_matches_the_value_engine(cands, default):
    plan = plan_harvest(cands, capacity_minutes=620)
    priced = value_month(plan.harvests, with_grading=False)
    assert abs(sum(v.harvest_gain for v in priced) - plan.gain) <= len(priced)   # per-vehicle rounding
    assert all(v.offer <= default[v.vehicle_id].offer for v in priced)


def test_every_vehicle_is_in_the_plan_even_with_nothing_to_harvest(cands):
    plan = plan_harvest(cands)
    assert len(plan.harvests) == 12 and plan.harvests["V09"] == ()
