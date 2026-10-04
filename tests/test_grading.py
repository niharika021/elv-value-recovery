import pandas as pd
import pytest

from app.engines.grading import (BORDERLINE, NO_PHOTO, NO_READING, NOTE_CONTRADICTS, NOTE_SUGGESTS_WEAR,
                                 GradingRule, RuleError, grade_inspections, grade_part, load_rules,
                                 summarise_units)

PHOTO = "photos/x.jpg"


def rule(limit_type, l1=None, l2=None, nominal=None, verdict="replace", unit="mm"):
    return GradingRule("P-01", "m", unit, limit_type, l1, l2, verdict, "DWG-P-01", nominal)


@pytest.fixture(scope="module")
def grades():
    return grade_inspections()


def part(grades, vid, part_no):
    return grades[(grades.vehicle_id == vid) & (grades.part_no == part_no)].iloc[0]


# ---- limit types, boundaries inclusive -------------------------------------------------

@pytest.mark.parametrize("value, result", [(8.5, "pass"), (8.49, "fail"), (14.0, "pass")])
def test_min(value, result):
    assert grade_part(rule("min", 8.5, nominal=14.0), value, photo_uri=PHOTO).result == result


@pytest.mark.parametrize("value, result", [(0.10, "pass"), (0.1001, "fail"), ("0.1", "pass")])
def test_max(value, result):
    assert grade_part(rule("max", 0.10, nominal=0.02), value, photo_uri=PHOTO).result == result


@pytest.mark.parametrize("value, result", [(14.2, "pass"), (14.8, "pass"), (14.19, "fail"), (14.81, "fail")])
def test_range(value, result):
    assert grade_part(rule("range", 14.2, 14.8, nominal=14.5), value, photo_uri=PHOTO).result == result


@pytest.mark.parametrize("value, result", [(2, "pass"), (3, "fail")])
def test_scale_max(value, result):
    assert grade_part(rule("scale_max", 2, unit="0-3"), value, photo_uri=PHOTO).result == result


@pytest.mark.parametrize("value, result", [("pass", "pass"), ("FAIL", "fail"), ("maybe", "no_reading")])
def test_pass_fail(value, result):
    assert grade_part(rule("pass_fail", unit="-"), value, photo_uri=PHOTO).result == result


def test_fail_takes_the_drawing_verdict():
    g = grade_part(rule("min", 31.2, nominal=32.0, verdict="scrap"), 31.0, photo_uri=PHOTO)
    assert (g.result, g.verdict) == ("fail", "scrap")


@pytest.mark.parametrize("value", [None, float("nan"), "", "n/a"])
def test_missing_reading_is_never_a_pass(value):
    g = grade_part(rule("max", 0.1, nominal=0.02), value, photo_uri=PHOTO)
    assert g.verdict == "needs_inspection" and NO_READING in g.flags and g.needs_review


# ---- margin and flags ------------------------------------------------------------------

def test_margin_is_share_of_band_left():
    assert grade_part(rule("min", 8.5, nominal=14.0), 14.0, photo_uri=PHOTO).margin == 1.0
    assert grade_part(rule("max", 0.10, nominal=0.02), 0.06, photo_uri=PHOTO).margin == 0.5
    assert grade_part(rule("range", 14.2, 14.8, nominal=14.5), 14.5, photo_uri=PHOTO).margin == 1.0


def test_borderline_threshold_is_a_parameter():
    r = rule("max", 0.10, nominal=0.02)
    assert BORDERLINE in grade_part(r, 0.095, photo_uri=PHOTO).flags          # 6% left
    assert BORDERLINE not in grade_part(r, 0.095, photo_uri=PHOTO, borderline=0.05).flags


def test_notes_flag_but_never_change_the_verdict():
    r = rule("min", 8.5, nominal=14.0)
    bad_note = grade_part(r, 12.0, note="heavy wear visible", photo_uri=PHOTO)
    assert bad_note.verdict == "reuse" and NOTE_SUGGESTS_WEAR in bad_note.flags
    ok_note = grade_part(r, 7.0, note="looks ok", photo_uri=PHOTO)
    assert ok_note.verdict == "replace" and NOTE_CONTRADICTS in ok_note.flags


