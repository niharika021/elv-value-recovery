import pandas as pd
import pytest

from app.engines.value import (PricingError, load_carbon, load_prices, month_table, price_components,
                               value_month, value_vehicle)
from app.engines.value import DATA

VEH = pd.read_csv(DATA / "vehicles.csv")
COMP = pd.read_csv(DATA / "components.csv")
PRICES, CARBON = load_prices(), load_carbon()

# Output of scripts/check_values.py (Day 1 sketch): (offer scrap-only, offer with harvest, parts pulled)
SKETCH = {
    "V01": (17455, 24895, 6), "V02": (27470, 36349, 6), "V03": (28333, 35052, 6), "V04": (20873, 24767, 5),
    "V05": (32250, 41984, 7), "V06": (18993, 20702, 3), "V07": (26465, 29442, 3), "V08": (35425, 43944, 6),
    "V09": (18395, 18395, 0), "V10": (17831, 26980, 6), "V11": (19484, 25393, 6), "V12": (31536, 34523, 4),
}


def vehicle(vid):
    return next(VEH[VEH.vehicle_id == vid].itertuples(index=False))


def value(vid, harvest=None):
    return value_vehicle(vehicle(vid), COMP[COMP.vehicle_id == vid], PRICES, CARBON, harvest)


@pytest.fixture(scope="module")
def month():
    return {v.vehicle_id: v for v in value_month()}


# ---- reproduces the agreed Day 1 economics ---------------------------------------------

@pytest.mark.parametrize("vid", SKETCH)
def test_matches_the_sketch(month, vid):
    v = month[vid]
    assert (v.offer_scrap_only, v.offer, len(v.harvest)) == SKETCH[vid]


def test_month_averages_match_the_readme(month):
    t = month_table(list(month.values()))
    before = (t.informal - t.offer_scrap_only).mean()
    assert round(before) == 14666 and round(t.gap.mean()) == 9006
    assert round(100 * (1 - t.gap.mean() / before)) == 39


def test_offer_adds_up(month):
    for v in month.values():
        assert abs(v.revenue - (v.metal_value + v.always_removed_value + v.epr + v.harvest_gain)) <= 2
        assert abs(v.offer - (v.revenue - v.processing - v.margin)) <= 2


# ---- any harvest set can be priced ----------------------------------------------------

def test_empty_harvest_is_scrap_only():
    v = value("V02", harvest=[])
    assert v.offer == v.offer_scrap_only == SKETCH["V02"][0] and v.harvest_gain == 0


def test_harvest_order_does_not_matter():
    assert value("V02", ["ecu", "alternator"]).offer == value("V02", ["alternator", "ecu"]).offer


def test_positive_net_part_raises_offer_negative_lowers_it():
    base = value("V02", ["ecu"]).offer
    assert value("V02", ["ecu", "ac_compressor"]).offer > base
    assert value("V02", ["ecu", "radiator"]).offer < base       # V02 radiator: grade B, net -50


@pytest.mark.parametrize("vid, part", [
    ("V09", "alternator"),             # grade C
    ("V10", "catalytic_converter"),    # missing
    ("V02", "battery"),                # always removed, not a harvest choice
    ("V02", "spoiler"),                # not on the vehicle
])
def test_cannot_harvest_what_is_not_available(vid, part):
    with pytest.raises(PricingError):
        value(vid, [part])


def test_duplicate_harvest_is_rejected():
    with pytest.raises(PricingError):
        value("V02", ["ecu", "ecu"])


def test_missing_price_item_is_rejected():
    market = pd.read_csv(DATA / "market_prices.csv")
    with pytest.raises(PricingError):
        load_prices(market[market.item != "labour_rate_per_hour"])


def test_unknown_material_is_rejected():
    comp = COMP[COMP.vehicle_id == "V01"].copy()
    comp.loc[comp.index[0], "material"] = "unobtainium"
    with pytest.raises(PricingError):
        price_components(comp, PRICES)


# ---- EPR steel and CO2 -----------------------------------------------------------------

def test_steel_to_recycler_drops_by_steel_in_harvested_parts():
    v = vehicle("V02")
    body = v.kerb_weight_kg * v.steel_fraction
    assert value("V02", []).steel_to_recycler_kg == round(body, 1)
    assert value("V02", ["front_doors_pair"]).steel_to_recycler_kg == round(body - 32.0, 1)      # steel
    assert value("V02", ["starter_motor"]).steel_to_recycler_kg == round(body - 3.5 * 0.8, 1)    # steel/copper
    assert value("V02", ["ecu"]).steel_to_recycler_kg == round(body, 1)                           # electronics


def test_co2_counts_reused_parts_only():
    assert value("V02", []).co2_avoided_kg == 0
    # alternator: 5 kg aluminium/copper, 10 kgCO2e/kg new, reuse carries 12% -> 44 kg avoided
    assert value("V02", ["alternator"]).co2_avoided_kg == 44.0


# ---- planted stories -------------------------------------------------------------------

def test_v03_converter_is_about_half_the_steel_value(month):
    v = month["V03"]
    cat = v.lines.set_index("component").loc["catalytic_converter", "sale_value"]
    assert 0.4 < cat / (v.steel_kg * PRICES.steel) < 0.6


def test_v10_missing_converter_is_the_biggest_gap(month):
    assert month["V10"].lines.set_index("component").loc["catalytic_converter", "status"] == "missing"
    before = {k: v.informal_offer - v.offer_scrap_only for k, v in month.items()}
    assert max(before, key=before.get) == "V10"


def test_v09_flood_car_harvests_nothing(month):
    assert month["V09"].harvest == () and month["V09"].co2_avoided_kg == 0


def test_v06_front_end_parts_lost(month):
    lines = month["V06"].lines.set_index("component")
    for c in ("radiator", "headlamps_pair", "front_doors_pair", "ac_compressor"):
        assert lines.loc[c, "status"] == "not_harvestable" and not lines.loc[c, "harvested"]


def test_v02_regulator_is_perfect_and_in_demand(month):
    alt = month["V02"].lines.set_index("component").loc["alternator"]
    assert "ALT-06 (60/mo, 90d new, 100% margin)" in alt.reusable_high_demand


def test_teardown_review_reaches_the_value_lines(month):
    assert month["V05"].lines.set_index("component").loc["starter_motor", "teardown"] == "engineer_review: STR-03"
    assert month["V04"].lines.set_index("component").loc["alternator", "teardown"] == "not inspected"  # grade C


def test_a_plan_missing_a_vehicle_is_refused():
    with pytest.raises(PricingError):
        value_month({"V01": ["ecu"]}, with_grading=False)
