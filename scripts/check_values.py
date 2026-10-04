"""Quick sanity check of the synthetic economics (a first sketch of the value engine).

For each vehicle: what can the RVSF afford to offer the owner
  (a) scrap-only: depollute, sell battery + catalytic converter, shred the rest
  (b) with AI harvest: also pull every component whose sale value beats labour + lost scrap value
and how that compares with the informal scrapper's offer.
"""
from pathlib import Path
import pandas as pd

D = Path(__file__).resolve().parents[1] / "data"
veh = pd.read_csv(D / "vehicles.csv")
comp = pd.read_csv(D / "components.csv")
mp = pd.read_csv(D / "market_prices.csv").set_index("item").value_inr

STEEL, AL, CU = mp.steel_scrap_per_kg, mp.aluminium_scrap_per_kg, mp.copper_scrap_per_kg
SCRAP_PER_KG = {"steel": STEEL, "aluminium": AL, "steel/copper": 0.8 * STEEL + 0.2 * CU,
                "aluminium/copper": 0.7 * AL + 0.3 * CU, "electronics": 40, "plastic/glass": 5,
                "lead": 0, "steel/PGM": 0}
LABOUR = mp.labour_rate_per_hour / 60
ALWAYS = {"battery", "catalytic_converter"}  # removed in both scenarios

rows = []
for v in veh.itertuples():
    c = comp[comp.vehicle_id == v.vehicle_id].copy()
    base_metal = v.kerb_weight_kg * v.steel_fraction * STEEL + v.aluminium_kg * AL + v.copper_kg * CU
    always = c[c.component.isin(ALWAYS)].sale_value_inr.sum()
    c["net"] = c.sale_value_inr - c.dismantle_minutes * LABOUR - c.weight_kg * c.material.map(SCRAP_PER_KG)
    pick = c[~c.component.isin(ALWAYS) & (c.condition_grade.isin(["A", "B"])) & (c.net > 0)]
    harvest_gain = pick.net.sum()

    def offer(revenue):
        return revenue - mp.processing_cost_per_vehicle - revenue * mp.target_margin_pct / 100

    rev_scrap = base_metal + always + mp.epr_certificate_per_vehicle
    rev_harv = rev_scrap + harvest_gain
    rows.append(dict(vehicle=v.vehicle_id, segment=v.segment, informal=v.informal_offer_inr,
                     offer_scrap_only=round(offer(rev_scrap)), offer_with_harvest=round(offer(rev_harv)),
                     parts_pulled=len(pick), story=str(v.demo_story if isinstance(v.demo_story, str) else "")[:45]))
r = pd.DataFrame(rows)
r["gap_before"] = r.informal - r.offer_scrap_only
r["gap_after"] = r.informal - r.offer_with_harvest
r["gap_closed_pct"] = (100 * (r.gap_before - r.gap_after) / r.gap_before).round()
pd.set_option("display.width", 200)
print(r.to_string(index=False))
print("\nAverage gap before: INR", round(r.gap_before.mean()), " after:", round(r.gap_after.mean()),
      " closed:", round(100 * (1 - r.gap_after.mean() / r.gap_before.mean())), "%")
