"""Value engine: what an RVSF can offer for a vehicle, for a given set of harvested components.

Prices any harvest decision. By default it uses the rule from scripts/check_values.py (pull every
A/B component whose sale value beats labour + the scrap value it takes out of the shredder), and
reproduces that sketch's offers exactly. The Day 5 harvest planner will choose the set instead.

Per vehicle it reports the offer and its breakdown, the gap to the informal scrapper, the steel
sent to the recycler (weighbridge basis for the EPR certificate) and the CO2 avoided by reuse.

Run:  python -m app.engines.value          -> the synthetic month
      python -m app.engines.value V03      -> one vehicle, line by line
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"

ALWAYS_REMOVED = ("battery", "catalytic_converter")  # depollution / PGM recycler, in every scenario
HARVEST_GRADES = ("A", "B")
UNIT_OF = {"starter_motor": "starter", "alternator": "alternator"}  # components with a teardown grade

# What a kg of each material is worth in the shredder stream, as shares of the three metal prices
# plus a flat INR/kg for the rest. Same figures as scripts/check_values.py. The steel share also
# says how much steel a harvested part takes off the weighbridge.
COMPOSITION = {
    "steel":            dict(steel=1.0),
    "aluminium":        dict(aluminium=1.0),
    "steel/copper":     dict(steel=0.8, copper=0.2),
    "aluminium/copper": dict(aluminium=0.7, copper=0.3),
    "electronics":      dict(flat=40),
    "plastic/glass":    dict(flat=5),
    "lead":             dict(),  # battery: sold for lead, counted in its sale value
    "steel/PGM":        dict(),  # converter: sold to the PGM recycler, counted in its sale value
}

PRICE_ITEMS = ("steel_scrap_per_kg", "aluminium_scrap_per_kg", "copper_scrap_per_kg",
               "epr_certificate_per_vehicle", "processing_cost_per_vehicle", "labour_rate_per_hour",
               "target_margin_pct")


class PricingError(ValueError):
    """Bad input to the value engine: never price around it."""


@dataclass(frozen=True)
class Prices:
    steel: float
    aluminium: float
    copper: float
    epr: float
    processing: float
    labour_per_hour: float
    margin_pct: float

    def scrap_per_kg(self, material: str) -> float:
        if material not in COMPOSITION:
            raise PricingError(f"No scrap composition for material {material!r}")
        c = COMPOSITION[material]
        return (c.get("steel", 0) * self.steel + c.get("aluminium", 0) * self.aluminium
                + c.get("copper", 0) * self.copper + c.get("flat", 0))

    def offer(self, revenue: float) -> float:
        return revenue - self.processing - revenue * self.margin_pct / 100


def load_prices(market: pd.DataFrame | None = None) -> Prices:
    market = pd.read_csv(DATA / "market_prices.csv") if market is None else market
    v = market.set_index("item").value_inr
    missing = [i for i in PRICE_ITEMS if i not in v.index]
    if missing:
        raise PricingError(f"market_prices is missing {missing}")
    return Prices(v.steel_scrap_per_kg, v.aluminium_scrap_per_kg, v.copper_scrap_per_kg,
                  v.epr_certificate_per_vehicle, v.processing_cost_per_vehicle, v.labour_rate_per_hour,
                  v.target_margin_pct)


def load_carbon(carbon: pd.DataFrame | None = None) -> dict[str, float]:
    """kgCO2e avoided per kg reused, by material.

    reuse_share_of_new is read as: a reused part still carries this share of a new part's
    footprint (testing, cleaning, transport), so reuse avoids (1 - share). To be confirmed.
    """
    carbon = pd.read_csv(DATA / "carbon_factors.csv") if carbon is None else carbon
    return {r.material: r.kgco2e_per_kg_new * (1 - r.reuse_share_of_new) for r in carbon.itertuples()}


def price_components(comp: pd.DataFrame, prices: Prices) -> pd.DataFrame:
    """One line per component: sale value, labour, scrap value lost, net, and whether it may be harvested."""
    rows = []
    for c in comp.itertuples(index=False):
        labour = c.dismantle_minutes * prices.labour_per_hour / 60
        scrap_lost = c.weight_kg * prices.scrap_per_kg(c.material)
        net = c.sale_value_inr - labour - scrap_lost
        if c.component in ALWAYS_REMOVED:
            labour, net = 0.0, c.sale_value_inr  # removal is depollution, already in the processing cost
            status = "missing" if c.condition_grade == "missing" else "always_removed"
            why = ("not on the vehicle at intake" if status == "missing"
                   else "removed in every scenario; labour is in the processing cost")
        elif c.condition_grade not in HARVEST_GRADES:
            status, why = "not_harvestable", f"grade {c.condition_grade}: no resale, stays in scrap stream"
        elif net <= 0:
            status, why = "not_worth_it", f"sale {c.sale_value_inr:.0f} < labour {labour:.0f} + scrap lost {scrap_lost:.0f}"
        else:
            status, why = "harvestable", f"net +{net:.0f} after labour {labour:.0f} and scrap lost {scrap_lost:.0f}"
        rows.append(dict(component=c.component, grade=c.condition_grade, material=c.material,
                         weight_kg=c.weight_kg, minutes=c.dismantle_minutes, sale_value=c.sale_value_inr,
                         labour=round(labour, 2), scrap_lost=round(scrap_lost, 2), net=round(net, 2),
                         status=status, why=why))
    return pd.DataFrame(rows)


@dataclass(frozen=True)
class VehicleValue:
    vehicle_id: str
    informal_offer: float
    steel_kg: float            # body steel before harvest
    metal_value: float         # steel + aluminium + copper in the shredder stream
    always_removed_value: float
    epr: float
    harvest: tuple[str, ...]
    harvest_gain: float        # sale value of harvested parts, net of labour and scrap value lost
    harvest_minutes: float
    revenue: float
    processing: float
    margin: float
    offer: float
    offer_scrap_only: float
    steel_to_recycler_kg: float  # weighbridge steel: body steel minus steel leaving in harvested parts
    co2_avoided_kg: float
    lines: pd.DataFrame = field(repr=False, compare=False)

    @property
    def gap(self) -> float:
        return self.informal_offer - self.offer

    @property
    def gap_closed_pct(self) -> float:
        before = self.informal_offer - self.offer_scrap_only
        return 100 * (before - self.gap) / before if before > 0 else 0.0


def default_harvest(lines: pd.DataFrame) -> tuple[str, ...]:
    """The check_values.py rule: every harvestable component with positive net value."""
    return tuple(lines.loc[lines.status == "harvestable", "component"])


def value_vehicle(vehicle, comp: pd.DataFrame, prices: Prices, carbon: dict[str, float],
                  harvest: tuple[str, ...] | list[str] | None = None) -> VehicleValue:
    """Price one vehicle for a harvest set (None = default rule). Grade C, missing or
    always-removed components cannot be harvested; asking for one is an error."""
    lines = price_components(comp, prices)
    harvest = default_harvest(lines) if harvest is None else tuple(harvest)
    allowed = set(lines.loc[lines.status.isin(["harvestable", "not_worth_it"]), "component"])
    bad = [h for h in harvest if h not in allowed]
    if bad:
        raise PricingError(f"{vehicle.vehicle_id}: cannot harvest {bad} "
                          f"({', '.join(lines.set_index('component').status.reindex(bad).fillna('unknown'))})")
    if len(set(harvest)) != len(harvest):
        raise PricingError(f"{vehicle.vehicle_id}: duplicate components in harvest {harvest}")

    lines["harvested"] = lines.component.isin(harvest)
    picked = lines[lines.harvested]

    steel_kg = vehicle.kerb_weight_kg * vehicle.steel_fraction
    metal = steel_kg * prices.steel + vehicle.aluminium_kg * prices.aluminium + vehicle.copper_kg * prices.copper
    always = lines.loc[lines.status == "always_removed", "sale_value"].sum()
    base = metal + always + prices.epr
    gain = picked.net.sum()
    revenue = base + gain

    steel_out = sum(p.weight_kg * COMPOSITION[p.material].get("steel", 0) for p in picked.itertuples())
    co2 = sum(p.weight_kg * carbon[p.material] for p in picked.itertuples())

    return VehicleValue(
        vehicle_id=vehicle.vehicle_id, informal_offer=vehicle.informal_offer_inr,
        steel_kg=round(steel_kg, 1), metal_value=round(metal), always_removed_value=round(always),
        epr=prices.epr, harvest=harvest, harvest_gain=round(gain), harvest_minutes=picked.minutes.sum(),
        revenue=round(revenue), processing=prices.processing, margin=round(revenue * prices.margin_pct / 100),
        offer=round(prices.offer(revenue)), offer_scrap_only=round(prices.offer(base)),
        steel_to_recycler_kg=round(steel_kg - steel_out, 1), co2_avoided_kg=round(co2, 1), lines=lines,
    )


def attach_grading(lines: pd.DataFrame, vehicle_id: str, units: pd.DataFrame, grades: pd.DataFrame,
                   part_market: pd.DataFrame) -> pd.DataFrame:
    """Annotate starter / alternator lines with their teardown status. Information only: prices do not change."""
    lines = lines.copy()
    demand = part_market.set_index("part_no")
    status, high_demand = [], []
    for c in lines.component:
        unit = UNIT_OF.get(c)
        u = units[(units.vehicle_id == vehicle_id) & (units.unit_type == unit)] if unit else units.iloc[0:0]
        if not unit or u.empty:
            status.append("" if not unit else "not inspected")
            high_demand.append("")
            continue
        u = u.iloc[0]
        status.append(u.status if u.status == "graded" else f"engineer_review: {u.review}")
        g = grades[(grades.vehicle_id == vehicle_id) & (grades.unit_type == unit) & (grades.verdict == "reuse")]
        hd = g[g.part_no.isin(demand.index)]
        high_demand.append(" ".join(
            f"{p.part_no} ({demand.loc[p.part_no, 'demand_per_month']}/mo, {demand.loc[p.part_no, 'new_lead_time_days']}d new"
            + (f", {p.margin:.0%} margin)" if pd.notna(p.margin) else ")") for p in hd.itertuples()))
    lines["teardown"] = status
    lines["reusable_high_demand"] = high_demand
    return lines


def value_month(harvests: dict[str, list[str]] | None = None, with_grading: bool = True,
                grades: pd.DataFrame | None = None) -> list[VehicleValue]:
    """Value every vehicle in the synthetic month. harvests=None uses the default rule; a harvests
    dict must name every vehicle, so a vehicle missing from a plan is never silently re-planned."""
    veh = pd.read_csv(DATA / "vehicles.csv")
    if harvests is not None and set(veh.vehicle_id) - set(harvests):
        raise PricingError(f"Harvest plan has no entry for {sorted(set(veh.vehicle_id) - set(harvests))}")
    comp = pd.read_csv(DATA / "components.csv")
    prices, carbon = load_prices(), load_carbon()
    if with_grading:
        from app.engines.grading import grade_inspections, summarise_units
        grades = grade_inspections() if grades is None else grades   # pass decided grades to show reviews resolved
        units, pm = summarise_units(grades), pd.read_csv(DATA / "part_market.csv")
    out = []
    for v in veh.itertuples(index=False):
        vv = value_vehicle(v, comp[comp.vehicle_id == v.vehicle_id], prices, carbon,
                           None if harvests is None else harvests[v.vehicle_id])
        if with_grading:
            vv = replace(vv, lines=attach_grading(vv.lines, v.vehicle_id, units, grades, pm))
        out.append(vv)
    return out


def month_table(values: list[VehicleValue]) -> pd.DataFrame:
    return pd.DataFrame([dict(
        vehicle=v.vehicle_id, informal=v.informal_offer, offer_scrap_only=v.offer_scrap_only, offer=v.offer,
        parts=len(v.harvest), minutes=v.harvest_minutes, gap=v.gap, gap_closed_pct=round(v.gap_closed_pct),
        steel_to_recycler_kg=v.steel_to_recycler_kg, co2_avoided_kg=v.co2_avoided_kg,
    ) for v in values])


if __name__ == "__main__":
    pd.set_option("display.width", 220, "display.max_colwidth", 70)
    values = value_month()
    if len(sys.argv) > 1:
        v = next(x for x in values if x.vehicle_id == sys.argv[1].upper())
        print(v.lines.drop(columns=["material", "weight_kg"]).to_string(index=False))
        print(f"\n{v.vehicle_id}: metal {v.metal_value:,.0f} + always removed {v.always_removed_value:,.0f} "
              f"+ EPR {v.epr:,.0f} + harvest {v.harvest_gain:,.0f} = revenue {v.revenue:,.0f}; "
              f"- processing {v.processing:,.0f} - margin {v.margin:,.0f} = offer {v.offer:,.0f} "
              f"(informal {v.informal_offer:,.0f}, scrap-only {v.offer_scrap_only:,.0f})")
    else:
        t = month_table(values)
        print(t.to_string(index=False))
        before = (t.informal - t.offer_scrap_only).mean()
        print(f"\nAverage gap before: INR {before:,.0f}  after: {t.gap.mean():,.0f}  "
              f"closed: {100 * (1 - t.gap.mean() / before):.0f} %   "
              f"steel to recycler: {t.steel_to_recycler_kg.sum():,.0f} kg   CO2 avoided: {t.co2_avoided_kg.sum():,.0f} kg")
