"""Compliance engine: the demo rule pack against each vehicle's evidence on file.

For every vehicle and rule: pass, fail, or n/a (with the reason), and which stage a failure
blocks. Dismantle-stage rules (depollution, Certificate of Deposit) stop the harvest planner
before anything is pulled; every other rule holds the vehicle's release.
Vehicle status: red if a red rule fails, amber if an amber rule fails, otherwise green.

Evidence is not taken on trust where the engines can check it: grading evidence fails when
the grading engine finds a harvested part without its photo, whatever the evidence file says;
C08 (overrides logged with a reason) is judged on the decision log itself, not the file's Y/N.
There are no engineer waivers: a compliance gap closes only when the evidence is on file.

The rule pack is a simplified demo summary, not legal text (see compliance_rules.csv sources).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.engines.grading import DATA, NO_PHOTO
from app.engines.value import UNIT_OF

# What each evidence field gates. A new rule needs a decision here before the engine will run.
STAGE = {
    "depollution_record_id": "dismantle",
    "certificate_of_deposit_no": "dismantle",
    "steel_weighbridge_ticket": "release",
    "hazwaste_manifest_no": "release",
    "trace_tags_complete": "release",
    "grading_evidence_complete": "release",
    "reman_label_printed": "release",
    "overrides_logged": "release",
    "pgm_recycler_id": "release",
}
ABOUT_HARVEST = {"trace_tags_complete", "grading_evidence_complete", "reman_label_printed"}


class ComplianceError(ValueError):
    """The rule pack or evidence cannot be checked as given."""


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    severity: str
    stage: str
    status: str        # pass | fail | n/a
    detail: str
    check: str
    source: str


@dataclass(frozen=True)
class VehicleCompliance:
    vehicle_id: str
    results: tuple[RuleResult, ...]

    @property
    def fails(self) -> list[RuleResult]:
        return [r for r in self.results if r.status == "fail"]

    @property
    def status(self) -> str:
        sev = {r.severity for r in self.fails}
        return "red" if "red" in sev else "amber" if "amber" in sev else "green"

    @property
    def can_dismantle(self) -> bool:
        return not any(r.stage == "dismantle" for r in self.fails)

    @property
    def can_release(self) -> bool:
        return not self.fails


def load_rule_pack(rules: pd.DataFrame | None = None) -> pd.DataFrame:
    rules = pd.read_csv(DATA / "compliance_rules.csv") if rules is None else rules
    unknown = sorted(set(rules.evidence_field) - set(STAGE))
    if unknown:
        raise ComplianceError(f"No stage decided for evidence field(s) {unknown}")
    bad = sorted(set(rules.severity) - {"red", "amber"})
    if bad:
        raise ComplianceError(f"Unknown severity {bad}")
    return rules


def _present(v) -> bool:
    return isinstance(v, str) and v.strip() not in ("", "N")


OVERRIDE_ACTIONS = ("override:", "exclude", "require")


def _overrides_logged(overrides: list, file_value) -> tuple[str, str]:
    """C08 from the decision log: every engineer override needs a named engineer and a reason."""
    bad = [d for d in overrides if not d.engineer.strip() or not d.reason.strip()]
    note = "" if not isinstance(file_value, str) or file_value.strip() in ("", "Y") else         f"; the evidence file says {file_value!r}, but the decision log is the record"
    if bad:
        return "fail", f"{len(bad)} override(s) in the decision log without an engineer or reason{note}"
    if not overrides:
        return "pass", f"no engineer overrides recorded for this vehicle{note}"
    return "pass", f"{len(overrides)} engineer override(s) in the decision log, each with engineer and reason{note}"


def check_vehicle(vehicle_id: str, evidence: dict, harvest: tuple[str, ...] | None,
                  converter_present: bool, photos_missing: dict[str, int], rules: pd.DataFrame,
                  overrides: list | None = None) -> VehicleCompliance:
    """harvest=None means not yet planned: harvest-dependent rules are reported as pending (n/a)."""
    out = []
    for r in rules.itertuples(index=False):
        f, v = r.evidence_field, evidence.get(r.evidence_field)
        stage = STAGE[f]

        def res(status, detail):
            out.append(RuleResult(r.rule_id, r.severity, stage, status, detail, r.check, r.source))

        if f == "overrides_logged":
            res(*_overrides_logged(overrides or [], v))
        elif f == "pgm_recycler_id" and not converter_present:
            res("n/a", "no catalytic converter on the vehicle at intake")
        elif f in ABOUT_HARVEST and harvest is None:
            res("n/a", "pending: harvest not planned yet")
        elif f in ABOUT_HARVEST and not harvest:
            res("n/a", "nothing harvested")
        elif f == "grading_evidence_complete" and _present(v) and photos_missing:
            gaps = ", ".join(f"{n} on {u}" for u, n in photos_missing.items())
            res("fail", f"evidence file says complete, but grading found photos missing ({gaps})")
        elif _present(v):
            res("pass", f"{f} = {v}")
        else:
            res("fail", f"{f} missing" if not isinstance(v, str) or not v.strip() else f"{f} = {v}")
    return VehicleCompliance(vehicle_id, tuple(out))


def check_month(harvests: dict[str, tuple[str, ...]] | None = None, grades: pd.DataFrame | None = None,
                rules: pd.DataFrame | None = None, decisions: list | None = None) -> dict[str, VehicleCompliance]:
    """Check every vehicle. harvests=None checks dismantle-stage rules only (before planning).
    decisions: the engineer decision log, for C08."""
    rules = load_rule_pack(rules)
    ev = pd.read_csv(DATA / "compliance_evidence.csv", dtype=str).fillna("").set_index("vehicle_id")
    comp = pd.read_csv(DATA / "components.csv")
    veh = pd.read_csv(DATA / "vehicles.csv")
    missing_ev = sorted(set(veh.vehicle_id) - set(ev.index))
    if missing_ev:
        raise ComplianceError(f"No evidence record for {missing_ev}")
    if grades is None:
        from app.engines.grading import grade_inspections
        grades = grade_inspections()
    no_photo = grades[grades["flags"].str.contains(NO_PHOTO)].groupby(["vehicle_id", "unit_type"]).size()

    out = {}
    for vid in veh.vehicle_id:
        cat = comp[(comp.vehicle_id == vid) & (comp.component == "catalytic_converter")]
        harvest = None if harvests is None else tuple(harvests[vid])
        units = [UNIT_OF[c] for c in (harvest or ()) if c in UNIT_OF]
        photos = {u: int(no_photo[(vid, u)]) for u in units if (vid, u) in no_photo.index}
        overrides = [d for d in (decisions or []) if d.vehicle_id == vid and d.action.startswith(OVERRIDE_ACTIONS)]
        out[vid] = check_vehicle(vid, ev.loc[vid].to_dict(), harvest,
                                 converter_present=bool(len(cat)) and cat.condition_grade.iloc[0] != "missing",
                                 photos_missing=photos, rules=rules, overrides=overrides)
    return out


def dismantle_blocked(results: dict[str, VehicleCompliance] | None = None) -> set[str]:
    """Vehicles the planner must not touch: a dismantle-stage rule fails."""
    results = check_month() if results is None else results
    return {vid for vid, c in results.items() if not c.can_dismantle}


def month_summary(results: dict[str, VehicleCompliance]) -> pd.DataFrame:
    return pd.DataFrame([dict(
        vehicle=vid, status=c.status, can_dismantle=c.can_dismantle, can_release=c.can_release,
        fails="; ".join(f"{r.rule_id} ({r.severity}) {r.detail}" for r in c.fails),
        not_applicable=" ".join(r.rule_id for r in c.results if r.status == "n/a"),
    ) for vid, c in results.items()])


if __name__ == "__main__":
    from app.engines.planner import plan_harvest

    pd.set_option("display.width", 220, "display.max_colwidth", 110)
    blocked = dismantle_blocked()
    plan = plan_harvest(blocked=blocked)
    print(f"Blocked before dismantling: {sorted(blocked)}\n")
    print(month_summary(check_month(plan.harvests)).to_string(index=False))
