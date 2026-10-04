"""
Synthetic dataset for the ELV Value Recovery Planner (MECA Queens, AI Builder Cup 2026).

Everything here is INVENTED for a hackathon demo. No real company, brand, vehicle model,
drawing or price list is used. Two public anchors only (NITI Aayog, Jan 2026):
  - informal scrappers pay ~60-65% more, a gap of ~INR 15,000 per mid-range vehicle
  - EPR certificate value ~INR 5,500 per vehicle processed

Run:  python scripts/generate_data.py      -> writes CSVs into data/
The script is deterministic (fixed seed) so every teammate gets the same data.
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data"
OUT.mkdir(exist_ok=True)
rng = np.random.default_rng(42)

# --------------------------------------------------------------------------------------
# 1. Vehicles arriving at the RVSF (one synthetic month, October 2026)
# --------------------------------------------------------------------------------------
SEG = {  # generic segments only, no brands
    "hatchback": dict(code="HB", kerb=(850, 960), informal=(31000, 35000)),
    "sedan": dict(code="SD", kerb=(1080, 1200), informal=(38000, 42000)),
    "suv": dict(code="SV", kerb=(1350, 1500), informal=(46000, 50000)),
}
plan = [  # (segment, model_year, condition, story)
    ("hatchback", 2007, "running, worn", ""),
    ("sedan", 2008, "running, worn", "high-demand regulator on alternator"),
    ("sedan", 2006, "non-running, intact", "catalytic converter worth ~half the steel value"),
    ("hatchback", 2005, "non-running, intact", ""),
    ("suv", 2009, "running, worn", "starter brushes below drawing minimum, note says looks ok"),
    ("hatchback", 2008, "accident, front damage", "front-end parts lost; harvest rear only"),
    ("sedan", 2007, "non-running, intact", "COMPLIANCE RED: no depollution record"),
    ("suv", 2010, "running, worn", "borderline alternator bearing: engineer override demo"),
    ("hatchback", 2006, "flood damaged, heavy rust", "harvest not worth the labour"),
    ("sedan", 2009, "running, worn", "catalytic converter missing (removed before intake)"),
    ("hatchback", 2011, "non-running, intact", "DATA QUALITY: model code mislabelled, photos missing"),
    ("suv", 2008, "non-running, intact", ""),
]
veh_rows = []
for i, (seg, yr, cond, story) in enumerate(plan, start=1):
    s = SEG[seg]
    kerb = int(rng.integers(*s["kerb"]))
    model_code = f"{s['code']}-{int(rng.integers(10, 30))}"
    if i == 11:
        model_code = "SV-14"  # mislabelled: a hatchback carrying an SUV model code
    veh_rows.append(dict(
        vehicle_id=f"V{i:02d}",
        intake_date=f"2026-10-{int(rng.integers(1, 28)):02d}",
        segment=seg,
        model_code=model_code,
        fuel="petrol" if rng.random() < 0.7 else "diesel",
        model_year=yr,
        kerb_weight_kg=kerb,
        steel_fraction=round(float(rng.uniform(0.62, 0.68)), 3),
        aluminium_kg=round(float(rng.uniform(35, 70)) * kerb / 1100, 1),
        copper_kg=round(float(rng.uniform(9, 16)) * kerb / 1100, 1),
        condition=cond,
        dereg_status="deregistered" if i != 4 else "pending",
        informal_offer_inr=int(round(rng.integers(*s["informal"]) / 500) * 500),
        demo_story=story,
    ))
vehicles = pd.DataFrame(veh_rows)

# --------------------------------------------------------------------------------------
# 2. Harvestable components per vehicle (RVSF-level decision)
# --------------------------------------------------------------------------------------
# value_a / value_b = sale value as Grade A / Grade B core or used part (INR)
# grade C = no resale; the part stays in the scrap stream
COMP = {
    "starter_motor":       dict(weight=3.5, minutes=25, a=2200, b=1200, material="steel/copper"),
    "alternator":          dict(weight=5.0, minutes=20, a=2600, b=1400, material="aluminium/copper"),
    "ac_compressor":       dict(weight=6.0, minutes=35, a=3500, b=1800, material="aluminium"),
    "catalytic_converter": dict(weight=4.5, minutes=30, a=None, b=None, material="steel/PGM"),
    "ecu":                 dict(weight=0.6, minutes=10, a=1800, b=600, material="electronics"),
    "radiator":            dict(weight=3.0, minutes=20, a=900, b=400, material="aluminium"),
    "front_doors_pair":    dict(weight=32.0, minutes=30, a=3000, b=1500, material="steel"),
    "headlamps_pair":      dict(weight=3.0, minutes=12, a=1600, b=700, material="plastic/glass"),
    "battery":             dict(weight=12.0, minutes=8, a=1200, b=1200, material="lead"),
}
CAT_PGM = {"hatchback": (4000, 5500), "sedan": (6000, 9500), "suv": (7000, 10000)}

def grade_for(vid, comp, cond):
    """Pick a condition grade, with planted stories."""
    if comp == "battery":
        return "A"  # battery is always removed (depollution) and sold for lead
    if vid == "V09":  # flood + rust: almost nothing worth pulling
        return "C" if comp not in ("catalytic_converter",) else "A"
    if vid == "V06" and comp in ("radiator", "headlamps_pair", "front_doors_pair", "ac_compressor"):
        return "C"  # front-end accident damage
    if cond.startswith("running"):
        return rng.choice(["A", "A", "B"])
    return rng.choice(["A", "B", "B", "C"])

comp_rows = []
for v in veh_rows:
    for comp, c in COMP.items():
        g = grade_for(v["vehicle_id"], comp, v["condition"])
        if comp == "catalytic_converter":
            lo, hi = CAT_PGM[v["segment"]]
            val = int(rng.integers(lo, hi) // 100 * 100)
            if v["vehicle_id"] == "V03":
                val = 9800  # planted: very valuable converter
            present = not (v["vehicle_id"] == "V10")  # V10: converter missing (stolen before intake)
            comp_rows.append(dict(vehicle_id=v["vehicle_id"], component=comp,
                                  condition_grade="A" if present else "missing",
                                  sale_value_inr=val if present else 0,
                                  weight_kg=c["weight"], dismantle_minutes=c["minutes"],
                                  material=c["material"]))
            continue
        val = c["a"] if g == "A" else c["b"] if g == "B" else 0
        comp_rows.append(dict(vehicle_id=v["vehicle_id"], component=comp, condition_grade=g,
                              sale_value_inr=val, weight_kg=c["weight"],
                              dismantle_minutes=c["minutes"], material=c["material"]))
components = pd.DataFrame(comp_rows)

# --------------------------------------------------------------------------------------
# 3. Starter / alternator bill of materials + reference grading limits (from our drawings)
# --------------------------------------------------------------------------------------
# limit_type: min | max | range | pass_fail | scale_max
BOM = [
    # unit, part_no, part_name, material, kg, critical, measure, unit, nominal, limit_type, lim1, lim2, fail_verdict
    ("starter", "STR-01", "Drive-end housing", "die-cast aluminium", 0.45, "Y", "crack_check", "-", None, "pass_fail", None, None, "scrap"),
    ("starter", "STR-02", "Armature (commutator)", "steel/copper", 0.90, "Y", "commutator_diameter", "mm", 32.0, "min", 31.2, None, "scrap"),
    ("starter", "STR-03", "Carbon brush set", "carbon/copper", 0.05, "N", "brush_length", "mm", 14.0, "min", 8.5, None, "replace"),
    ("starter", "STR-04", "Field frame", "steel", 0.85, "Y", "corrosion_level", "0-3", 0, "scale_max", 1, None, "refurbish"),
    ("starter", "STR-05", "Solenoid switch", "steel/copper", 0.40, "Y", "pull_in_coil_resistance", "ohm", 0.40, "range", 0.30, 0.50, "replace"),
    ("starter", "STR-06", "Pinion and overrunning clutch", "steel", 0.30, "Y", "pinion_tooth_wear", "mm", 0.0, "max", 0.30, None, "replace"),
    ("starter", "STR-07", "Planetary gear set", "steel", 0.25, "Y", "gear_backlash", "mm", 0.10, "max", 0.25, None, "replace"),
    ("starter", "STR-08", "Armature bushings", "sintered bronze", 0.02, "N", "radial_play", "mm", 0.05, "max", 0.15, None, "replace"),
    ("starter", "STR-09", "Brush holder plate", "phenolic/steel", 0.10, "N", "crack_check", "-", None, "pass_fail", None, None, "replace"),
    ("starter", "STR-10", "Commutator-end cover", "steel", 0.15, "N", "corrosion_level", "0-3", 0, "scale_max", 2, None, "refurbish"),
    ("alternator", "ALT-01", "Front housing", "die-cast aluminium", 0.70, "Y", "crack_check", "-", None, "pass_fail", None, None, "scrap"),
    ("alternator", "ALT-02", "Rear housing", "die-cast aluminium", 0.60, "Y", "crack_check", "-", None, "pass_fail", None, None, "scrap"),
    ("alternator", "ALT-03", "Rotor (slip rings)", "steel/copper", 1.10, "Y", "slip_ring_diameter", "mm", 14.4, "min", 14.0, None, "scrap"),
    ("alternator", "ALT-04", "Stator winding", "steel/copper", 1.20, "Y", "insulation_test", "-", None, "pass_fail", None, None, "scrap"),
    ("alternator", "ALT-05", "Carbon brushes", "carbon/copper", 0.03, "N", "exposed_brush_length", "mm", 10.5, "min", 4.5, None, "replace"),
    ("alternator", "ALT-06", "Voltage regulator", "electronics", 0.08, "Y", "regulated_voltage", "V", 14.5, "range", 14.2, 14.8, "replace"),
    ("alternator", "ALT-07", "Rectifier bridge", "electronics", 0.15, "Y", "diode_test", "-", None, "pass_fail", None, None, "replace"),
    ("alternator", "ALT-08", "Drive-end bearing", "bearing steel", 0.10, "Y", "radial_play", "mm", 0.02, "max", 0.10, None, "replace"),
    ("alternator", "ALT-09", "Pulley / OAP clutch", "steel", 0.35, "N", "groove_wear", "mm", 0.0, "max", 0.40, None, "replace"),
    ("alternator", "ALT-10", "Slip-ring-end bearing", "bearing steel", 0.05, "Y", "radial_play", "mm", 0.02, "max", 0.10, None, "replace"),
]
bom_cols = ["unit_type", "part_no", "part_name", "material", "weight_kg", "critical", "measure", "unit",
            "nominal", "limit_type", "limit_1", "limit_2", "verdict_if_fail"]
bom = pd.DataFrame(BOM, columns=bom_cols)
bom["drawing_no"] = "DWG-" + bom["part_no"]
# Reference rules = the ground truth Gemini's drawing extraction should reproduce
grading_rules_reference = bom[["part_no", "measure", "unit", "limit_type", "limit_1", "limit_2",
                               "verdict_if_fail", "drawing_no"]].copy()
grading_rules_reference["source"] = "drawing"
bom_public = bom.drop(columns=["limit_type", "limit_1", "limit_2", "verdict_if_fail"])  # limits live on drawings only

# --------------------------------------------------------------------------------------
# 4. Teardown inspections for starter + alternator parts
# --------------------------------------------------------------------------------------
NOTES_OK = ["clean, normal wear", "looks ok", "light wear", "within spec by eye", "good condition"]
NOTES_BAD = ["heavy wear visible", "scoring on surface", "discoloured from heat", "pitting", "worn unevenly"]

def measure(row, vid, wear_bias):
    """Return (measured_value, crack, corrosion, note)."""
    lt, nom, l1, l2 = row.limit_type, row.nominal, row.limit_1, row.limit_2
    corrosion = int(min(3, max(0, rng.normal(0.8 + wear_bias, 0.7))))
    crack = "N"
    note = rng.choice(NOTES_OK)
    val = ""
    if lt == "min":
        span = nom - l1
        val = round(nom - span * float(rng.uniform(0.2, 0.95 + wear_bias)), 2)
    elif lt == "max":
        val = round(nom + (l1 - nom) * float(rng.uniform(0.1, 0.9 + wear_bias)), 3)
    elif lt == "range":
        mid, half = (l1 + l2) / 2, (l2 - l1) / 2
        val = round(mid + half * float(rng.uniform(-0.9 - wear_bias, 0.9 + wear_bias)), 2)
    elif lt == "pass_fail":
        fail = rng.random() < 0.08 + wear_bias * 0.3
        val = "fail" if fail else "pass"
        if row.measure == "crack_check" and fail:
            crack, note = "Y", "hairline crack near mounting boss"
    elif lt == "scale_max":
        val = corrosion
    if val != "" and lt in ("min", "max", "range"):
        bad = (lt == "min" and val < l1) or (lt == "max" and val > l1) or (lt == "range" and not (l1 <= val <= l2))
        if bad:
            note = rng.choice(NOTES_BAD)
    return val, crack, corrosion, note

ins_rows = []
for v in veh_rows:
    vid = v["vehicle_id"]
    for unit, comp in (("starter", "starter_motor"), ("alternator", "alternator")):
        grade = components.query("vehicle_id == @vid and component == @comp").condition_grade.iloc[0]
        if grade == "C":
            continue  # not harvested, not inspected
        wear_bias = 0.15 if grade == "B" else 0.0
        if v["condition"].startswith("running"):
            wear_bias += 0.05
        for row in bom[bom.unit_type == unit].itertuples():
            val, crack, corr, note = measure(row, vid, wear_bias)
            # ---- planted stories ----
            if vid == "V05" and row.part_no == "STR-03":
                val, note = 7.9, "looks ok, brushes clean"          # below 8.5 min, note misleads
            if vid == "V08" and row.part_no == "ALT-08":
                val, note = 0.095, "slight noise when spun by hand"  # within 0.10 limit -> engineer override
            if vid == "V02" and row.part_no == "ALT-06":
                val, note = 14.5, "regulator tests perfect"         # high-demand part, keep
            photo = f"photos/{vid}_{row.part_no}.jpg"
            if vid == "V11" or rng.random() < 0.06:
                photo = ""  # missing photos
            ins_rows.append(dict(vehicle_id=vid, unit_type=unit, part_no=row.part_no,
                                 measure=row.measure, measured_value=val, crack=crack,
                                 corrosion_level=corr, inspector_note=note, photo_uri=photo,
                                 inspector="INSP-" + str(int(rng.integers(1, 4)))))
inspections = pd.DataFrame(ins_rows)

# --------------------------------------------------------------------------------------
# 5. Market prices, costs and the two public anchors
# --------------------------------------------------------------------------------------
market = pd.DataFrame([
    dict(item="steel_scrap_per_kg", value_inr=28, note="shredded ELV steel, net of yield loss; synthetic"),
    dict(item="aluminium_scrap_per_kg", value_inr=110, note="mixed cast aluminium; synthetic"),
    dict(item="copper_scrap_per_kg", value_inr=220, note="insulated wiring harness, per kg of harness; synthetic"),
    dict(item="epr_certificate_per_vehicle", value_inr=5500, note="NITI Aayog Jan 2026 estimate"),
    dict(item="informal_price_gap_midrange", value_inr=15000, note="NITI Aayog Jan 2026 estimate"),
    dict(item="processing_cost_per_vehicle", value_inr=13000, note="depollution, compliance, admin, logistics, capex amortisation; synthetic"),
    dict(item="labour_rate_per_hour", value_inr=360, note="dismantling technician; synthetic"),
    dict(item="target_margin_pct", value_inr=10, note="RVSF margin on revenue; synthetic"),
])
part_market = pd.DataFrame([
    # component-level demand and lead time for a NEW replacement part (drives harvest priority)
    dict(part_no="ALT-06", part_name="Voltage regulator", new_price_inr=2400, refurb_cost_inr=0, demand_per_month=60, new_lead_time_days=90),
    dict(part_no="STR-05", part_name="Solenoid switch", new_price_inr=1500, refurb_cost_inr=150, demand_per_month=45, new_lead_time_days=30),
    dict(part_no="STR-02", part_name="Armature", new_price_inr=1900, refurb_cost_inr=300, demand_per_month=25, new_lead_time_days=45),
    dict(part_no="ALT-03", part_name="Rotor", new_price_inr=2100, refurb_cost_inr=350, demand_per_month=20, new_lead_time_days=45),
    dict(part_no="ALT-04", part_name="Stator", new_price_inr=1700, refurb_cost_inr=250, demand_per_month=18, new_lead_time_days=40),
    dict(part_no="ALT-01", part_name="Front housing", new_price_inr=900, refurb_cost_inr=120, demand_per_month=15, new_lead_time_days=60),
    dict(part_no="STR-01", part_name="Drive-end housing", new_price_inr=700, refurb_cost_inr=100, demand_per_month=15, new_lead_time_days=60),
])

# --------------------------------------------------------------------------------------
# 6. Compliance rule pack + per-vehicle evidence
#     Summaries for a DEMO rule pack. Not legal text. Verify before any real use.
# --------------------------------------------------------------------------------------
compliance_rules = pd.DataFrame([
    dict(rule_id="C01", check="Depollution completed before dismantling (fuel, oils, coolant, refrigerant, battery, airbags)",
         evidence_field="depollution_record_id", severity="red", source="Environment Protection (End-of-Life Vehicles) Rules, 2025; RVSF operating norms"),
    dict(rule_id="C02", check="Certificate of Deposit issued and vehicle deregistered before dismantling",
         evidence_field="certificate_of_deposit_no", severity="red", source="Motor Vehicles (Registration and Functions of Vehicle Scrapping Facility) Rules, 2021"),
    dict(rule_id="C03", check="Weighbridge record of steel sent for recycling (basis for EPR certificate)",
         evidence_field="steel_weighbridge_ticket", severity="red", source="ELV Rules 2025, EPR on steel recovered"),
    dict(rule_id="C04", check="Hazardous fractions (oil, battery, refrigerant) sent to an authorised recycler with manifest",
         evidence_field="hazwaste_manifest_no", severity="amber", source="Hazardous and Other Wastes Rules; ELV Rules 2025"),
    dict(rule_id="C05", check="Every harvested component traceable to its source vehicle",
         evidence_field="trace_tags_complete", severity="amber", source="IATF 16949-style traceability expectation"),
    dict(rule_id="C06", check="Every reused part graded against a documented limit, with measurement evidence",
         evidence_field="grading_evidence_complete", severity="amber", source="BSI PAS 3100 (remanufactured parts) principle"),
    dict(rule_id="C07", check="Reused / remanufactured parts labelled so they cannot be mistaken for new",
         evidence_field="reman_label_printed", severity="amber", source="FTC guides on rebuilt/remanufactured auto parts (disclosure principle)"),
    dict(rule_id="C08", check="Every engineer override logged with a reason",
         evidence_field="overrides_logged", severity="amber", source="Internal audit trail requirement"),
    dict(rule_id="C09", check="Catalytic converter sent to an authorised PGM recycler",
         evidence_field="pgm_recycler_id", severity="amber", source="ELV Rules 2025 (channelling to registered recyclers)"),
])
ev_rows = []
for v in veh_rows:
    vid = v["vehicle_id"]
    ev_rows.append(dict(
        vehicle_id=vid,
        depollution_record_id="" if vid == "V07" else f"DP-26-{int(rng.integers(1000, 9999))}",
        certificate_of_deposit_no="" if v["dereg_status"] == "pending" else f"COD-HR-{int(rng.integers(100000, 999999))}",
        steel_weighbridge_ticket=f"WB-{int(rng.integers(10000, 99999))}",
        hazwaste_manifest_no=f"HW-{int(rng.integers(1000, 9999))}" if vid != "V12" else "",
        trace_tags_complete="Y",
        grading_evidence_complete="N" if vid == "V11" else "Y",   # missing photos
        reman_label_printed="Y",
        overrides_logged="Y",
        pgm_recycler_id="" if vid == "V10" else f"PGM-{int(rng.integers(10, 99))}",
    ))
compliance_evidence = pd.DataFrame(ev_rows)

# --------------------------------------------------------------------------------------
# 7. Carbon factors (approximate public averages; cite exact sources in the deck)
# --------------------------------------------------------------------------------------
carbon = pd.DataFrame([
    dict(material="steel", kgco2e_per_kg_new=1.9, reuse_share_of_new=0.15, note="approx. global average, primary route mix"),
    dict(material="aluminium", kgco2e_per_kg_new=15.0, reuse_share_of_new=0.10, note="approx. primary aluminium"),
    dict(material="copper", kgco2e_per_kg_new=4.0, reuse_share_of_new=0.15, note="approx. refined copper"),
    dict(material="electronics", kgco2e_per_kg_new=60.0, reuse_share_of_new=0.10, note="rough, per kg of assembly"),
    dict(material="steel/copper", kgco2e_per_kg_new=2.4, reuse_share_of_new=0.15, note="blend"),
    dict(material="aluminium/copper", kgco2e_per_kg_new=10.0, reuse_share_of_new=0.12, note="blend"),
    dict(material="plastic/glass", kgco2e_per_kg_new=3.0, reuse_share_of_new=0.10, note="blend"),
    dict(material="lead", kgco2e_per_kg_new=1.5, reuse_share_of_new=0.30, note="recycled, not reused"),
    dict(material="steel/PGM", kgco2e_per_kg_new=8.0, reuse_share_of_new=0.20, note="PGM recovery, rough"),
])

# --------------------------------------------------------------------------------------
for name, df in {
    "vehicles": vehicles, "components": components, "bom": bom_public,
    "grading_rules_reference": grading_rules_reference, "inspections": inspections,
    "market_prices": market, "part_market": part_market,
    "compliance_rules": compliance_rules, "compliance_evidence": compliance_evidence,
    "carbon_factors": carbon,
}.items():
    df.to_csv(OUT / f"{name}.csv", index=False)
    print(f"{name:26s} {len(df):4d} rows")
