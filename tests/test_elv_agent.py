"""Agent tools and grounding check, offline (no model calls)."""
import json

import pytest

from app.elv_agent import tools
from app.elv_agent.agent import compliance_agent, inspection_agent, root_agent
from app.elv_agent.grounding import numbers_in_text, ungrounded

ALL_TOOLS = [tools.month_overview, tools.vehicle_value, tools.plan_what_if, tools.vehicle_grading,
             tools.review_queue, tools.drawing_rule, tools.vehicle_compliance, tools.compliance_overview]


# ---- tools: engine figures, read-only, JSON-safe ----------------------------------------

def test_agents_only_have_the_read_only_tools():
    given = {t.__name__ for a in (root_agent, inspection_agent, compliance_agent) for t in a.tools}
    assert given == {t.__name__ for t in ALL_TOOLS}
    assert all(t.__doc__ for t in ALL_TOOLS)   # the docstring is what the model sees


def test_every_tool_returns_json_safe_output():
    for t, args in [(tools.month_overview, ()), (tools.vehicle_value, ("V05",)), (tools.plan_what_if, (620,)),
                    (tools.vehicle_grading, ("V05",)), (tools.review_queue, ()), (tools.drawing_rule, ("STR-03",)),
                    (tools.vehicle_compliance, ("V07",)), (tools.compliance_overview, ())]:
        json.dumps(t(*args))


def test_figures_are_the_engines():
    v = tools.vehicle_value("V05")["value"]
    assert (v["offer"], v["offer_scrap_only"], v["informal_offer"]) == (41984, 32250, 47000)
    m = tools.month_overview()["month"]
    assert m["blocked_before_dismantling"] == ["V04", "V07"]


@pytest.mark.parametrize("given", ["v5", "V5", " V05 ", "v05"])
def test_vehicle_ids_are_normalised(given):
    assert tools.vehicle_value(given)["vehicle_id"] == "V05"


@pytest.mark.parametrize("tool", [tools.vehicle_value, tools.vehicle_grading, tools.vehicle_compliance])
def test_unknown_vehicle_is_an_error_not_a_guess(tool):
    assert "error" in tool("V99")


def test_unknown_part_is_an_error():
    assert "error" in tools.drawing_rule("XYZ-01")


def test_drawing_rule_shows_gemini_beside_the_reference():
    r = tools.drawing_rule("str-03")
    assert r["reference"]["limit_1"] == 8.5
    if "gemini" in r:   # present once the drawing reader has run
        assert r["gemini"]["limit_1"] == 8.5 and "8.5" in r["gemini"]["evidence"]


def test_review_queue_has_the_planted_parts():
    q = {(p["vehicle_id"], p["part_no"]) for p in tools.review_queue()["parts"]}
    assert {("V05", "STR-03"), ("V08", "ALT-08")} <= q


def test_what_if_keeps_compliance_blocks_and_respects_capacity():
    w = tools.plan_what_if(300)
    assert w["minutes_used"] <= 300 and w["blocked_before_dismantling"] == ["V04", "V07"]
    assert w["left_for_capacity"]
    assert "error" in tools.plan_what_if(-1)


# ---- grounding ---------------------------------------------------------------------------

def test_identifiers_and_list_markers_are_not_figures():
    assert numbers_in_text("1. V05 STR-03 on DWG-STR-03 fails C06; HW-9212") == []


def test_number_formats():
    assert numbers_in_text("INR 41,984 and 7.9 mm, 66.0%, 1,240 min") == [41984, 7.9, 66.0, 1240]


def test_grounded_answer_passes():
    result = {"value": {"offer": 41984}, "reason": "7.9 mm outside min 8.5 mm", "margin": 0.06}
    assert ungrounded("Offer INR 41,984: 7.9 mm is under 8.5 mm, 6% margin left.", [result]) == []


def test_invented_figure_is_caught():
    result = {"value": {"offer": 41984}}
    assert ungrounded("Offer INR 41,984, about INR 42,000 after rounding.", [result]) == [42000]


def test_numbers_from_the_question_are_allowed():
    assert ungrounded("With 620 minutes the gain is INR 54,366.", [{"gain": 54366}], "what about 620 minutes?") == []


def test_overview_gives_the_gap_before_harvesting():
    rows = {r["vehicle_id"]: r for r in tools.month_overview()["vehicles"]}
    assert rows["V10"]["gap_scrap_only_inr"] == 41000 - 17831
    assert max(rows, key=lambda k: rows[k]["gap_scrap_only_inr"]) == "V10"
