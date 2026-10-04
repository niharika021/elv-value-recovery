"""Rule check: fixed gates between Gemini's reading of a drawing and the grading engine.

Gemini reads the limits; nothing here trusts it. A rule is accepted only if
  1. it passes the grading engine's own validation (load_rules),
  2. it names the drawing and part it was read from, and the unit matches the BOM,
  3. its evidence quote is really on that drawing, and
  4. every limit number in the rule appears in that quote, and
  5. the quote names the action the rule says to take on failure (scrap / replace / refurbish).
Accepted rules still wait for an engineer's approval before anything is graded with them.

score_against_reference() compares with the answer key; that is for the demo, not production.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
from pypdf import PdfReader

from app.engines.grading import DATA, RuleError, load_rules

DRAWINGS = DATA / "drawings"
RULE_FIELDS = ["part_no", "measure", "unit", "limit_type", "limit_1", "limit_2", "verdict_if_fail", "drawing_no"]
SCORED = ["limit_type", "limit_1", "limit_2", "verdict_if_fail"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().upper()


@lru_cache(maxsize=None)
def drawing_text(path: Path) -> str:
    return _norm(" ".join(p.extract_text() or "" for p in PdfReader(path).pages))


def _numbers(text: str) -> set[float]:
    return {float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)}


def _blank(x) -> bool:
    return x is None or (isinstance(x, float) and pd.isna(x)) or str(x).strip() == ""


def check_rule(row: dict, bom_row: dict, drawings: Path = DRAWINGS) -> list[str]:
    """Problems with one extracted rule; an empty list means it passed every gate."""
    problems = []
    if row.get("part_no") != bom_row["part_no"]:
        problems.append(f"part_no {row.get('part_no')!r} is not {bom_row['part_no']!r}")
    if row.get("drawing_no") != bom_row["drawing_no"]:
        problems.append(f"drawing_no {row.get('drawing_no')!r} is not {bom_row['drawing_no']!r}")
    if _norm(row.get("unit", "")) != _norm(bom_row["unit"]):
        problems.append(f"unit {row.get('unit')!r} does not match BOM unit {bom_row['unit']!r}")

    try:
        load_rules(pd.DataFrame([{k: row.get(k) for k in RULE_FIELDS}]),
                   pd.DataFrame([dict(part_no=bom_row["part_no"], nominal=bom_row["nominal"])]))
    except RuleError as e:
        problems.append(str(e))

    pdf = drawings / f"{bom_row['drawing_no']}.pdf"
    quote = _norm(row.get("evidence", ""))
    if not quote:
        problems.append("no evidence quote")
    elif not pdf.exists():
        problems.append(f"drawing {pdf.name} not found")
    elif quote not in drawing_text(pdf):
        problems.append(f"evidence not found on {pdf.name}: {row.get('evidence')!r}")
    else:
        for k in ("limit_1", "limit_2"):
            if not _blank(row.get(k)) and float(row[k]) not in _numbers(quote):
                problems.append(f"{k} {row[k]} is not in the evidence quote")
        if row.get("verdict_if_fail") and _norm(row["verdict_if_fail"]) not in quote:
            problems.append(f"verdict {row['verdict_if_fail']!r} is not named in the evidence quote")
    return problems


def check_rules(extracted: pd.DataFrame, bom: pd.DataFrame | None = None,
                drawings: Path = DRAWINGS) -> pd.DataFrame:
    """Gate every extracted rule. Adds `problems` and `status` (checked | rejected); a BOM part
    with no extracted rule is reported as missing rather than skipped."""
    bom = pd.read_csv(DATA / "bom.csv") if bom is None else bom
    by_part = {r["part_no"]: r for r in extracted.to_dict("records")}
    rows = []
    for b in bom.to_dict("records"):
        r = by_part.get(b["part_no"])
        if r is None:
            rows.append({"part_no": b["part_no"], "drawing_no": b["drawing_no"], "measure": b["measure"],
                         "problems": "no rule extracted", "status": "rejected"})
            continue
        r = {**r, "measure": b["measure"]}  # the BOM names the measure; the drawing gives its limits
        p = check_rule(r, b, drawings)
        rows.append({**r, "problems": "; ".join(p), "status": "rejected" if p else "checked"})
    extra = set(by_part) - set(bom.part_no)
    for part_no in sorted(extra):
        rows.append({**by_part[part_no], "problems": "part not in BOM", "status": "rejected"})
    return pd.DataFrame(rows)


def score_against_reference(checked: pd.DataFrame, reference: pd.DataFrame | None = None) -> pd.DataFrame:
    """Field-by-field comparison with the answer key. One row per part."""
    ref = pd.read_csv(DATA / "grading_rules_reference.csv") if reference is None else reference
    got = checked.set_index("part_no")
    rows = []
    for r in ref.to_dict("records"):
        g = got.loc[r["part_no"]].to_dict() if r["part_no"] in got.index else {}
        wrong = []
        for f in SCORED:
            a, b = r[f], g.get(f)
            same = (_blank(a) and _blank(b)) or (not _blank(a) and not _blank(b) and
                                                 (float(a) == float(b) if f in ("limit_1", "limit_2") else a == b))
            if not same:
                wrong.append(f"{f}: read {b!r}, key {a!r}")
        rows.append(dict(part_no=r["part_no"], status=g.get("status", "missing"), correct=not wrong,
                         wrong="; ".join(wrong)))
    return pd.DataFrame(rows)
