"""Submission hardening: drawing-rule approval, approval -> action, C08 from the decision log,
dashboard KPIs. Grouped by change. Gemini readings that differ from the baseline are built in
memory to prove which rule grades a part; the data files are never modified."""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.elv_agent import tools
from app.engines import rule_check
from app.engines.audit import build_month, decided_grades, decision_outcomes, record_decision
from app.engines.compliance import check_month, check_vehicle, load_rule_pack
from app.engines.decisions import Decision, DecisionError, JsonlStore, MemoryStore
from app.engines.rule_check import active_rules, gemini_rules
from app.web.server import app


def dec(kind, vid, action, target="", reason="checked", engineer="A. Engineer", context=None):
    return Decision(engineer=engineer, kind=kind, vehicle_id=vid, action=action, target=target, reason=reason,
                    context=context or {})


def grade(decisions, vid, part):
    g = decided_grades(decisions)
    return g[(g.vehicle_id == vid) & (g.part_no == part)].iloc[0]


def str03_reading(**changes):
    """Gemini's real STR-03 reading (min 8.5 mm, replace), with changes for the test."""
    return {**gemini_rules()["STR-03"], **changes}


LOOSER = dict(limit_1=7.5, evidence="1. SERVICE WEAR LIMIT: BRUSH LENGTH 7.5 mm MIN. 2. IF BELOW LIMIT: REPLACE WITH NEW OR GRADE-A PART.")


# ==== Change 1: engineer approval of Gemini's drawing rules ====================================

def test_baseline_grades_everything_until_a_rule_is_approved():
    rules, source = active_rules([])
    assert len(rules) == 20 and all(s.startswith("baseline") for s in source.values())
    assert grade([], "V05", "STR-03").verdict == "replace"            # 7.9 mm against baseline min 8.5


def test_an_approved_rule_is_the_one_used():
    approve = dec("rule_review", "", "approve", "STR-03", context={"rule": str03_reading(**LOOSER)})
    g = grade([approve], "V05", "STR-03")
    assert g.limit == "min 7.5 mm" and g.verdict == "reuse" and "approved by A. Engineer" in g.rule_source


def test_a_rejected_rule_is_not_used():
    reject = dec("rule_review", "", "reject", "STR-03", context={"rule": str03_reading(**LOOSER)})
    g = grade([reject], "V05", "STR-03")
    assert g.limit == "min 8.5 mm" and g.verdict == "replace" and g.rule_source.startswith("baseline")


def test_the_latest_decision_wins_approve_then_reject():
    snap = {"rule": str03_reading(**LOOSER)}
    ds = [dec("rule_review", "", "approve", "STR-03", context=snap), dec("rule_review", "", "reject", "STR-03", context=snap)]
    assert grade(ds, "V05", "STR-03").verdict == "replace"


def test_a_pending_reading_cannot_produce_a_pass(monkeypatch):
    # Gemini "reads" a looser limit that would pass V05's brushes, but nobody has approved it.
    monkeypatch.setattr(rule_check, "gemini_rules", lambda path=None: {"STR-03": str03_reading(**LOOSER)})
    assert build_month(decisions=[])["V05"]["grading"][2]["verdict"] == "replace"
    assert grade([], "V05", "STR-03").rule_source.startswith("baseline")


@pytest.mark.parametrize("bad", [
    dict(status="rejected"),                                   # failed the fixed gates
    dict(limit_type="range", limit_1=9.0, limit_2=8.0),         # not a valid rule
    dict(part_no="STR-04"),                                    # snapshot for another part
])
def test_an_invalid_extraction_never_becomes_active(bad):
    approve = dec("rule_review", "", "approve", "STR-03", context={"rule": str03_reading(**{**LOOSER, **bad})})
    assert grade([approve], "V05", "STR-03").limit == "min 8.5 mm"


def test_a_reading_that_failed_the_gates_cannot_be_approved():
    with pytest.raises(DecisionError, match="failed the fixed checks"):
        record_decision(MemoryStore(), dec("rule_review", "", "approve", "STR-01", reason="looks fine"))


def test_the_gates_are_rerun_at_approval(monkeypatch):
    # A reading marked "checked" whose limit is not in its quote (8.0 vs the 8.5 printed) is refused now.
    monkeypatch.setattr(rule_check, "gemini_rules", lambda path=None: {"STR-03": str03_reading(limit_1=8.0)})
    import app.engines.audit as audit
    monkeypatch.setattr(audit, "gemini_rules", rule_check.gemini_rules)
    with pytest.raises(DecisionError, match="no longer passes"):
        record_decision(MemoryStore(), dec("rule_review", "", "approve", "STR-03"))


