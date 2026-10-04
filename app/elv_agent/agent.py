"""ELV Value Recovery agents (Google ADK): a coordinator and two specialists.

Agents read and explain; the engines own every number; an engineer approves every decision.
The agents only have read-only tools over engine outputs.

Run:  python -m app.elv_agent.ask "Why is V05's starter flagged?"
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.genai import types

from app.elv_agent import tools

load_dotenv()
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
CONFIG = types.GenerateContentConfig(temperature=0)

GROUND_RULES = """
Ground rules, always:
- Every number you state (rupees, kg, mm, %, minutes, counts) must appear in a tool result
  in this conversation. Copy it; do not calculate new figures, round differently, or estimate.
  If you need a figure no tool gives, say so.
- You explain; you never decide. Never say a part or vehicle is approved, overridden, released
  or re-priced. Engineer decisions are made by an engineer, outside this chat.
- Name your source: the drawing number for a limit, the rule ID and source document for
  compliance, the component line for a harvest decision.
- Rupees as INR with thousands separators (INR 41,984). Plain, short answers for an RVSF team.
- The data is a synthetic demo month; the compliance rule pack is a demo summary, not legal advice.
"""

inspection_agent = Agent(
    name="inspection_agent",
    model=MODEL,
    generate_content_config=CONFIG,
    description="Teardown grading of starters and alternators: measurements against drawing limits, "
                "verdicts, borderline parts, inspector notes, engineer review queue, and how limits "
                "were read from drawings.",
    instruction="""You explain teardown grading for starter and alternator parts.
The grading engine compares each measurement with the limit on the part's drawing and gives the
verdict. Inspector notes and photos never change a verdict; they raise flags that send a part to
an engineer. Explain a flag by quoting the measurement, the limit and drawing number, and the note.
Limits come from the drawings; Gemini's readings are checked by fixed gates and still need an
engineer's sign-off before use.
When the question is not about grading or drawings, transfer back to elv_coordinator.
""" + GROUND_RULES,
    tools=[tools.vehicle_grading, tools.review_queue, tools.drawing_rule],
)

compliance_agent = Agent(
    name="compliance_agent",
    model=MODEL,
    generate_content_config=CONFIG,
    description="Compliance checks per vehicle: which rules pass, fail or do not apply, what evidence "
                "is missing, and whether a failure blocks dismantling or release.",
    instruction="""You explain the compliance check for each vehicle.
Red rules that fail at the dismantle stage (depollution record, Certificate of Deposit) mean the
vehicle may not be dismantled; other failures hold its release until the evidence is on file.
A rule marked n/a does not apply (say why). Say what evidence would close each gap.
When the question is not about compliance, transfer back to elv_coordinator.
""" + GROUND_RULES,
    tools=[tools.vehicle_compliance, tools.compliance_overview],
)

root_agent = Agent(
    name="elv_coordinator",
    model=MODEL,
    generate_content_config=CONFIG,
    description="ELV value recovery coordinator for a registered vehicle scrapping facility (RVSF).",
    instruction="""You help an RVSF team earn more from each end-of-life vehicle, close the gap to
the informal scrapper's offer, and stay compliant.
You answer questions on offers, value, harvest plans and labour what-ifs with your own tools.
Transfer to inspection_agent for part grading, drawing limits and the engineer review queue.
Transfer to compliance_agent for compliance rules, evidence and release.
""" + GROUND_RULES,
    tools=[tools.month_overview, tools.vehicle_value, tools.plan_what_if],
    sub_agents=[inspection_agent, compliance_agent],
)
