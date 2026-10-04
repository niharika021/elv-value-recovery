# ELV Value Recovery Planner

**Team MECA Queens · Google Cloud AI Builder Cup 2026 · Manufacturing: Intelligent Operations & Industrial Efficiency**

Formal vehicle scrapping centres (RVSFs) in India lose end-of-life vehicles to informal scrappers, who pay owners about **₹15,000 more per vehicle**. RVSFs run below **20% of capacity**, and producers missed the first ELV-rules scrapping target by **70%** (FY26).

This app helps an RVSF earn more from every vehicle:
- decide **which components to harvest** for reuse or remanufacturing
- **grade starter and alternator parts** against limits that Gemini reads from part drawings
- calculate **value per vehicle**, certified **steel for EPR**, and **CO₂ avoided**
- run a **compliance check** before any vehicle or part is released, and produce an audit pack

Design rule: **agents read and explain; fixed engines own every number; an engineer approves every decision.**

> Status: Day 5 (grading, value and harvest-planner engines). Agents and the web app follow; see the timeline in the project plan.

---

## Repository layout

```
data/                      synthetic dataset (CSV) + data/drawings/*.pdf
scripts/generate_data.py   regenerates every CSV (fixed seed, deterministic)
scripts/make_drawings.py   regenerates the 20 part drawings
scripts/check_values.py    first sketch of the value engine: scrap-only vs harvest offer per vehicle
app/agents/                ADK coordinator, inspection agent, compliance agent        (Day 6-8)
app/engines/               grading rules, value engine, harvest planner (OR-Tools)    (Day 3-5)
app/web/                   frontend: vehicle cards, approval inbox, dashboard         (Day 9-11)
```

Regenerate everything:

```bash
pip install -r requirements.txt
python scripts/generate_data.py
python scripts/make_drawings.py
python scripts/check_values.py
python -m app.engines.grading     # Day 3: grade every teardown part
python -m app.engines.value       # Day 4: offer, EPR steel and CO2 per vehicle (add V03 for one vehicle)
python -m app.engines.planner     # Day 5: best harvest at 100%, 75% and 50% of the labour needed
python -m pytest -q
```

## Dataset (all invented)

| File | Rows | What it holds |
|---|---|---|
| `vehicles.csv` | 12 | One synthetic RVSF month: segment, model year, kerb weight, metal content, condition, deregistration status, informal offer, planted demo story |
| `components.csv` | 108 | 9 harvestable components per vehicle with condition grade (A/B/C), sale value, weight, dismantling minutes |
| `bom.csv` | 20 | Starter and alternator parts with measure, nominal value and drawing number (limits are only on the drawings) |
| `drawings/DWG-*.pdf` | 20 | Generic part drawings with wear and inspection limits written in the NOTES box |
| `grading_rules_reference.csv` | 20 | Answer key for Gemini's drawing extraction (limit type, limits, verdict if failed) |
| `inspections.csv` | 190 | Teardown measurements, crack and corrosion checks, inspector notes, photo paths |
| `market_prices.csv` | 8 | Scrap metal prices, EPR certificate value, processing cost, labour rate, margin |
| `part_market.csv` | 7 | Demand and new-part lead time for high-value sub-parts |
| `compliance_rules.csv` | 9 | Demo rule pack (summaries, with source names; not legal text) |
| `compliance_evidence.csv` | 12 | Evidence on file per vehicle |
| `carbon_factors.csv` | 9 | Approximate kgCO₂e per kg new, and the share avoided by reuse |

### Planted demo stories

| Vehicle | Story the app must surface |
|---|---|
| V02 | Alternator voltage regulator in perfect condition: high-demand part (90-day new lead time) |
| V03 | Catalytic converter worth roughly half the car's steel value |
| V04 | Deregistration pending, no Certificate of Deposit: compliance **red** |
| V05 | Starter brushes 7.9 mm against an 8.5 mm drawing minimum, though the note says "looks ok" |
| V06 | Front-end accident: front components lost, harvest the rest |
| V07 | No depollution record: compliance **red**, cannot be released |
| V08 | Alternator bearing play 0.095 mm (limit 0.10) with "slight noise": engineer override moment |
| V09 | Flood and rust: harvesting is not worth the labour |
| V10 | Catalytic converter missing before intake: biggest value gap |
| V11 | Mislabelled model code and missing photos: data quality and amber compliance |
| V12 | No hazardous-waste manifest: compliance **amber** |

