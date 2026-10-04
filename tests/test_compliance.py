import pandas as pd
import pytest

from app.engines.compliance import (ComplianceError, check_month, dismantle_blocked, load_rule_pack,
                                    month_summary)
from app.engines.grading import DATA
from app.engines.planner import plan_harvest


@pytest.fixture(scope="module")
def plan():
    return plan_harvest(blocked=dismantle_blocked())


@pytest.fixture(scope="module")
def month(plan):
    return check_month(plan.harvests)


def result(month, vid, rule_id):
    return next(r for r in month[vid].results if r.rule_id == rule_id)


# ---- planted stories -------------------------------------------------------------------

def test_v04_and_v07_are_blocked_before_dismantling():
    assert dismantle_blocked() == {"V04", "V07"}


def test_blocked_vehicles_are_not_harvested(plan):
    assert plan.harvests["V04"] == plan.harvests["V07"] == ()


def test_v07_red_no_depollution_record(month):
    assert month["V07"].status == "red" and result(month, "V07", "C01").status == "fail"
    assert not month["V07"].can_dismantle and not month["V07"].can_release


def test_v04_red_no_certificate_of_deposit(month):
    assert month["V04"].status == "red" and result(month, "V04", "C02").status == "fail"


def test_v12_amber_no_hazwaste_manifest(month):
    assert month["V12"].status == "amber" and [r.rule_id for r in month["V12"].fails] == ["C04"]
    assert month["V12"].can_dismantle and not month["V12"].can_release


def test_v11_amber_grading_evidence(month):
    assert result(month, "V11", "C06").status == "fail" and month["V11"].status == "amber"


# ---- rules that do not apply are not failures --------------------------------------------

def test_v10_converter_rule_does_not_apply(month):
    r = result(month, "V10", "C09")
    assert r.status == "n/a" and "no catalytic converter" in r.detail


def test_nothing_harvested_means_harvest_rules_do_not_apply(month):
    for vid in ("V04", "V07", "V09"):
        assert {r.rule_id for r in month[vid].results if r.status == "n/a"} >= {"C05", "C06", "C07"}
    assert month["V09"].status == "green"


def test_before_planning_harvest_rules_are_pending():
    early = check_month(None)
    assert result(early, "V01", "C06").detail == "pending: harvest not planned yet"
    assert {v for v, c in early.items() if not c.can_dismantle} == {"V04", "V07"}


# ---- evidence is cross-checked, not taken on trust ---------------------------------------

def test_missing_photos_override_the_evidence_file(month):
    r = result(month, "V02", "C06")      # evidence file says Y; grading finds 2 photos missing
    assert r.status == "fail" and "evidence file says complete" in r.detail


def test_only_harvested_units_need_photos(plan):
    no_units = {**plan.harvests, "V02": tuple(c for c in plan.harvests["V02"]
                                             if c not in ("starter_motor", "alternator"))}
    assert result(check_month(no_units), "V02", "C06").status == "pass"


# ---- rule pack validation ----------------------------------------------------------------

def test_a_rule_with_no_stage_decision_is_refused():
    rules = pd.read_csv(DATA / "compliance_rules.csv")
    rules.loc[len(rules)] = ["C10", "New rule", "new_evidence_field", "amber", "x"]
    with pytest.raises(ComplianceError):
        load_rule_pack(rules)


def test_unknown_severity_is_refused():
    rules = pd.read_csv(DATA / "compliance_rules.csv")
    rules.loc[0, "severity"] = "purple"
    with pytest.raises(ComplianceError):
        load_rule_pack(rules)


def test_summary_has_every_vehicle(month):
    s = month_summary(month)
    assert len(s) == 12 and set(s.status) <= {"red", "amber", "green"}