def test_approval_is_recorded_append_only_with_everything_needed_for_audit(tmp_path):
    s = JsonlStore(tmp_path / "log.jsonl")
    a = record_decision(s, dec("rule_review", "", "approve", "STR-03", reason="matches drawing note 1"))
    with pytest.raises(DecisionError, match="already approved"):
        record_decision(s, dec("rule_review", "", "approve", "STR-03"))
    b = record_decision(s, dec("rule_review", "", "reject", "STR-03", reason="re-check the drawing revision"))
    log = JsonlStore(tmp_path / "log.jsonl").all()
    assert [d.id for d in log] == [a.id, b.id]
    c = log[0].context
    assert c["drawing_no"] == "DWG-STR-03" and c["rule"]["limit_1"] == 8.5 and c["rule"]["unit"] == "mm"
    assert c["rule"]["verdict_if_fail"] == "replace" and "8.5 mm MIN" in c["rule"]["evidence"]
    assert c["gates"] == "checked" and c["rule_as_read"] == "min 8.5 mm" and c["active_before"].startswith("baseline")
    assert (log[0].engineer, log[0].reason) == ("A. Engineer", "matches drawing note 1") and log[0].at
    assert active_rules(log)[1]["STR-03"].startswith("baseline")    # rejected last


def test_rule_decisions_are_for_parts_not_vehicles():
    with pytest.raises(DecisionError, match="part number"):
        record_decision(MemoryStore(), dec("rule_review", "V05", "approve", "STR-03"))


def test_a_rule_approval_makes_an_earlier_sign_off_stale():
    s = MemoryStore()
    record_decision(s, dec("sign_off", "V01", "sign"))
    assert build_month(decisions=s.all())["V01"]["approval"]["status"] == "signed"
    record_decision(s, dec("rule_review", "", "approve", "STR-03", reason="matches the drawing"))   # V01 starter graded
    assert build_month(decisions=s.all())["V01"]["approval"]["status"] == "ready"


# ==== Change 2: approval -> action ================================================================

def test_no_action_before_approval_where_approval_is_required():
    g = grade([], "V05", "STR-03")
    assert (g.status, g.next_action) == ("Awaiting engineer", "Hold: awaiting engineer decision")


def test_approval_releases_the_engines_action():
    g = grade([dec("part_review", "V05", "accept", "STR-03")], "V05", "STR-03")
    assert g.status == "Approved by A. Engineer" and g.next_action == "Replace with a new or Grade-A part"


def test_override_is_recorded_and_changes_the_action():
    s = MemoryStore()
    d = record_decision(s, dec("part_review", "V08", "override:replace", "ALT-08", reason="noisy on spin test"))
    g = grade(s.all(), "V08", "ALT-08")
    assert g.verdict == "replace" and g.engine_verdict == "reuse" and g.next_action.startswith("Replace")
    assert g.status == "Overridden by A. Engineer (engine said reuse)"
    assert d.context["next_action_before"] == "Hold: awaiting engineer decision"
    assert "next: Replace" in decision_outcomes(s.all(), build_month(decisions=s.all()))[d.id]


def test_request_review_keeps_the_part_on_hold_and_blocks_sign_off():
    s = MemoryStore()
    record_decision(s, dec("part_review", "V03", "request_review", "ALT-03", reason="re-measure slip rings"))
    record_decision(s, dec("part_review", "V03", "accept", "ALT-08", reason="bearing quiet"))
    g = grade(s.all(), "V03", "ALT-03")
    assert g.needs_review and g.next_action == "Hold: further inspection"
    with pytest.raises(DecisionError, match="open item"):
        record_decision(s, dec("sign_off", "V03", "sign"))
    record_decision(s, dec("part_review", "V03", "accept", "ALT-03", reason="re-measured 14.05 mm"))
    record_decision(s, dec("sign_off", "V03", "sign"))
    assert build_month(decisions=s.all())["V03"]["approval"]["next_action"].startswith("Released")


def test_unflagged_parts_follow_the_engine():
    g = grade([], "V02", "ALT-06")
    assert g.status == "Engine verdict (no review needed)" and g.next_action == "Harvest for reuse"


def test_vehicle_next_actions():
    packs = build_month(decisions=[])
    assert packs["V07"]["approval"]["next_action"].startswith("Hold: compliance blocks dismantling (C01)")
    assert packs["V01"]["approval"]["next_action"] == "Awaiting engineer sign-off"
    assert packs["V05"]["approval"]["next_action"].startswith("Hold: resolve 3 open item")


