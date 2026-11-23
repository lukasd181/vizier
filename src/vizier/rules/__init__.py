"""The turn watcher's rule engine.

Deterministic code runs every rule every turn and ranks the results; Claude
decides which matter now and explains why. Ranking, from the spec:
  * severity first (critical > warning > info);
  * early game, by root cause — exploration and expansion lead because the
    CivBench failure chain starts there;
  * later, by category (victory threats, then cities, then the rest);
  * at most 3 per turn, filtered by help level, minus snoozed alerts and
    rules the player keeps dismissing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vizier import benchmarks as bm
from vizier.models import SEVERITY_CRITICAL, Alert
from vizier.rules import diplomacy, empire, era, expansion, planning, safety, sanity, tempo, victory  # noqa: F401  (registers rules)
from vizier.rules.base import RULES, SANITY_RULES, RuleContext

MAX_ALERTS = 3
WATCHDOG_RULES = frozenset({"rival_victory", "loyalty"})
CATEGORY_ORDER = {
    "victory": 0,
    "city": 1,
    "military": 2,
    "era": 3,
    "expansion": 3.5,
    "planning": 4,
    "economy": 5,
    "diplomacy": 6,
    "data": 7,
}
# A rule the player dismissed this many times, at this share of the times it
# was shown, is retired for the rest of the game (unless critical).
RETIRE_MIN_DISMISSALS = 5
RETIRE_DISMISS_RATE = 0.8


@dataclass
class Review:
    turn: int
    top: list[Alert]
    all: list[Alert]
    suppressed: dict[str, str] = field(default_factory=dict)  # alert_id -> reason
    errors: list[str] = field(default_factory=list)


def run_rules(ctx: RuleContext) -> tuple[list[Alert], list[str]]:
    alerts: list[Alert] = []
    errors: list[str] = []
    for name, fn in SANITY_RULES + RULES:
        try:
            alerts.extend(fn(ctx))
        except Exception as e:  # one broken rule must not hide the others
            errors.append(f"{name}: {type(e).__name__}: {e}")
    return alerts, errors


def sort_key(a: Alert, early: bool) -> tuple:
    secondary = a.root_cause if early else CATEGORY_ORDER.get(a.category, 9)
    tertiary = CATEGORY_ORDER.get(a.category, 9) if early else a.root_cause
    return (a.severity, secondary, tertiary, a.id)


def review(
    ctx: RuleContext,
    help_level: str = "advisor",
    snoozed: set[str] | None = None,
    dismiss_counts: dict[str, int] | None = None,
    shown_counts: dict[str, int] | None = None,
) -> Review:
    alerts, errors = run_rules(ctx)
    early = bm.early_game(ctx.snap.turn, ctx.snap.speed_multiplier)
    alerts.sort(key=lambda a: sort_key(a, early))

    snoozed = snoozed or set()
    dismiss_counts = dismiss_counts or {}
    shown_counts = shown_counts or {}
    suppressed: dict[str, str] = {}
    eligible: list[Alert] = []
    for a in alerts:
        if help_level == "off":
            suppressed[a.id] = "help level off"
            continue
        if help_level == "watchdog" and not (a.severity == SEVERITY_CRITICAL and a.rule in WATCHDOG_RULES):
            suppressed[a.id] = "watchdog shows only critical victory and loyalty alerts"
            continue
        if a.id in snoozed and a.severity != SEVERITY_CRITICAL:
            suppressed[a.id] = "snoozed"
            continue
        d, shown = dismiss_counts.get(a.rule, 0), shown_counts.get(a.rule, 0)
        if a.severity != SEVERITY_CRITICAL and d >= RETIRE_MIN_DISMISSALS and shown and d / shown >= RETIRE_DISMISS_RATE:
            suppressed[a.id] = f"rule retired: dismissed {d} of {shown} times"
            continue
        eligible.append(a)
    return Review(turn=ctx.snap.turn, top=eligible[:MAX_ALERTS], all=alerts, suppressed=suppressed, errors=errors)
