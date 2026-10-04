"""Rule check and drawing reader, offline: a fake reader stands in for Gemini."""
import re

import pandas as pd
import pytest

from app.agents.drawing_reader import extract_rules
from app.engines.grading import DATA, load_rules
from app.engines.rule_check import DRAWINGS, check_rules, drawing_text, score_against_reference

REF = pd.read_csv(DATA / "grading_rules_reference.csv").set_index("part_no")
BOM = pd.read_csv(DATA / "bom.csv")


def notes(drawing_no):
    """Note lines 1 and 2 of a drawing, as printed: the limit and the action."""
    t = drawing_text(DRAWINGS / f"{drawing_no}.pdf")
    return re.search(r"1\. .*?(?= 3\. )", t).group(0)


def perfect_read(pdf, b):
    r = REF.loc[b["part_no"]]
    return dict(part_no=b["part_no"], drawing_no=b["drawing_no"], unit=b["unit"], limit_type=r.limit_type,
                limit_1=None if pd.isna(r.limit_1) else r.limit_1, limit_2=None if pd.isna(r.limit_2) else r.limit_2,
                verdict_if_fail=r.verdict_if_fail, evidence=notes(b["drawing_no"]))


def reader_with(part_no, **wrong):
    def read(pdf, b):
        r = perfect_read(pdf, b)
        return {**r, **wrong} if b["part_no"] == part_no else r
    return read


def status(checked, part_no):
    row = checked.set_index("part_no").loc[part_no]
    return row.status, row.problems


@pytest.fixture(scope="module")
def perfect():
    return check_rules(extract_rules(perfect_read))


# ---- a perfect reading passes every gate and scores 20/20 --------------------------------

def test_perfect_reading_passes_and_matches_the_key(perfect):
    assert (perfect.status == "checked").all() and len(perfect) == 20
    assert score_against_reference(perfect).correct.all()


def test_checked_rules_load_into_the_grading_engine(perfect):
    rules = load_rules(perfect, BOM)
    assert rules["STR-03"].limit_1 == 8.5 and rules["ALT-06"].limit_2 == 14.8


def test_measure_comes_from_the_bom_not_the_reader(perfect):
    assert perfect.set_index("part_no").loc["STR-03", "measure"] == "brush_length"


# ---- each way Gemini could go wrong is caught --------------------------------------------

def test_nominal_dimension_mistaken_for_the_limit_is_rejected():
    # the brush drawing shows 8.0 (width) beside the 8.5 MIN wear limit
    checked = check_rules(extract_rules(reader_with("STR-03", limit_1=8.0)))
    s, p = status(checked, "STR-03")
    assert s == "rejected" and "limit_1 8.0 is not in the evidence quote" in p


def test_invented_quote_is_rejected():
    checked = check_rules(extract_rules(reader_with("STR-03", limit_1=9.0,
                                                    evidence="1. SERVICE WEAR LIMIT: BRUSH LENGTH 9.0 mm MIN.")))
    assert "evidence not found" in status(checked, "STR-03")[1]


def test_quote_from_another_drawing_is_rejected():
    checked = check_rules(extract_rules(reader_with("STR-03", evidence=notes("DWG-ALT-05"))))
    assert "evidence not found on DWG-STR-03.pdf" in status(checked, "STR-03")[1]


def test_wrong_verdict_is_rejected():
    checked = check_rules(extract_rules(reader_with("STR-02", verdict_if_fail="replace")))   # drawing says scrap
    assert "verdict 'replace' is not named" in status(checked, "STR-02")[1]


@pytest.mark.parametrize("wrong, expected", [
    (dict(unit="in"), "does not match BOM unit"),
    (dict(drawing_no="DWG-STR-04"), "drawing_no"),
    (dict(limit_type="range", limit_1=14.8, limit_2=14.2), "range needs limit_1 < limit_2"),
    (dict(limit_type="pass_fail"), "pass_fail takes no limits"),
    (dict(evidence=""), "no evidence quote"),
])
def test_malformed_or_mismatched_rules_are_rejected(wrong, expected):
    part = "ALT-06"
    checked = check_rules(extract_rules(reader_with(part, **wrong)))
    s, p = status(checked, part)
    assert s == "rejected" and expected in p


def test_failed_read_is_missing_not_guessed():
    def read(pdf, b):
        if b["part_no"] == "ALT-08":
            raise RuntimeError("timeout")
        return perfect_read(pdf, b)
    checked = check_rules(extract_rules(read))
    assert status(checked, "ALT-08") == ("rejected", "no rule extracted")
    assert score_against_reference(checked).set_index("part_no").loc["ALT-08", "status"] == "rejected"


def test_a_rule_for_a_part_not_in_the_bom_is_rejected():
    extra = pd.concat([extract_rules(perfect_read), pd.DataFrame([dict(part_no="XYZ-01", drawing_no="DWG-XYZ-01")])])
    assert status(check_rules(extra), "XYZ-01") == ("rejected", "part not in BOM")


def test_score_names_the_wrong_field():
    checked = check_rules(extract_rules(reader_with("STR-08", limit_1=0.25)))
    row = score_against_reference(checked).set_index("part_no").loc["STR-08"]
    assert not row.correct and "limit_1: read 0.25, key 0.15" in row.wrong