def test_outcomes_mark_superseded_decisions():
    s = MemoryStore()
    a = record_decision(s, dec("harvest", "V02", "require", "radiator", reason="order"))
    b = record_decision(s, dec("harvest", "V02", "clear", "radiator", reason="cancelled"))
    out = decision_outcomes(s.all(), build_month(decisions=s.all()))
    assert out[a.id] == "superseded by a later decision" and "radiator left on the vehicle" in out[b.id]


# ==== Change 3: C08 from the decision log; no waivers ============================================

def c08(results, vid):
    return next(r for r in results[vid].results if r.rule_id == "C08")


def test_c08_with_no_overrides():
    r = c08(build_month_compliance([]), "V08")
    assert r.status == "pass" and "no engineer overrides recorded" in r.detail


def test_c08_counts_logged_overrides():
    s = MemoryStore()
    record_decision(s, dec("part_review", "V08", "override:replace", "ALT-08", reason="noise"))
    r = c08(build_month_compliance(s.all()), "V08")
    assert r.status == "pass" and r.detail.startswith("1 engineer override")


def test_c08_ignores_a_stale_evidence_file_value():
    rules = load_rule_pack()
    v = check_vehicle("V08", {"overrides_logged": "N"}, ("alternator",), True, {}, rules[rules.rule_id == "C08"],
                      overrides=[dec("part_review", "V08", "override:replace", "ALT-08", reason="noise")])
    assert v.results[0].status == "pass" and "decision log is the record" in v.results[0].detail


def test_c08_fails_an_override_without_a_reason():
    rules = load_rule_pack()
    v = check_vehicle("V08", {}, ("alternator",), True, {}, rules[rules.rule_id == "C08"],
                      overrides=[dec("part_review", "V08", "override:replace", "ALT-08", reason=" ")])
    assert v.results[0].status == "fail"


def test_audit_pack_carries_the_log_based_c08():
    s = MemoryStore()
    record_decision(s, dec("harvest", "V08", "exclude", "alternator", reason="cracked housing"))
    p = build_month(decisions=s.all())["V08"]
    r = next(r for r in p["compliance"]["rules"] if r["rule_id"] == "C08")
    assert r["status"] == "pass" and "1 engineer override" in r["detail"]


def test_there_is_no_compliance_waiver():
    with pytest.raises(DecisionError, match="Unknown kind"):
        record_decision(MemoryStore(), dec("compliance_waiver", "V07", "waive", "C01", reason="trust me"))
    assert build_month(decisions=[])["V07"]["compliance"]["can_dismantle"] is False


def build_month_compliance(decisions):
    g = decided_grades(decisions)
    return check_month({v: tuple(p["plan"]["harvest"]) for v, p in build_month(decisions=decisions).items()},
                       g, decisions=decisions)


# ==== Change 5: dashboard KPIs come from the engines ================================================

def test_month_kpis_are_consistent_engine_aggregates():
    m = tools.month_overview()["month"]
    packs = tools._packs()
    assert m["harvest_gain_inr"] == round(sum(p["value"]["harvest_gain"] for p in packs.values()))
    gap_drop = m["average_gap_scrap_only_inr"] - m["average_gap_inr"]
    assert abs((m["average_offer_inr"] - m["average_offer_scrap_only_inr"]) - gap_drop) <= 1
    assert m["open_items"] == sum(len(p["open_items"]) for p in packs.values())


# ==== API ============================================================================================

@pytest.fixture
def client():
    tools.STORE.path.unlink(missing_ok=True)
    yield TestClient(app)
    tools.STORE.path.unlink(missing_ok=True)


def test_rules_api_and_approval_flow(client):
    r = client.get("/api/rules").json()
    assert len(r["rules"]) == 20 and r["pending"] == 19
    assert next(x for x in r["rules"] if x["part_no"] == "STR-01")["state"] == "failed the fixed checks"
    ok = client.post("/api/decisions", json=dict(engineer="T", kind="rule_review", action="approve",
                                                 vehicle_id="", target="str-03", reason="matches note"))
    assert ok.status_code == 201 and "Gemini" in ok.json()["outcome"]
    bad = client.post("/api/decisions", json=dict(engineer="T", kind="rule_review", action="approve",
                                                  vehicle_id="", target="STR-01", reason="x"))
    assert bad.status_code == 400 and "fixed checks" in bad.json()["detail"]
    inbox = client.get("/api/inbox").json()
    assert inbox["rules_pending"] == 18 and inbox["recent"][0]["outcome"].startswith("STR-03 is graded with: Gemini")
