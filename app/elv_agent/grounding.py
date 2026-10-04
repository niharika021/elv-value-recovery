"""Grounding check: every number in an agent's answer must come from a tool result (or the question).

Identifiers (V05, STR-03, DWG-ALT-08, C06, COD-HR-...) and list markers are not figures and are
ignored. A figure matches if it equals a tool number, the same number rounded to 0-2 decimals, or
a 0-1 fraction shown as a percentage. Anything else is reported, never silently accepted.
"""
from __future__ import annotations

import json
import re

ID = re.compile(r"\b(?:[A-Z]+-)*[A-Z]+-?\d+[A-Z0-9-]*\b")          # V05, STR-03, DWG-STR-03, C06, PGM-31
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
NUMBER = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{2,3})+(?:\.\d+)?(?![\d])|(?<![\w.])\d+(?:\.\d+)?(?![\d])")


def numbers_in_text(text: str) -> list[float]:
    text = LIST_MARKER.sub(" ", ID.sub(" ", text))
    return [float(n.replace(",", "")) for n in NUMBER.findall(text)]


def _walk(x, out: set[float]) -> None:
    if isinstance(x, bool) or x is None:
        return
    if isinstance(x, (int, float)):
        out.add(float(x))
    elif isinstance(x, str):
        out.update(numbers_in_text(x))
    elif isinstance(x, dict):
        for k, v in x.items():
            _walk(k, out)
            _walk(v, out)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _walk(v, out)


def known_numbers(tool_results: list, question: str = "") -> set[float]:
    raw: set[float] = set(numbers_in_text(question))
    for r in tool_results:
        _walk(r if not isinstance(r, str) else json.loads(r) if r.strip().startswith(("{", "[")) else r, raw)
    known = set(raw)
    for n in raw:
        known.update(round(n, d) for d in (0, 1, 2))
        if 0 <= n <= 1:
            known.update({round(100 * n), round(100 * n, 1)})
    return known


def ungrounded(answer: str, tool_results: list, question: str = "") -> list[float]:
    """Numbers in the answer that no tool result (or the question) contains."""
    known = known_numbers(tool_results, question)
    seen, out = set(), []
    for n in numbers_in_text(answer):
        if n not in known and n not in seen:
            seen.add(n)
            out.append(n)
    return out
