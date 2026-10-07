"""Engineer decisions: the only way a human changes what the engines conclude.

Four kinds, all append-only and attributed:
  part_review  accept the grading engine's verdict on a flagged part, override it to another
               verdict, or request further inspection (the part stays on hold)
  harvest      exclude or require a component in the plan (or clear an earlier instruction)
  sign_off     sign a vehicle off; only allowed when nothing is open, and it goes stale if
               anything about the vehicle is decided after it
  rule_review  approve or reject a grading rule Gemini read from a drawing. Only an approved
               rule that passed the fixed gates can grade parts; otherwise the baseline rule does.

Every decision needs a named engineer, and every judgment a reason (compliance C08: overrides
logged with a reason). The log is never edited: the latest decision per target wins and the
history stays. Storage sits behind DecisionStore: a JSON-lines file locally, Firestore on Cloud
Run (make_store picks by ELV_STORE).

Identity is self-declared in this demo; on Cloud Run it should come from the sign-in (IAP).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import pandas as pd

from app.engines.grading import FAIL_VERDICTS

ROOT = Path(__file__).resolve().parents[2]
VERDICTS = {"reuse"} | FAIL_VERDICTS
KINDS = {"part_review", "harvest", "sign_off", "rule_review"}
ACTIONS = {
    "part_review": {"accept", "request_review"} | {f"override:{v}" for v in VERDICTS},
    "harvest": {"exclude", "require", "clear"},
    "sign_off": {"sign"},
    "rule_review": {"approve", "reject"},
}

# What happens to a part once its verdict is final. Fixed: derived from the verdict, never by an LLM.
NEXT_ACTION = {
    "reuse": "Harvest for reuse",
    "replace": "Replace with a new or Grade-A part",
    "refurbish": "Refurbish before reuse",
    "scrap": "Send to the scrap stream",
    "needs_inspection": "Further inspection",
}


class DecisionError(ValueError):
    """A decision that the rules do not allow. It is not recorded."""


@dataclass(frozen=True)
class Decision:
    engineer: str
    kind: str
    vehicle_id: str
    action: str
    reason: str = ""
    target: str = ""                 # part_no (part_review, rule_review), component (harvest), "" (sign_off)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    context: dict = field(default_factory=dict)   # what the engine said at the time, for the audit trail

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.kind, self.vehicle_id, self.target)


class DecisionStore(Protocol):
    def append(self, d: Decision) -> None: ...
    def all(self) -> list[Decision]: ...
    def version(self) -> str: ...


class JsonlStore:
    """Append-only JSON-lines file. Fine for one process; Cloud Run uses Firestore instead."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("ELV_DECISIONS", ROOT / "out" / "decisions.jsonl"))
        self._lock = threading.Lock()

    def append(self, d: Decision) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(d), ensure_ascii=False) + "\n")

    def all(self) -> list[Decision]:
        if not self.path.exists():
            return []
        return [Decision(**json.loads(line)) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def version(self) -> str:
        return f"{len(self.all())}"


class MemoryStore:
    def __init__(self):
        self._d: list[Decision] = []

    def append(self, d: Decision) -> None:
        self._d.append(d)

    def all(self) -> list[Decision]:
        return list(self._d)

    def version(self) -> str:
        return str(len(self._d))


class FirestoreStore:
    """Firestore collection, one document per decision (id = decision id), ordered by a nanosecond
    sequence so decisions in the same second keep their order. Documents are only ever created,
    never updated: create() fails if the id exists, which keeps the log append-only."""

    def __init__(self, collection: str | None = None, client=None):
        if client is None:
            from google.cloud import firestore
            client = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        self.col = client.collection(collection or os.environ.get("ELV_DECISIONS_COLLECTION", "decisions"))
        self._seq = 0

    def append(self, d: Decision) -> None:
        self._seq = max(time.time_ns(), self._seq + 1)
        self.col.document(d.id).create({**asdict(d), "seq": self._seq})

    def all(self) -> list[Decision]:
        docs = [doc.to_dict() for doc in self.col.order_by("seq").stream()]
        return [Decision(**{k: v for k, v in d.items() if k != "seq"}) for d in docs]

    def version(self) -> str:
        last = list(self.col.order_by("seq", direction="DESCENDING").limit(1).stream())
        return f"{last[0].to_dict()['seq']}" if last else "0"


def make_store() -> DecisionStore:
    """ELV_STORE=firestore on Cloud Run (the container's disk does not survive restarts);
    a JSON-lines file otherwise."""
    return FirestoreStore() if os.environ.get("ELV_STORE", "").lower() == "firestore" else JsonlStore()


def latest(decisions: list[Decision]) -> dict[tuple[str, str, str], Decision]:
    out: dict[tuple[str, str, str], Decision] = {}
    for d in decisions:            # log order is time order
        out[d.key] = d
    return out


def validate_shape(d: Decision) -> None:
    """Rules that need nothing but the decision itself."""
    if not d.engineer.strip():
        raise DecisionError("Every decision needs the engineer's name.")
    if d.kind not in KINDS:
        raise DecisionError(f"Unknown kind {d.kind!r}.")
    if d.action not in ACTIONS[d.kind]:
        raise DecisionError(f"{d.kind} cannot {d.action!r}; allowed: {sorted(ACTIONS[d.kind])}.")
    if d.kind != "sign_off" and not d.reason.strip():
        raise DecisionError("A reason is required (compliance C08: decisions logged with a reason).")
    if d.kind == "sign_off" and d.target:
        raise DecisionError("A sign-off is for the whole vehicle; it takes no target.")
    if d.kind != "sign_off" and not d.target:
        raise DecisionError(f"A {d.kind} decision needs a target.")
    if d.kind == "rule_review" and d.vehicle_id:
        raise DecisionError("A drawing-rule decision is for a part number, not a vehicle.")
    if d.kind != "rule_review" and not d.vehicle_id:
        raise DecisionError(f"A {d.kind} decision needs a vehicle.")


# ---- applying decisions to engine outputs --------------------------------------------------

def apply_part_reviews(grades: pd.DataFrame, decisions: list[Decision]) -> pd.DataFrame:
    """Final verdict per part: the engine's, unless an engineer overrode it. A decided part is no
    longer waiting for review; a part sent for further inspection stays open. The engine's own
    verdict is kept beside it, and every part gets its status and next action."""
    g = grades.copy()
    g["engine_verdict"] = g.verdict
    g["decision"], g["decided_by"], g["decision_reason"], g["decided_at"] = "", "", "", ""
    for (kind, vid, part), d in latest(decisions).items():
        if kind != "part_review":
            continue
        m = (g.vehicle_id == vid) & (g.part_no == part)
        if d.action.startswith("override:"):
            g.loc[m, "verdict"] = d.action.split(":", 1)[1]
        g.loc[m, "decision"] = d.action
        g.loc[m, "decided_by"] = d.engineer
        g.loc[m, "decision_reason"] = d.reason
        g.loc[m, "decided_at"] = d.at
        g.loc[m, "needs_review"] = d.action == "request_review"
    outcome = [part_outcome(r) for r in g.to_dict("records")]
    g["status"] = [o[0] for o in outcome]
    g["next_action"] = [o[1] for o in outcome]
    return g


def part_outcome(r: dict) -> tuple[str, str]:
    """(status, next action) for one graded part. Nothing moves while an engineer's call is
    pending: a flagged or unruled part is on hold until it is decided."""
    d, who = r.get("decision") or "", r.get("decided_by") or ""
    if d == "request_review":
        return f"Inspection requested by {who}", "Hold: further inspection"
    if r.get("needs_review"):
        return "Awaiting engineer", "Hold: awaiting engineer decision"
    nxt = NEXT_ACTION.get(r["verdict"], "Hold")
    if d == "accept":
        return f"Approved by {who}", nxt
    if d.startswith("override:"):
        return f"Overridden by {who} (engine said {r.get('engine_verdict')})", nxt
    return "Engine verdict (no review needed)", nxt


def harvest_instructions(decisions: list[Decision]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """(exclude, require) for the planner, from the latest harvest decision per component."""
    exclude, require = set(), set()
    for (kind, vid, comp), d in latest(decisions).items():
        if kind == "harvest" and d.action == "exclude":
            exclude.add((vid, comp))
        elif kind == "harvest" and d.action == "require":
            require.add((vid, comp))
    return exclude, require


def sign_off_for(vehicle_id: str, decisions: list[Decision], parts: set[str] = frozenset()) -> Decision | None:
    """The vehicle's sign-off if it is still current: nothing about the vehicle decided after it,
    including a drawing-rule decision for a part graded on this vehicle (`parts`)."""
    signed = None
    for d in decisions:
        if d.vehicle_id == vehicle_id:
            signed = d if d.kind == "sign_off" else None
        elif d.kind == "rule_review" and d.target in parts:
            signed = None
    return signed