def test_electrical_fail_with_ok_note_is_not_a_contradiction():
    g = grade_part(rule("pass_fail", unit="-", verdict="scrap"), "fail", note="looks ok", photo_uri=PHOTO)
    assert NOTE_CONTRADICTS not in g.flags


def test_missing_photo_is_evidence_gap_not_engineering_review():
    g = grade_part(rule("min", 8.5, nominal=14.0), 12.0, photo_uri="")
    assert NO_PHOTO in g.flags and not g.needs_review


# ---- rule validation (rules will come from Gemini) ------------------------------------

def rules_df(**over):
    row = dict(part_no="P-01", measure="m", unit="mm", limit_type="min", limit_1=8.5, limit_2=None,
               verdict_if_fail="replace", drawing_no="DWG-P-01")
    return pd.DataFrame([{**row, **over}])


BOM = pd.DataFrame([dict(part_no="P-01", nominal=14.0)])


@pytest.mark.parametrize("over", [
    dict(limit_type="minimum"),
    dict(verdict_if_fail="bin"),
    dict(limit_1=None),
    dict(limit_type="range", limit_1=14.8, limit_2=14.2),
    dict(limit_type="pass_fail"),
])
def test_malformed_rules_are_rejected(over):
    with pytest.raises(RuleError):
        load_rules(rules_df(**over), BOM)


def test_inspection_without_a_rule_is_an_error():
    ins = pd.DataFrame([dict(vehicle_id="V99", unit_type="starter", part_no="XXX-01", measure="m",
                             measured_value="1", inspector_note="", photo_uri=PHOTO, inspector="I")])
    with pytest.raises(RuleError):
        grade_inspections(ins)


def test_reference_rules_load():
    rules = load_rules()
    assert len(rules) == 20 and rules["STR-03"].limit_1 == 8.5 and rules["STR-03"].nominal == 14.0


# ---- the synthetic month and its planted stories ---------------------------------------

def test_every_inspection_is_graded(grades):
    assert len(grades) == 190 and set(grades.result) <= {"pass", "fail"}


def test_v05_brushes_below_minimum_despite_note(grades):
    g = part(grades, "V05", "STR-03")
    assert g.verdict == "replace" and NOTE_CONTRADICTS in g["flags"] and g.needs_review


def test_v08_borderline_bearing_goes_to_engineer(grades):
    g = part(grades, "V08", "ALT-08")
    assert g.verdict == "reuse" and BORDERLINE in g["flags"] and NOTE_SUGGESTS_WEAR in g["flags"]
    assert g.needs_review


def test_v02_regulator_is_perfect(grades):
    g = part(grades, "V02", "ALT-06")
    assert g.verdict == "reuse" and g.margin == 1.0 and not g.needs_review


def test_v11_photos_missing_on_every_part(grades):
    v11 = grades[grades.vehicle_id == "V11"]
    assert len(v11) == 20 and v11["flags"].str.contains(NO_PHOTO).all()


def test_flood_car_has_nothing_to_grade(grades):
    assert "V09" not in set(grades.vehicle_id)


def test_engine_agrees_with_the_generators_wear_notes(grades):
    """The generator writes a damage note whenever a dimension is out of limit; V05 STR-03 is the planted exception."""
    dims = grades[grades.margin.notna()]  # margin exists only for min / max / range limits
    fails = dims[(dims.result == "fail") & ~((dims.vehicle_id == "V05") & (dims.part_no == "STR-03"))]
    assert len(fails) > 0 and fails.inspector_note.isin(["heavy wear visible", "scoring on surface", "discoloured from heat",
                                      "pitting", "worn unevenly"]).all()


def test_unit_summary(grades):
    u = summarise_units(grades).set_index(["vehicle_id", "unit_type"])
    assert len(u) == 19
    assert u.loc[("V05", "starter"), "status"] == "engineer_review"
    assert u.loc[("V02", "alternator"), "reuse"] == 10
