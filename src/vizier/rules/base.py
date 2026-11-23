"""Rule plumbing: one rule = one function from RuleContext to alerts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from vizier.models import Alert, Commitment, EmpireSnapshot, Goal


@dataclass
class RuleContext:
    snap: EmpireSnapshot
    goal: Goal | None = None
    # (turn, summary) pairs from earlier reviews, oldest first
    history: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    commitments: list[Commitment] = field(default_factory=list)
    # Remembered barbarian camps: x, y, distance, first_seen_turn, last_seen_turn
    camps: list[dict[str, Any]] = field(default_factory=list)
    # Values the sanity rules flagged as untrustworthy; other rules skip them.
    suspect: set[str] = field(default_factory=set)
    source_warnings: list[str] = field(default_factory=list)


Rule = Callable[[RuleContext], list[Alert]]

RULES: list[tuple[str, Rule]] = []
SANITY_RULES: list[tuple[str, Rule]] = []


def rule(name: str, *, sanity: bool = False) -> Callable[[Rule], Rule]:
    def deco(fn: Rule) -> Rule:
        (SANITY_RULES if sanity else RULES).append((name, fn))
        return fn

    return deco


def per_turn_rate(
    history: list[tuple[int, dict[str, Any]]], getter: Callable[[dict[str, Any]], float | None], window: int = 10
) -> float | None:
    """Average change per turn of a metric over the last `window` turns."""
    pts = [(t, v) for t, s in history if (v := getter(s)) is not None]
    if len(pts) < 2:
        return None
    last_t = pts[-1][0]
    pts = [(t, v) for t, v in pts if t >= last_t - window]
    if len(pts) < 2 or pts[-1][0] == pts[0][0]:
        return None
    return (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0])


def turns_to_reach(current: float, target: float, rate: float | None) -> int | None:
    if current >= target:
        return 0
    if not rate or rate <= 0:
        return None
    return int(-(-(target - current) // rate))  # ceil