### Grading engine (`app/engines/grading.py`)

Measurement + drawing limit -> **reuse / replace / refurbish / scrap** for each part. Limits are inclusive, a missing reading is never a pass, and malformed rules are rejected (they will come from Gemini later).
Inspector notes and photos **never change a verdict**; they raise flags, and any flagged part goes to an engineer:

| Flag | Raised when | Demo |
|---|---|---|
| `note_contradicts_measurement` | a dimension fails but the note says it looks fine | V05 starter brushes |
| `borderline` | a pass with under 10% of the tolerance band left | V08 alternator bearing |
| `note_suggests_wear` | a pass, but the note describes damage or noise | V08 "slight noise" |
| `photo_missing` | no photo: grading evidence incomplete (compliance C06), not an engineering review | V11 |

Synthetic month: 190 parts graded, 176 reuse, 7 replace, 7 scrap, 8 for engineer review.

### Value engine (`app/engines/value.py`)

Prices **any** harvest set for a vehicle: metal in the shredder stream + battery and converter + EPR certificate + harvested parts (sale value less labour and the scrap value they take out) - processing cost - margin = **offer**. With the default rule it reproduces `check_values.py` exactly, vehicle by vehicle; the Day 5 planner will choose the set instead.

It also reports **steel to the recycler** (body steel less the steel leaving in reused parts: the weighbridge basis for EPR) and **CO₂ avoided** by reuse. Each line carries its reason, its teardown status from the grading engine, and the high-demand sub-parts that passed, with their margin (V02's regulator: 100%).
Grade C, missing, or always-removed parts cannot be harvested; asking for one is an error, not a zero.

Synthetic month: 8,385 kg steel to recyclers, 2,132 kg CO₂ avoided.

### Harvest planner (`app/engines/planner.py`)

OR-Tools CP-SAT chooses which parts to pull across the month to maximise the total offer, under optional limits: **technician minutes**, **blocked vehicles** (e.g. a red compliance check), and **engineer decisions** (parts excluded or required). It only chooses; the value engine prices the plan. Contradictory instructions, or required parts that do not fit, are refused rather than half-met.

With no limits the plan equals the value engine's default rule. Plans are proven optimal (tests check them against an exact knapsack), and every positive part left on a vehicle says why.

| Labour available | Parts | Harvest gain | Gap closed |
|---|---|---|---|
| 1,240 min (all) | 58 | ₹75,460 | 39% |
| 930 min (75%) | 46 | ₹67,845 | 35% |
| 620 min (50%) | 30 | ₹54,366 | 28% |

On this data, "best value per minute first" lands within ~₹100 of optimal; the solver earns its place by guaranteeing the plan and handling engineer decisions and future limits (per day, per technician) without special cases.

### Economics check (`scripts/check_values.py`)

Calibrated so the scrap-only gap matches NITI Aayog's estimate:

- Average gap to the informal offer, scrap-only: **≈ ₹14,700 per vehicle**
- With AI-guided harvesting: **≈ ₹9,000**, i.e. **about 39% of the gap closed on average, up to ~74%** on good vehicles, none on the flood car

## Sources for the public figures

- NITI Aayog, *India's ELV circular economy* (Jan 2026): informal price gap, EPR certificate value, RVSF utilisation
  https://www.niti.gov.in/hi/node/2110
- Tribune India (10 May 2026): FY26 target 7.62 lakh vehicles, 2.42 lakh scrapped
  https://www.tribuneindia.com/news/india/end-of-life-vehicle-rules-make-auto-sector-non-compliant-fy26-scrap-target-missed-by-70/

## Disclaimer

All vehicles, parts, drawings, prices and evidence records are invented for a hackathon demo. No real company, brand, product, drawing or price list is used. The compliance rule pack is a simplified demo summary and is not legal advice.
