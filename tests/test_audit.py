import json

import pytest

from app.engines.audit import build_month, write_month
from app.engines.value import value_month


@pytest.fixture(scope="module")
def packs():
    return build_month()


def test_every_vehicle_has_a_json_safe_pack(packs, tmp_path):
    write_month(packs, tmp_path)
    assert len(packs) == 12
    for vid in packs:
        assert json.loads((tmp_path / f"{vid}.json").read_text(encoding="utf-8"))["vehicle_id"] == vid


def test_blocked_vehicles_get_the_scrap_only_offer(packs):
    for vid in ("V04", "V07"):
        p = packs[vid]
        assert p["plan"]["harvest"] == [] and p["value"]["offer"] == p["value"]["offer_scrap_only"]
        assert any("blocks dismantle" in i for i in p["open_items"])


def test_unblocked_offers_match_the_value_engine(packs):
    default = {v.vehicle_id: v.offer for v in value_month(with_grading=False)}
    for vid, p in packs.items():
        if vid not in ("V04", "V07"):
            assert p["value"]["offer"] == default[vid]


def test_open_items_drive_approval(packs):
    assert packs["V01"]["approval"]["status"] == "ready" and packs["V01"]["open_items"] == []
    assert packs["V05"]["approval"]["status"] == "pending"
    assert any("STR-03" in i for i in packs["V05"]["open_items"])


def test_grading_evidence_only_for_harvested_units(packs):
    assert packs["V09"]["grading"] == []
    assert {g["unit_type"] for g in packs["V05"]["grading"]} == {"starter", "alternator"}


def test_capacity_flows_through(packs):
    tight = build_month(capacity_minutes=300)
    assert sum(len(p["plan"]["harvest"]) for p in tight.values()) < sum(len(p["plan"]["harvest"]) for p in packs.values())
    assert any(d["why"] == "labour capacity" for p in tight.values() for d in p["plan"]["left_on_vehicle"])
