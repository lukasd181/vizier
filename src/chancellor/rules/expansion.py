"""The upstream end of CivBench's failure chain: exploration and expansion.

Poor exploration → slow expansion → fewer cities → an unwinnable victory.
These carry low root_cause numbers so they lead the list in the early game.
"""

from __future__ import annotations

from chancellor import benchmarks as bm
from chancellor.models import SEVERITY_INFO, SEVERITY_WARNING, Alert
from chancellor.rules.base import RuleContext, rule


def amenity_headroom_low(s) -> bool:
    """Most cities sit at 0 or fewer spare amenities, so another city (which
    adds demand and gets nothing new) would tip the empire into unhappiness."""
    n = len(s.cities)
    if n < 3:
        return False
    tight = sum(1 for c in s.cities if c.net_amenities <= 0)
    return tight * 2 >= n


@rule("expansion")
def expansion(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    n = len(s.cities)
    pace = ctx.goal.pace if ctx.goal else "minimum"
    gap = bm.milestone_gap(bm.city_milestones(pace), n, s.turn, s.speed_multiplier)
    if gap is None:
        return []
    m, late = gap
    lo, hi = bm.scale(m.turn_lo, s.speed_multiplier), bm.scale(m.turn_hi, s.speed_multiplier)
    if n == 0:
        return [
            Alert(
                rule="expansion",
                key="capital",
                severity=SEVERITY_WARNING,
                category="expansion",
                title=f"No capital yet at turn {s.turn}",
                detail="Every turn the settler waits is a turn of lost yields; a decent spot now usually beats a perfect one later.",
                data={"cities": 0, "turns_late": late},
                root_cause=2,
            )
        ]
    return [
        Alert(
            rule="expansion",
            key=f"cities<{int(m.value)}",
            severity=SEVERITY_WARNING,
            category="expansion",
            title=f"{n} cities at turn {s.turn} — city {int(m.value)} is {late} turns late",
            detail=(
                f"{'Pro' if pace == 'pro' else 'Benchmark'} pace: city {int(m.value)} by T{lo}-{hi}"
                + (" (provisional)" if m.provisional else "")
                + (
                    ". Most of your cities have no spare amenities, so line up a new luxury with the next settler."
                    if amenity_headroom_low(s)
                    else ". A settler is usually the highest-leverage build until you catch up."
                )
            ),
            data={"cities": n, "milestone": m.value, "turns_late": late, "window": [lo, hi], "pace": pace},
            root_cause=2,
        )
    ]


@rule("settle_amenities")
def settle_amenities(ctx: RuleContext) -> list[Alert]:
    """Warn before a new city pushes an amenity-starved empire into unhappiness
    (a pro player pauses settling until the luxuries are there)."""
    s = ctx.snap
    settling = any(u.unit_type == "UNIT_SETTLER" for u in s.units) or any(
        c.currently_building == "UNIT_SETTLER" for c in s.cities
    )
    if not settling or not amenity_headroom_low(s):
        return []
    tight = [c.name for c in s.cities if c.net_amenities <= 0]
    return [
        Alert(
            rule="settle_amenities",
            key="headroom",
            severity=SEVERITY_INFO,
            category="city",
            title=f"{len(tight)} of {len(s.cities)} cities have no spare amenities before your next city",
            detail=(
                f"No spare amenities in: {', '.join(tight[:6])}. A new city adds demand. "
                "Improve or trade for a new luxury type alongside the settler (get_amenity_options)."
            ),
            data={"tight_cities": tight},
            fix_tool="get_amenity_options",
            root_cause=2,
        )
    ]


@rule("exploration")
def exploration(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    out = []
    if s.total_land > 0:
        gap = bm.milestone_gap(bm.EXPLORATION_MILESTONES, s.explored_pct, s.turn, s.speed_multiplier)
        if gap is not None:
            m, late = gap
            out.append(
                Alert(
                    rule="exploration",
                    key="explored",
                    severity=SEVERITY_WARNING,
                    category="expansion",
                    title=f"Only {s.explored_pct:.0f}% of land explored",
                    detail=(
                        f"Provisional benchmark: {m.value:.0f}% by T{bm.scale(m.turn_hi, s.speed_multiplier)}. "
                        "Unexplored land hides settle sites, civs to meet and barbarian camps."
                    ),
                    data={"explored_pct": round(s.explored_pct, 1), "target_pct": m.value, "turns_late": late},
                    root_cause=1,
                )
            )
    # Grace period: nobody has had time to build a scout on turn 1.
    early_enough = bm.scale(10, s.speed_multiplier) <= s.turn < bm.scale(150, s.speed_multiplier)
    if not s.recon_units and early_enough and s.explored_pct < 60:
        out.append(
            Alert(
                rule="exploration",
                key="no_scout",
                severity=SEVERITY_INFO if out else SEVERITY_WARNING,
                category="expansion",
                title="No scout is exploring",
                detail="You have no recon units. One scout early pays for itself in settle sites, eurekas and first-meet bonuses.",
                data={"recon_units": 0},
                root_cause=1,
            )
        )
    return out


@rule("districts")
def districts(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    total = sum(c.specialty_districts for c in s.cities)
    out = []
    if total == 0 and s.turn > bm.scale(bm.FIRST_DISTRICT_TURN, s.speed_multiplier):
        out.append(
            Alert(
                rule="districts",
                key="none",
                severity=SEVERITY_WARNING,
                category="expansion",
                title=f"No specialty districts at turn {s.turn}",
                detail=f"Provisional benchmark: first district by T{bm.scale(bm.FIRST_DISTRICT_TURN, s.speed_multiplier)}. Districts are where yields compound.",
                data={"districts": 0},
                root_cause=2,
            )
        )
    goal = ctx.goal
    if goal and goal.victory in bm.VICTORY_DISTRICTS and len(s.cities) >= 2:
        for dtype in bm.VICTORY_DISTRICTS[goal.victory]:
            missing = [c for c in s.cities if c.population >= 3 and dtype not in c.districts]
            have = len(s.cities) - len(missing)
            if missing and have < (len(s.cities) + 1) // 2:
                pretty = dtype.replace("DISTRICT_", "").replace("_", " ").title()
                out.append(
                    Alert(
                        rule="districts",
                        key=f"goal:{dtype}",
                        severity=SEVERITY_INFO,
                        category="expansion",
                        title=f"{have} of {len(s.cities)} cities have a {pretty}",
                        detail=f"Your {goal.victory} plan leans on {pretty}s. Candidates (pop 3+): {', '.join(c.name for c in missing[:5])}.",
                        data={"district": dtype, "missing_city_ids": [c.city_id for c in missing]},
                        root_cause=3,
                    )
                )
    return out
