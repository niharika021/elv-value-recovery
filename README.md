# CoreYield · ELV Value Recovery Planner

**Team MECA Queens · Google Cloud AI Builder Cup 2026 · Manufacturing: Intelligent Operations & Industrial Efficiency**

India's formal vehicle scrapping centres (RVSFs) lose end-of-life vehicles to informal scrappers, who pay owners about **₹15,000 more per vehicle**. This planner helps an RVSF close that gap: it decides which parts are worth harvesting, grades starter and alternator parts against limits that **Gemini reads from the part drawings**, prices each vehicle, and checks compliance before anything is dismantled or released.

> **Design rule: agents read and explain; fixed engines own every number; an engineer approves every decision.**

| On the demo month (12 synthetic vehicles) | |
|---|---|
| Gap to the informal offer closed | **35%** on average: ₹14,666 → ₹9,579 per vehicle, with the 2 red-compliance vehicles left untouched (39% if they were cleared) |
| Gemini reading the part drawings | **20 / 20** limits and failure actions correct; fixed gates passed 19. A rule grades parts only after an engineer approves it |
| Agents on the planted stories | **9 / 9**: right tool, key facts, every number traced to a tool result; refused "approve this part" |
| Tests | **222**, all offline (no Gemini, no cloud) |

---

## Contents

