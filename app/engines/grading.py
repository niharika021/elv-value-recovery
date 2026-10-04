"""Grading engine: teardown measurement + drawing limit -> part verdict.

Fixed rules own the verdict. Inspector notes and photos never change it; they can
only raise a flag that sends the part to an engineer for review.

Rules come from grading_rules_reference.csv today. Later they come from Gemini's
reading of the drawings, so load_rules() rejects anything malformed instead of guessing.

Run:  python -m app.engines.grading      -> per-unit summary for the synthetic month
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"

LIMIT_TYPES = {"min", "max", "range", "pass_fail", "scale_max"}
FAIL_VERDICTS = {"scrap", "replace", "refurbish"}
CONTINUOUS = {"min", "max", "range"}  # measured on a scale with a nominal: margin is meaningful

# Within this share of the tolerance band from the limit, a passing part goes to an engineer.
# Default to be confirmed by the engineering lead; callers can pass their own.
BORDERLINE_MARGIN = 0.10

# Note wording. A note can raise a flag; it can never change a verdict.
NOTE_OK = ("looks ok", "within spec", "good condition", "clean", "perfect", "normal wear", "light wear")
NOTE_WEAR = ("noise", "heavy wear", "scoring", "discoloured", "pitting", "worn unevenly", "crack")

# Flags
NOTE_CONTRADICTS = "note_contradicts_measurement"  # measurement fails, note says fine
NOTE_SUGGESTS_WEAR = "note_suggests_wear"          # measurement passes, note describes damage
BORDERLINE = "borderline"                          # passes, but close to the limit
NO_PHOTO = "photo_missing"                         # grading evidence incomplete (compliance C06)
NO_READING = "no_reading"                          # measurement missing or unreadable


class RuleError(ValueError):
    """A grading rule is malformed. Never grade against it."""


@dataclass(frozen=True)
class GradingRule:
    part_no: str
    measure: str
    unit: str
    limit_type: str
    limit_1: float | None
    limit_2: float | None
    verdict_if_fail: str
    drawing_no: str
    nominal: float | None = None

    def describe(self) -> str:
        u = "" if self.unit in ("-", "0-3") else f" {self.unit}"
        if self.limit_type == "pass_fail":
            return "pass/fail"
        if self.limit_type == "range":
            return f"{self.limit_1:g}-{self.limit_2:g}{u}"
        if self.limit_type == "scale_max":
            return f"max {self.limit_1:g} on 0-3 scale"
        return f"{self.limit_type} {self.limit_1:g}{u}"


@dataclass(frozen=True)
class PartGrade:
    vehicle_id: str
    unit_type: str
    part_no: str
    measure: str
    measured_value: str
    limit: str
    drawing_no: str
    result: str           # pass | fail | no_reading
    verdict: str          # reuse | replace | refurbish | scrap | needs_inspection
    margin: float | None  # share of tolerance band left before the limit (0 = at limit); None if not continuous
    flags: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""

    @property
    def needs_review(self) -> bool:
        return bool(set(self.flags) - {NO_PHOTO}) or self.verdict == "needs_inspection"


def _num(x) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)) or str(x).strip() == "":
        return None
    return float(x)


def load_rules(rules: pd.DataFrame | Path | str | None = None,
               bom: pd.DataFrame | Path | str | None = None) -> dict[str, GradingRule]:
    """Load and validate grading rules, keyed by part_no. Nominal values come from the BOM."""
    rules = pd.read_csv(rules or DATA / "grading_rules_reference.csv") if not isinstance(rules, pd.DataFrame) else rules
    bom = pd.read_csv(bom or DATA / "bom.csv") if not isinstance(bom, pd.DataFrame) else bom
    nominal = dict(zip(bom.part_no, bom.nominal))

    out: dict[str, GradingRule] = {}
    for r in rules.itertuples(index=False):
        l1, l2 = _num(r.limit_1), _num(r.limit_2)
        where = f"{r.part_no} ({r.drawing_no})"
        if r.limit_type not in LIMIT_TYPES:
            raise RuleError(f"{where}: unknown limit_type {r.limit_type!r}")
        if r.verdict_if_fail not in FAIL_VERDICTS:
            raise RuleError(f"{where}: unknown verdict_if_fail {r.verdict_if_fail!r}")
        if r.limit_type in ("min", "max", "scale_max") and (l1 is None or l2 is not None):
            raise RuleError(f"{where}: {r.limit_type} needs exactly one limit")
        if r.limit_type == "range" and (l1 is None or l2 is None or l1 >= l2):
            raise RuleError(f"{where}: range needs limit_1 < limit_2, got {l1}, {l2}")
        if r.limit_type == "pass_fail" and (l1 is not None or l2 is not None):
            raise RuleError(f"{where}: pass_fail takes no limits")
        if r.part_no in out:
            raise RuleError(f"{where}: duplicate rule")
        out[r.part_no] = GradingRule(r.part_no, r.measure, r.unit, r.limit_type, l1, l2,
                                     r.verdict_if_fail, r.drawing_no, _num(nominal.get(r.part_no)))
    return out


def _check(rule: GradingRule, raw) -> tuple[str, float | None]:
    """Return (result, margin). result is pass | fail | no_reading."""
    if rule.limit_type == "pass_fail":
        v = str(raw).strip().lower()
        return (v, None) if v in ("pass", "fail") else ("no_reading", None)
    try:
        v = _num(raw)
    except ValueError:
        v = None
    if v is None:
        return "no_reading", None

    lt, l1, l2, nom = rule.limit_type, rule.limit_1, rule.limit_2, rule.nominal
    if lt == "scale_max":
        return ("pass" if v <= l1 else "fail"), None
    if lt == "min":
        ok, band, left = v >= l1, (nom - l1) if nom is not None else None, v - l1
    elif lt == "max":
        ok, band, left = v <= l1, (l1 - nom) if nom is not None else None, l1 - v
    else:  # range: distance to the nearer edge, against the half-width
        ok, band, left = l1 <= v <= l2, (l2 - l1) / 2, min(v - l1, l2 - v)
    margin = round(left / band, 3) if band else None
    return ("pass" if ok else "fail"), margin


def _note_says(note: str, words: tuple[str, ...]) -> bool:
    n = (note or "").lower()
    return any(w in n for w in words)


def grade_part(rule: GradingRule, measured_value, *, vehicle_id: str = "", unit_type: str = "",
               note: str = "", photo_uri: str = "", borderline: float = BORDERLINE_MARGIN) -> PartGrade:
    result, margin = _check(rule, measured_value)
    shown = "" if measured_value is None or (isinstance(measured_value, float) and math.isnan(measured_value)) \
        else str(measured_value)
    unit = "" if rule.unit in ("-", "0-3") else f" {rule.unit}"
    note = "" if not isinstance(note, str) else note
    flags: list[str] = []

    if result == "no_reading":
        verdict = "needs_inspection"
        flags.append(NO_READING)
        reason = f"No usable {rule.measure} reading; re-measure before grading."
    elif result == "pass":
        verdict = "reuse"
        reason = f"{shown}{unit} within {rule.describe()} ({rule.drawing_no})."
        if margin is not None and rule.limit_type in CONTINUOUS and margin < borderline:
            flags.append(BORDERLINE)
            reason += f" Only {margin:.0%} of the tolerance band left."
        if _note_says(note, NOTE_WEAR):
            flags.append(NOTE_SUGGESTS_WEAR)
            reason += f' Note says "{note}".'
    else:
        verdict = rule.verdict_if_fail
        reason = f"{shown}{unit} outside {rule.describe()} ({rule.drawing_no}): {verdict}."
        # Only for measurements an inspector can see; an electrical test can fail on a part that looks fine.
        if rule.limit_type in CONTINUOUS and _note_says(note, NOTE_OK) and not _note_says(note, NOTE_WEAR):
            flags.append(NOTE_CONTRADICTS)
            reason += f' Note says "{note}".'

    if not isinstance(photo_uri, str) or not photo_uri.strip():
        flags.append(NO_PHOTO)

    return PartGrade(vehicle_id, unit_type, rule.part_no, rule.measure, shown, rule.describe(),
                     rule.drawing_no, result, verdict, margin, tuple(flags), reason)


def grade_inspections(inspections: pd.DataFrame | None = None, rules: dict[str, GradingRule] | None = None,
                      borderline: float = BORDERLINE_MARGIN) -> pd.DataFrame:
    """Grade every inspection row. A part with no rule is an error, not a pass."""
    ins = pd.read_csv(DATA / "inspections.csv", dtype={"measured_value": str}) if inspections is None else inspections
    rules = load_rules() if rules is None else rules
    missing = sorted(set(ins.part_no) - set(rules))
    if missing:
        raise RuleError(f"No grading rule for {missing}")

    rows = []
    for r in ins.itertuples(index=False):
        rule = rules[r.part_no]
        if r.measure != rule.measure:
            raise RuleError(f"{r.vehicle_id} {r.part_no}: inspected {r.measure!r}, drawing limits {rule.measure!r}")
        g = grade_part(rule, r.measured_value, vehicle_id=r.vehicle_id, unit_type=r.unit_type,
                       note=r.inspector_note, photo_uri=r.photo_uri, borderline=borderline)
        rows.append({**g.__dict__, "flags": ",".join(g.flags), "needs_review": g.needs_review,
                     "inspector_note": r.inspector_note, "inspector": r.inspector})
    return pd.DataFrame(rows)


def summarise_units(grades: pd.DataFrame) -> pd.DataFrame:
    """One row per vehicle and unit (starter / alternator). Counts only; the value engine prices them."""
    def parts(g, verdict):
        return " ".join(g.loc[g.verdict == verdict, "part_no"])

    rows = []
    for (vid, unit), g in grades.groupby(["vehicle_id", "unit_type"], sort=True):
        review = g[g.needs_review]
        rows.append(dict(
            vehicle_id=vid, unit_type=unit, parts=len(g),
            reuse=int((g.verdict == "reuse").sum()),
            replace=parts(g, "replace"), refurbish=parts(g, "refurbish"), scrap=parts(g, "scrap"),
            review=" ".join(review.part_no),
            photos_missing=int(g["flags"].str.contains(NO_PHOTO).sum()),
            status="engineer_review" if len(review) else "graded",
        ))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    grades = grade_inspections()
    pd.set_option("display.width", 220, "display.max_colwidth", 60)
    print(summarise_units(grades).to_string(index=False))
    print("\nParts for engineer review:")
    print(grades[grades.needs_review][["vehicle_id", "part_no", "verdict", "flags", "reason"]].to_string(index=False))
    v = grades.verdict.value_counts()
    print(f"\n{len(grades)} parts graded: " + ", ".join(f"{k} {n}" for k, n in v.items())
          + f"; {int(grades.needs_review.sum())} for engineer review")
