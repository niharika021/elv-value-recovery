import pytest

from app.engines.audit import build_month, record_decision
from app.engines.decisions import Decision, DecisionError, JsonlStore, MemoryStore


def dec(kind, vid, action, target="", reason="checked on the bench", engineer="A. Engineer"):
    return Decision(engineer=engineer, kind=kind, vehicle_id=vid, action=action, target=target, reason=reason)


def packs(store):
    return build_month(decisions=store.all())


def part(p, part_no):
    return next(g for g in p["grading"] if g["part_no"] == part_no)


# ---- shape -----------------------------------------------------------------------------------

@pytest.mark.parametrize("d, msg", [
    (dec("part_review", "V05", "accept", "STR-03", engineer=" "), "engineer"),
    (dec("part_review", "V05", "accept", "STR-03", reason=""), "reason"),
    (dec("part_review", "V05", "override:polish", "STR-03"), "cannot"),
    (dec("harvest", "V05", "exclude", ""), "target"),
    (dec("sign_off", "V01", "sign", "STR-03"), "no target"),
    (dec("approve", "V01", "sign"), "Unknown kind"),
])
def test_malformed_decisions_are_refused_and_not_stored(d, msg):
    s = MemoryStore()
    with pytest.raises(DecisionError, match=msg):
        record_decision(s, d)
    assert s.all() == []


# ---- part reviews --------------------------------------------------------------------------

def test_accepting_a_flagged_part_resolves_the_review_and_keeps_the_verdict():
    s = MemoryStore()
    d = record_decision(s, dec("part_review", "V05", "accept", "STR-03", reason="re-measured 7.9 mm, brushes worn"))
    p = packs(s)["V05"]
    g = part(p, "STR-03")
    assert g["verdict"] == "replace" and not g["needs_review"] and g["decided_by"] == "A. Engineer"
    assert not any("STR-03" in i for i in p["open_items"])
    assert d.context["engine_verdict"] == "replace" and d.context["drawing_no"] == "DWG-STR-03"


def test_override_changes_the_final_verdict_and_keeps_the_engines():
    s = MemoryStore()
    record_decision(s, dec("part_review", "V08", "override:replace", "ALT-08", reason="bearing noise on spin test"))
    g = part(packs(s)["V08"], "ALT-08")
    assert (g["verdict"], g["engine_verdict"], g["decision"]) == ("replace", "reuse", "override:replace")


def test_a_decided_part_no_longer_shows_as_under_review_on_the_component_line():
    s = MemoryStore()
    assert packs(s)["V05"]["components"][0]["teardown"] == "engineer_review: STR-03"
    record_decision(s, dec("part_review", "V05", "accept", "STR-03"))
    starter = next(c for c in packs(s)["V05"]["components"] if c["component"] == "starter_motor")
    assert starter["teardown"] == "graded"


def test_override_to_the_engines_own_verdict_is_refused():
    with pytest.raises(DecisionError, match="accept it instead"):
        record_decision(MemoryStore(), dec("part_review", "V08", "override:reuse", "ALT-08"))


def test_unknown_part_is_refused():
    with pytest.raises(DecisionError, match="no graded part"):
        record_decision(MemoryStore(), dec("part_review", "V09", "accept", "STR-03"))   # V09: nothing graded


# ---- harvest -----------------------------------------------------------------------------------

def test_excluding_a_part_replans_and_lowers_the_offer():
    s = MemoryStore()
    before = packs(s)["V08"]["value"]["offer"]
    d = record_decision(s, dec("harvest", "V08", "exclude", "alternator", reason="front housing cracked"))
    p = packs(s)["V08"]
    assert "alternator" not in p["plan"]["harvest"] and p["value"]["offer"] < before
    assert d.context == {"offer_before": before, "harvested_before": True}
    assert any(x["why"] == "engineer excluded" for x in p["plan"]["left_on_vehicle"])


def test_require_and_clear():
    s = MemoryStore()
    record_decision(s, dec("harvest", "V02", "require", "radiator", reason="customer order"))
    assert "radiator" in packs(s)["V02"]["plan"]["harvest"]
    record_decision(s, dec("harvest", "V02", "clear", "radiator", reason="order cancelled"))
    assert "radiator" not in packs(s)["V02"]["plan"]["harvest"]
    assert len(s.all()) == 2   # history kept


@pytest.mark.parametrize("vid, comp, msg", [
    ("V07", "alternator", "cannot follow"),      # blocked: no depollution record
    ("V09", "alternator", "cannot be harvested"),  # grade C
    ("V02", "battery", "cannot be harvested"),     # always removed
])
def test_impossible_harvest_instructions_are_refused(vid, comp, msg):
    with pytest.raises(DecisionError, match=msg):
        record_decision(MemoryStore(), dec("harvest", vid, "require", comp))


# ---- sign-off ----------------------------------------------------------------------------------

def test_sign_off_needs_nothing_open():
    with pytest.raises(DecisionError, match="open item"):
        record_decision(MemoryStore(), dec("sign_off", "V05", "sign"))


def test_sign_off_once_and_it_goes_stale_after_a_later_decision():
    s = MemoryStore()
    record_decision(s, dec("sign_off", "V01", "sign"))
    assert packs(s)["V01"]["approval"]["status"] == "signed"
    with pytest.raises(DecisionError, match="already signed"):
        record_decision(s, dec("sign_off", "V01", "sign"))
    record_decision(s, dec("harvest", "V01", "exclude", "ecu", reason="ECU water damage"))
    assert packs(s)["V01"]["approval"]["status"] == "ready"   # needs signing again


def test_reviewing_v03s_borderline_parts_makes_it_signable():
    s = MemoryStore()
    with pytest.raises(DecisionError):
        record_decision(s, dec("sign_off", "V03", "sign"))
    for p in ("ALT-03", "ALT-08"):
        record_decision(s, dec("part_review", "V03", "accept", p, reason="re-measured, within limit"))
    record_decision(s, dec("sign_off", "V03", "sign"))
    assert packs(s)["V03"]["approval"]["status"] == "signed"


def test_compliance_gaps_cannot_be_decided_away():
    s = MemoryStore()
    for p in ("STR-03", "ALT-05"):
        record_decision(s, dec("part_review", "V05", "accept", p))
    assert any("C06" in i for i in packs(s)["V05"]["open_items"])   # photos still missing
    with pytest.raises(DecisionError, match="open item"):
        record_decision(s, dec("sign_off", "V05", "sign"))


# ---- storage -------------------------------------------------------------------------------------

def test_jsonl_store_round_trips_and_appends(tmp_path):
    s = JsonlStore(tmp_path / "d.jsonl")
    a = record_decision(s, dec("part_review", "V08", "accept", "ALT-08", reason="spin test quiet"))
    b = record_decision(s, dec("sign_off", "V09", "sign"))
    got = JsonlStore(tmp_path / "d.jsonl").all()
    assert [d.id for d in got] == [a.id, b.id] and got[0].context["engine_verdict"] == "reuse"