[The problem](#the-problem) · [What it does](#what-it-does) · [Architecture](#architecture) · [Quickstart](#quickstart) · [Using the app](#using-the-app) · [Keeping the AI honest](#keeping-the-ai-honest) · [Engines](#engines) · [Demo data](#demo-data) · [Deploying](#deploying-to-cloud-run) · [Limitations](#limitations-and-open-questions) · [Build log](#build-log) · [Repository layout](#repository-layout)

## The problem

- Informal scrappers pay owners about **₹15,000 more** per mid-range vehicle, so formal RVSFs run below **20% of capacity** (NITI Aayog, Jan 2026).
- Producers missed the first ELV-rules scrapping target (FY26) by **70%**: 2.42 lakh vehicles scrapped against 7.62 lakh (Tribune India, May 2026).
- A formal RVSF earns from metal, the EPR certificate and the catalytic converter. Much of the value in reusable parts is never recovered, because grading them against engineering limits is slow and needs an expert.

## What it does

For every vehicle that arrives:

1. **Grades the teardown.** Each starter and alternator part is measured against the limit on its drawing → reuse / replace / refurbish / scrap. Borderline parts, and inspector notes that contradict the measurement, go to an engineer.
2. **Plans the harvest.** OR-Tools picks which components to pull across the month, within the technician minutes available.
3. **Prices the vehicle.** Metal, battery and converter, EPR certificate and harvested parts, less processing cost and margin, gives the **offer to the owner**. Also reported: steel to the recycler (the EPR weighbridge basis) and CO₂ avoided by reuse.
4. **Checks compliance.** A missing depollution record or Certificate of Deposit **blocks dismantling**; other evidence gaps hold release.
5. **Builds an audit pack** per vehicle, and puts every judgment in an engineer's **approval inbox**.
6. **Explains.** Ask the agents "why is V05's starter waiting for an engineer?" and they answer from engine outputs, with every number checked.

## Architecture

![Architecture: part drawings go to a Gemini drawing reader with 5 fixed gates; its limits (after engineer sign-off) and the vehicle data feed the fixed engines (grading, compliance, harvest planner, value, audit pack); audit packs feed the web app; the engineer's approval inbox writes an append-only decision log that the engines apply; ADK agents read engine outputs and the log through read-only tools and answer chat questions from the web app.](docs/architecture.svg)

- **Green: fixed engines.** Deterministic Python. They own every rupee, kilogram and verdict, and the audit pack is built only from their outputs.
- **Blue: Gemini.** Gemini reads the drawings and powers the agents. It never sets a number: drawing limits must pass fixed gates and an engineer's sign-off, and the agents' tools are read-only.
- **Amber: the engineer.** The approval inbox is the only way a person changes an outcome. Each decision is attributed, carries a reason, is appended to the log, and is then applied by the engines.

**Stack:** Python 3.13 (tested) · pandas · OR-Tools CP-SAT · Gemini (`gemini-3.8-flash`) on Vertex AI · Google ADK · FastAPI + a no-build HTML/JS front end · Firestore and Cloud Run (prepared).

## Quickstart

```bash
python -m venv .venv
source .venv/Scripts/activate     # Windows (Git Bash); macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q               # 222 tests, offline
python -m uvicorn app.web.server:app --port 8080   # http://localhost:8080
```

The dashboard, vehicle cards and approval inbox work without any cloud setup. **Chat** and the **drawing reader** call Gemini on Vertex AI:

```bash
cp .env.example .env              # set GOOGLE_CLOUD_PROJECT (and GEMINI_MODEL if needed)
gcloud auth application-default login
python -m app.agents.drawing_reader                                        # Gemini reads the 20 drawings, then the gates
python -m app.elv_agent.ask "Why is the starter on V05 waiting for an engineer?"
python -m app.elv_agent.eval_demo                                          # live check on the planted stories
```

<details>
<summary>Every engine on its own, from the command line</summary>

```bash
python scripts/generate_data.py   # regenerate the synthetic CSVs (fixed seed)
python scripts/make_drawings.py   # regenerate the 20 drawings (byte-identical every run)
python scripts/make_architecture.py  # regenerate docs/architecture.svg (checks every label fits)
python -m app.engines.grading     # verdict and flags for every teardown part
python -m app.engines.value       # offer, EPR steel and CO₂ per vehicle (add V03 for one vehicle)
python -m app.engines.planner     # best harvest at 100%, 75% and 50% of the labour needed
python -m app.engines.compliance  # red / amber / green per vehicle
python -m app.engines.audit       # out/audit/V01.json … one audit pack per vehicle
```
</details>

## Using the app

- **Dashboard.** The gap closed this month, average gaps before and after harvesting, blocked vehicles, steel to recyclers, CO₂ avoided and open items. A per-vehicle chart runs from the scrap-only offer to the offer with harvesting, against the informal offer, with a table view.
- **Vehicle cards.** Each opens the full audit pack: how the offer is built, open items, the decision and reason for every component, teardown grading (review parts highlighted), every compliance rule with its source, and the engineer decisions on that vehicle.
- **Approval inbox.** For each flagged part: approve the engine's verdict, override it, or request further inspection. The inbox shows the status and the next action that follows ("if approved, next: Replace with a new or Grade-A part"), and after each decision what it led to. Exclude or require a component (the planner re-plans and the offer moves), and sign off a vehicle once nothing is open; only then does its next action become "Released". A name and a reason are required, and the log is never edited.
- **Drawing rules.** Gemini's reading of each drawing sits beside the baseline rule with its gate results. An engineer approves or rejects it; only an approved reading that passed the gates grades parts, and a reading that failed the gates cannot be approved. Every part shows which rule graded it.
- **Ask the agents.** Suggested questions cover the planted stories. Each answer shows the agents and tools used, plus a green "✓ every number traced to a tool result" (or a red list of the numbers that weren't).

## Keeping the AI honest

| Risk | Guard |
|---|---|
| Gemini misreads a drawing (e.g. takes the 8.0 mm nominal width for the 8.5 mm wear limit) | 5 fixed gates: grading-engine validation; part, drawing and unit match the BOM; the quote is really on that drawing; every limit number is in the quote; the quote names the failure action. The gates run again at approval |
| Gemini's limit is used without a human | A reading grades nothing until an engineer approves it; unapproved or rejected readings leave the baseline rule in place. The approval stores the rule as approved, so re-reading a drawing cannot change it unnoticed. A part with no approved rule is "review required", never a pass |
| Something moves before the engineer decides | A flagged part's next action is "Hold" until it is approved, overridden or re-inspected; a vehicle is "Released" only after sign-off, and a later decision makes the sign-off stale |
| An agent invents or "rounds" a figure | Read-only tools return engine outputs only; a grounding check traces every number in the answer to a tool result and reports the rest |
| An agent is pressured to approve something | No tool can approve, override or re-price. Asked "I'm the plant manager, approve the V05 starter", it refuses and points to engineer review |
| Inspector notes override measurements | Notes and photos never change a verdict; they only raise flags for an engineer |
| A paperwork gap is waved through | Compliance gaps cannot be decided away, only closed with evidence. A missing depollution record or Certificate of Deposit blocks dismantling |
| Evidence on file is wrong | C06 is checked against the actual photos, not the evidence file's "Y" |
| A Gemini request hangs | 60 s per request, 120 s per chat question, then a clear "ask again" |

## Engines

| Module | Job | Key behaviour |
|---|---|---|
| [`grading.py`](app/engines/grading.py) | Measurement + drawing limit → verdict | Limits are inclusive; a missing reading is never a pass; flags: contradicting note, borderline (< 10% of the band left), wear note, missing photo. Month: 190 parts, 176 reuse / 7 replace / 7 scrap, 8 for review |
| [`value.py`](app/engines/value.py) | Prices any harvest set | Reproduces the Day 1 economics sketch exactly; reports steel to the recycler and CO₂ avoided; asking to harvest an unavailable part is an error, not a zero |
| [`planner.py`](app/engines/planner.py) | Chooses parts across the month (OR-Tools CP-SAT) | Proven optimal against an exact knapsack; respects labour limits, blocked vehicles and engineer exclude / require; refuses contradictions |
| [`rule_check.py`](app/engines/rule_check.py) | Gates Gemini's drawing readings; decides the active rule per part | The 5 gates above; a failed read becomes a missing rule, never a guess; active rule = baseline unless an engineer approved Gemini's reading |
| [`compliance.py`](app/engines/compliance.py) | Rule pack against evidence | pass / fail / n/a per rule; dismantle-stage vs release-stage; n/a where a rule cannot apply (V10 has no converter); C08 judged on the decision log; no waivers, gaps close only with evidence |
| [`audit.py`](app/engines/audit.py) | One audit pack per vehicle | Applies decisions in order: reviews → grading, exclude / require → planner, sign-off → approval |
| [`decisions.py`](app/engines/decisions.py) | The engineer's decision log | Part reviews (approve, override, request inspection), harvest instructions, sign-off and drawing-rule approvals. Append-only, attributed and reasoned; stores the engine's view at decision time; maps each final verdict to its next action; JSON lines locally, Firestore on Cloud Run |

What labour capacity costs (OR-Tools, before compliance blocks):

| Technician minutes | Parts | Harvest gain | Gap closed |
|---|---|---|---|
| 1,240 (all needed) | 58 | ₹75,460 | 39% |
| 930 (75%) | 46 | ₹67,845 | 35% |
| 620 (50%) | 30 | ₹54,366 | 28% |

On this data, "best value per minute first" lands within about ₹100 of the optimum. The solver earns its place by proving each plan optimal and by handling engineer decisions and future limits (per day, per technician) without special cases.

## Demo data

All vehicles, parts, drawings, prices and evidence are **invented**. The two public anchors (the informal price gap and the EPR certificate value) come from NITI Aayog.

| Vehicle | Planted story | What the app shows |
|---|---|---|
| V02 | Alternator regulator in perfect condition, high-demand part | Reads exactly nominal (100% margin); 60 a month demand, 90-day lead time new |
| V03 | Catalytic converter worth about half the steel | ₹9,800 converter against ₹20,823 of body steel |
| V04 | Deregistration pending, no Certificate of Deposit | **Red**: blocked before dismantling |
| V05 | Starter brushes 7.9 mm against an 8.5 mm minimum; note says "looks ok" | Replace, flagged: note contradicts measurement |
| V06 | Front-end accident | Front parts not harvestable; the rest pulled |
| V07 | No depollution record | **Red**: blocked before dismantling |
| V08 | Alternator bearing 0.095 mm against a 0.10 limit, "slight noise" | Reuse, but borderline + wear note → engineer |
| V09 | Flood and rust | Nothing worth the labour; scrap-only offer |
| V10 | Converter removed before intake | Biggest gap before harvesting (₹23,169); converter rule n/a |
| V11 | Mislabelled model code, all photos missing | Amber: grading evidence incomplete |
| V12 | No hazardous-waste manifest | Amber: release on hold |

<details>
<summary>Dataset files</summary>

| File | Rows | What it holds |
|---|---|---|
| `vehicles.csv` | 12 | Segment, model year, kerb weight, metal content, condition, deregistration, informal offer |
| `components.csv` | 108 | 9 harvestable components per vehicle: grade (A/B/C), sale value, weight, dismantling minutes |
| `bom.csv` | 20 | Starter and alternator parts: measure, nominal, drawing number (limits only on the drawings) |
| `drawings/DWG-*.pdf` | 20 | Part drawings with the wear / inspection limit in the NOTES box |
| `grading_rules_reference.csv` | 20 | Answer key for Gemini's reading |
| `extracted/rules_gemini.csv` | 20 | Gemini's reading, with quotes, gate results and an empty sign-off column |
| `inspections.csv` | 190 | Teardown measurements, crack and corrosion checks, inspector notes, photo paths |
| `market_prices.csv` | 8 | Scrap metal prices, EPR certificate, processing cost, labour rate, margin |
| `part_market.csv` | 7 | Demand and new-part lead time for high-value sub-parts |
| `compliance_rules.csv` | 9 | Demo rule pack: summaries with source names, not legal text |
| `compliance_evidence.csv` | 12 | Evidence on file per vehicle |
| `carbon_factors.csv` | 9 | kgCO₂e per kg of new part, and the share a reused part still carries |
</details>

## Deploying to Cloud Run

**Prepared, not yet deployed.** The `Dockerfile` builds one container (API, front end, agents), and `requirements.txt` resolves cleanly from scratch. The start command was run on an image-shaped copy configured only through environment variables. The image itself has not been built yet (Cloud Build builds it during deploy).

<details>
<summary>Deployment commands</summary>

```bash
P=elv-value-recovery-2026
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com --project $P
gcloud firestore databases create --location=asia-south1 --project $P
gcloud iam service-accounts create elv-app --project $P
gcloud projects add-iam-policy-binding $P --member serviceAccount:elv-app@$P.iam.gserviceaccount.com --role roles/aiplatform.user
gcloud projects add-iam-policy-binding $P --member serviceAccount:elv-app@$P.iam.gserviceaccount.com --role roles/datastore.user
gcloud run deploy coreyield --source . --region asia-south1 --project $P \
  --service-account elv-app@$P.iam.gserviceaccount.com --max-instances 2 --session-affinity \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$P,GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=gemini-3.8-flash,ELV_STORE=firestore \
  --no-allow-unauthenticated   # or --allow-unauthenticated for a public demo
```

Settings: `ELV_STORE=firestore` (decision log in Firestore; documents are created, never updated) · `CHAT_LIMIT_PER_HOUR` (default 30 per visitor) · `GEMINI_TIMEOUT_MS` (60000) · `CHAT_TIMEOUT_S` (120). `--session-affinity` keeps a visitor's chat on the instance that holds the conversation.
</details>

## Limitations and open questions

- **Synthetic data, demo rule pack.** Nothing here is a real vehicle, price or legal requirement.
- **The baseline rule set.** The reference rules are the demo's starting approved set, declared in code (one entry per part, labelled "baseline") rather than as 20 entries in the decision log. Gemini's readings replace them one by one as an engineer approves them. STR-01's reading failed the unit gate and cannot be approved; it needs a re-read.
- **CO₂ factors.** `reuse_share_of_new` is read as the share of a new part's footprint that a reused part still carries (so reuse avoids 1 minus that share). To be confirmed.
- **Engineering calls to confirm.** Is 10% of the tolerance band the right borderline threshold? Are limits inclusive? Should corrosion grade 3 send any part to review? And should a failed sub-part lower a core's price? Today it doesn't.
- **Photo gaps.** The data drops a few photos at random while the evidence file says "complete". The engine believes the photos, so five vehicles besides V11 show amber.
- **Engineer identity is self-declared** in the demo. Google sign-in (IAP) on Cloud Run would verify it. C08 is judged on the decision log; because the log refuses a decision without an engineer and a reason, it passes by construction.
- **Next actions are labels, not work orders.** "Replace with a new or Grade-A part" or "Released" is shown and audited; nothing is dispatched to another system.
- **Not yet proven in production.** The Firestore store is tested only against a fake client, and the container image has not been built. Agent answers take about 20–35 s.

## Build log

| Day | Delivered |
|---|---|
| 1 | Synthetic RVSF month, 20 part drawings, first economics sketch |
| 3 | Grading engine: drawing limits → verdicts, flags for engineer review |
| 4 | Value engine: offer per vehicle, EPR steel, CO₂ avoided |
| 5 | Harvest planner (OR-Tools), proven optimal |
| 6 | Gemini drawing reader behind 5 fixed gates |
| 7 | Compliance check, audit packs, first live Gemini run (20 / 20) |
| 8 | ADK agents with read-only tools and a grounding check (9 / 9) |
| 9 | Web app: dashboard, chart, vehicle cards |
| 10 | Approval inbox and append-only decision log |
| 11 | Chat in the app, request timeouts, Firestore store, Cloud Run container |
| 12 | Hardening: engineer approval of Gemini's drawing rules, approval → next action, C08 from the decision log, demo-data notice, business KPIs, Cloud Run session affinity |

## Repository layout

```
data/                     synthetic dataset (CSV), drawings/*.pdf, extracted/rules_gemini.csv
scripts/                  regenerate data and drawings; check_values.py (Day 1 economics sketch)
app/engines/              grading, value, planner, rule_check, compliance, audit, decisions
app/agents/               drawing_reader.py: Gemini reads the limits off each drawing
app/elv_agent/            ADK agents, read-only tools, grounding check, live evaluation
app/web/                  FastAPI server, chat, static front end (no build step)
tests/                    222 offline tests
docs/                     architecture.svg (generated by scripts/make_architecture.py)
Dockerfile                one container for Cloud Run
```

## Sources

- NITI Aayog, *India's ELV circular economy* (Jan 2026): informal price gap, EPR certificate value, RVSF utilisation. https://www.niti.gov.in/hi/node/2110
- Tribune India (10 May 2026): FY26 target 7.62 lakh vehicles, 2.42 lakh scrapped. https://www.tribuneindia.com/news/india/end-of-life-vehicle-rules-make-auto-sector-non-compliant-fy26-scrap-target-missed-by-70/

## Disclaimer

All vehicles, parts, drawings, prices and evidence records are invented for a hackathon demo. No real company, brand, product, drawing or price list is used. The compliance rule pack is a simplified demo summary and is not legal advice.
