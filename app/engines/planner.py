"""Harvest planner: which components to pull, across the month, under real limits.

Maximises the total offer the RVSF can make across its vehicles. Every offer is linear in the
harvest gain, so this is the same as maximising the summed net value of the parts pulled.
Limits, all optional:
  - capacity_minutes: technician minutes available for harvesting
  - blocked: vehicles that may not be dismantled (e.g. a red compliance check)
  - exclude / require: (vehicle, component) pairs an engineer has rejected or insisted on

The planner only chooses. The value engine prices every plan, so the numbers have one owner.
With no limits the plan equals the value engine's default rule.

Run:  python -m app.engines.planner        -> the month at full, 75% and 50% of the labour needed
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from ortools.sat.python import cp_model

from app.engines.value import DATA, load_prices, month_table, price_components, value_month

PAISE = 100  # CP-SAT needs integers: net values in paise


class PlanError(ValueError):
    """The limits cannot all be met: never return a plan that breaks one."""


@dataclass(frozen=True)
class Plan:
    harvests: dict[str, tuple[str, ...]]
    minutes: int
    gain: float                 # summed net value of the parts pulled, INR
    status: str                 # OPTIMAL (FEASIBLE is refused)
    dropped: pd.DataFrame       # positive-net parts left on the vehicle, and why


def candidates(vehicles: pd.DataFrame | None = None, components: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every component the value engine allows to be harvested, with its net value and minutes."""
    veh = pd.read_csv(DATA / "vehicles.csv") if vehicles is None else vehicles
    comp = pd.read_csv(DATA / "components.csv") if components is None else components
    prices = load_prices()
    rows = []
    for vid in veh.vehicle_id:
        lines = price_components(comp[comp.vehicle_id == vid], prices)
        lines = lines[lines.status.isin(["harvestable", "not_worth_it"])]
        rows.append(lines.assign(vehicle_id=vid)[["vehicle_id", "component", "net", "minutes", "status"]])
    out = pd.concat(rows, ignore_index=True)
    out.attrs["vehicle_ids"] = list(veh.vehicle_id)  # includes vehicles with nothing to harvest (V09)
    return out


def plan_harvest(cands: pd.DataFrame | None = None, *, capacity_minutes: int | None = None,
                 blocked: set[str] = frozenset(), exclude: set[tuple[str, str]] = frozenset(),
                 require: set[tuple[str, str]] = frozenset(), time_limit_s: float = 10.0) -> Plan:
    cands = candidates() if cands is None else cands
    keys = list(zip(cands.vehicle_id, cands.component))
    unknown = (set(exclude) | set(require)) - set(keys)
    if unknown:
        raise PlanError(f"Not a harvestable part: {sorted(unknown)}")
    clash = {k for k in require if k in exclude or k[0] in blocked}
    if clash:
        raise PlanError(f"Required and also excluded or blocked: {sorted(clash)}")

    m = cp_model.CpModel()
    x = {k: m.NewBoolVar(f"{k[0]}_{k[1]}") for k in keys}
    for k in keys:
        if k[0] in blocked or k in exclude:
            m.Add(x[k] == 0)
        if k in require:
            m.Add(x[k] == 1)
    minutes = dict(zip(keys, cands.minutes.astype(int)))
    if capacity_minutes is not None:
        m.Add(sum(minutes[k] * x[k] for k in keys) <= int(capacity_minutes))
    net = dict(zip(keys, (cands.net * PAISE).round().astype(int)))
    # Best total value first; among equal values, fewer minutes.
    m.Maximize(sum((net[k] * 100_000 - minutes[k]) * x[k] for k in keys))

    s = cp_model.CpSolver()
    s.parameters.num_workers = 1        # deterministic: same data, same plan
    s.parameters.random_seed = 0
    s.parameters.max_time_in_seconds = time_limit_s
    status = s.Solve(m)
    if status == cp_model.INFEASIBLE:
        need = sum(minutes[k] for k in require)
        raise PlanError(f"Limits cannot all be met (required parts alone need {need} min, "
                        f"capacity {capacity_minutes})")
    if status != cp_model.OPTIMAL:
        raise PlanError(f"No proven-optimal plan within {time_limit_s}s ({s.StatusName(status)})")

    chosen = {k for k in keys if s.Value(x[k])}
    harvests = {vid: tuple(c for v, c in keys if v == vid and (v, c) in chosen)
                for vid in dict.fromkeys([*cands.attrs.get("vehicle_ids", []), *cands.vehicle_id])}

    left = cands[[k not in chosen and n > 0 for k, n in zip(keys, cands.net)]].copy()
    left["why"] = [("vehicle blocked" if v in blocked else "engineer excluded" if (v, c) in exclude
                    else "labour capacity") for v, c in zip(left.vehicle_id, left.component)]
    left["net_per_min"] = (left.net / left.minutes).round(1)

    return Plan(harvests, sum(minutes[k] for k in chosen), round(sum(net[k] for k in chosen) / PAISE, 2),
                s.StatusName(status), left.drop(columns="status").reset_index(drop=True))


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    cands = candidates()
    full = plan_harvest(cands).minutes
    for share in (1.0, 0.75, 0.5):
        cap = round(full * share)
        plan = plan_harvest(cands, capacity_minutes=cap)
        t = month_table(value_month(plan.harvests, with_grading=False))
        before = (t.informal - t.offer_scrap_only).mean()
        print(f"\n=== capacity {cap} min ({share:.0%} of {full}): {plan.minutes} min used, "
              f"{sum(map(len, plan.harvests.values()))} parts, gain INR {plan.gain:,.0f}, "
              f"gap closed {100 * (1 - t.gap.mean() / before):.0f}%")
        if len(plan.dropped):
            print("left on the vehicle:")
            print(plan.dropped.to_string(index=False))
