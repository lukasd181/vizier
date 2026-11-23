"""Benchmarks the empire is compared against.

City-count thresholds come from CivBench's cross-game analysis of games 1-4
(civ6-mcp docs/cross-game-analysis.md): city 2 by T30-40, city 3 by T50-75,
city 4 by T80-100, gold over 500. Everything marked PROVISIONAL is a working
estimate to check against replay data before trusting it.

All turn numbers are for Standard speed and scale with the game's
speed_cost_multiplier (67 Quick, 100 Standard, 150 Epic, 300 Marathon).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Milestone:
    value: float
    turn_lo: int  # benchmark window, Standard speed
    turn_hi: int
    provisional: bool = False


CITY_MILESTONES: tuple[Milestone, ...] = (
    Milestone(1, 1, 3, provisional=True),  # found the capital; each turn waiting costs yields
    Milestone(2, 30, 40),
    Milestone(3, 50, 75),
    Milestone(4, 80, 100),
    Milestone(6, 120, 150, provisional=True),
)

# PROVISIONAL "pro" pace, read off one Deity science game by Ursa Ryan
# ("Every Decision Explained", Aug 2025): 4 cities by mid-Classical, 7 at the
# start of the Medieval era, 12-15 by its end, 16 by the Industrial era. He
# starts behind Deity AIs, so on lower difficulties this is beatable.
PRO_CITY_MILESTONES: tuple[Milestone, ...] = (
    Milestone(1, 1, 3, provisional=True),
    Milestone(2, 15, 25, provisional=True),
    Milestone(4, 45, 60, provisional=True),
    Milestone(7, 75, 90, provisional=True),
    Milestone(12, 110, 130, provisional=True),
    Milestone(16, 140, 165, provisional=True),
)
PACES = ("minimum", "pro")


def city_milestones(pace: str = "minimum") -> tuple[Milestone, ...]:
    return PRO_CITY_MILESTONES if pace == "pro" else CITY_MILESTONES


# PROVISIONAL: CivBench calls 9% at T40, 11% at T70 and 34% at T160 failures
# but gives no target; these sit comfortably above those.
EXPLORATION_MILESTONES: tuple[Milestone, ...] = (
    Milestone(15, 30, 40, provisional=True),
    Milestone(25, 60, 80, provisional=True),
    Milestone(35, 100, 120, provisional=True),
)

FIRST_DISTRICT_TURN = 60  # PROVISIONAL: CivBench game 1 had none by T75
IDLE_GOLD = 500
# Early on even a few hundred gold is lost tempo: a trader, a builder or a
# monument now beats gold later (both pros: "don't float gold early").
IDLE_GOLD_EARLY = 200
IDLE_GOLD_EARLY_UNTIL = 60
IDLE_FAITH = 500  # PROVISIONAL: CivBench games ended with 876-9,599 idle faith
CHECKPOINT_EVERY = 10

# District each victory path leans on (for "missing district types").
VICTORY_DISTRICTS: dict[str, tuple[str, ...]] = {
    "science": ("DISTRICT_CAMPUS",),
    "culture": ("DISTRICT_THEATER",),
    "religious": ("DISTRICT_HOLY_SITE",),
    "diplomatic": ("DISTRICT_COMMERCIAL_HUB",),
    "domination": ("DISTRICT_ENCAMPMENT",),
}

VICTORY_TYPES: dict[str, str] = {
    "science": "VICTORY_TECHNOLOGY",
    "culture": "VICTORY_CULTURE",
    "religious": "VICTORY_RELIGIOUS",
    "diplomatic": "VICTORY_DIPLOMATIC",
    "domination": "VICTORY_CONQUEST",
    "score": "VICTORY_SCORE",
}


def scale(turn: int, speed_multiplier: int) -> int:
    return round(turn * (speed_multiplier or 100) / 100)


def milestone_gap(
    milestones: tuple[Milestone, ...], current: float, turn: int, speed_multiplier: int
) -> tuple[Milestone, int] | None:
    """The most overdue milestone not yet reached, and how many turns past
    its window's upper bound we are. None if on track."""
    worst: tuple[Milestone, int] | None = None
    for m in milestones:
        deadline = scale(m.turn_hi, speed_multiplier)
        if current < m.value and turn > deadline:
            late = turn - deadline
            if worst is None or late > worst[1]:
                worst = (m, late)
    return worst


def next_milestone(
    milestones: tuple[Milestone, ...], current: float, speed_multiplier: int
) -> tuple[Milestone, int] | None:
    for m in milestones:
        if current < m.value:
            return m, scale(m.turn_hi, speed_multiplier)
    return None


def early_game(turn: int, speed_multiplier: int) -> bool:
    """Exploration and expansion alerts outrank others in this phase."""
    return turn < scale(100, speed_multiplier)
