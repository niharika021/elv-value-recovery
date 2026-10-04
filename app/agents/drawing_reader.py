"""Drawing reader: Gemini reads the inspection limits off each part drawing.

Gemini gets the PDF and the part's BOM row (part number, measure, unit; never the limits) and
returns the limit as structured output plus a verbatim quote of the note it came from.
app.engines.rule_check then gates every rule; Gemini's reading is never used unchecked.

Setup: copy .env.example to .env and set GOOGLE_CLOUD_PROJECT (Vertex AI) and GEMINI_MODEL.
Run:   python -m app.agents.drawing_reader          -> data/extracted/rules_gemini.csv + score
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from app.engines.grading import DATA
from app.engines.rule_check import DRAWINGS, check_rules, score_against_reference

OUT = DATA / "extracted"

PROMPT = """You are reading an engineering part drawing for a vehicle remanufacturing line.
Find the inspection or wear limit for the measure named below, in the NOTES box, and the action
the drawing requires when a part fails it. Report only what the drawing states; do not use
typical values from your own knowledge. Dimensions shown on the view are nominal sizes, not limits.

Part: {part_no} ({part_name}), drawing {drawing_no}
Measure to find: {measure} (unit {unit})

limit_type:
  min        the value must be at least limit_1
  max        the value must be at most limit_1
  range      the value must be between limit_1 and limit_2 (limit_1 < limit_2)
  pass_fail  a test or check that passes or fails; no limits
  scale_max  a 0-3 grade must not exceed limit_1
verdict_if_fail: scrap (part not reusable), replace (fit a new or grade-A part), or
  refurbish (clean, treat, recoat and reuse).
unit: as the BOM gives it: {unit}
evidence: the note lines stating the limit and the action, copied exactly as printed."""


class DrawingRule(BaseModel):
    part_no: str
    drawing_no: str
    unit: str
    limit_type: Literal["min", "max", "range", "pass_fail", "scale_max"]
    limit_1: Optional[float] = Field(None, description="null for pass_fail")
    limit_2: Optional[float] = Field(None, description="upper limit, only for range")
    verdict_if_fail: Literal["scrap", "replace", "refurbish"]
    evidence: str


def gemini_reader(model: str | None = None):
    """Return read(pdf_bytes, bom_row) -> dict, backed by Gemini on Vertex AI (or an API key)."""
    from google import genai
    from google.genai import types

    load_dotenv()
    model = model or os.environ.get("GEMINI_MODEL")
    if not model:
        sys.exit("Set GEMINI_MODEL in .env (see .env.example)")
    client = genai.Client()  # reads GOOGLE_GENAI_USE_VERTEXAI / GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION
    config = types.GenerateContentConfig(response_mime_type="application/json",
                                         response_schema=DrawingRule, temperature=0)

    def read(pdf: bytes, bom_row: dict) -> dict:
        r = client.models.generate_content(
            model=model, config=config,
            contents=[types.Part.from_bytes(data=pdf, mime_type="application/pdf"),
                      PROMPT.format(**bom_row)])
        if r.parsed is None:
            raise RuntimeError(f"{bom_row['part_no']}: no structured answer ({r.text!r:.200})")
        return r.parsed.model_dump()

    read.model = model
    return read


def extract_rules(read, bom: pd.DataFrame | None = None, drawings: Path = DRAWINGS) -> pd.DataFrame:
    """Run a reader over every BOM part's drawing. A failed read becomes a missing rule, not a guess."""
    bom = pd.read_csv(DATA / "bom.csv") if bom is None else bom
    rows = []
    for b in bom.to_dict("records"):
        try:
            rows.append(read((drawings / f"{b['drawing_no']}.pdf").read_bytes(), b))
        except Exception as e:  # noqa: BLE001 - one bad drawing must not stop the other nineteen
            print(f"  {b['part_no']}: read failed: {e}", file=sys.stderr)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    read = gemini_reader()
    print(f"Reading {len(pd.read_csv(DATA / 'bom.csv'))} drawings with {read.model} ...")
    checked = check_rules(extract_rules(read))
    checked["source"] = f"gemini:{read.model}"
    checked["approved_by"] = ""  # an engineer signs off before the grading engine may use these
    OUT.mkdir(exist_ok=True)
    checked.to_csv(OUT / "rules_gemini.csv", index=False)

    score = score_against_reference(checked)
    pd.set_option("display.width", 200, "display.max_colwidth", 90)
    bad = checked[checked.status != "checked"]
    if len(bad):
        print("\nRejected by the rule check:")
        print(bad[["part_no", "problems"]].to_string(index=False))
    if (~score.correct).any():
        print("\nDiffers from the answer key:")
        print(score[~score.correct][["part_no", "status", "wrong"]].to_string(index=False))
    print(f"\n{(checked.status == 'checked').sum()}/{len(checked)} passed the rule check; "
          f"{score.correct.sum()}/{len(score)} match the answer key -> {OUT / 'rules_gemini.csv'}")
