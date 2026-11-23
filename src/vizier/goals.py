"""Goal status: progress against benchmarks and when to change course.

Code computes; Claude explains. The viability checks are pivot rules from
CivBench's lesson "stuck on an unwinnable victory path" (3 of 4 games), e.g.
under 4 cities at T100 means science isn't viable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vizier import benchmarks as bm
from vizier.models import Commitment, EmpireSnapshot, Goal

VICTORIES = ("science", "culture", "religious", "diplomatic", "domination", "score", "none")
HELP_LEVELS = ("off", "watchdog", "advisor", "coach")


@dataclass
class Viability:
    viable: bool
    reasons: list[str] = field(default_factory=list)
    suggest: list[str] = field(default_factory=list)


def viability(goal: Goal, s: EmpireSnapshot) -> Viability:
    v = Viability(True)
    t = s.turn
    T = lambda n: bm.scale(n, s.speed_multiplier)  # noqa: E731
    vtype = bm.VICTORY_TYPES.get(goal.victory)
    if vtype and s.enabled_victories and vtype not in s.enabled_victories:
        return Viability(False, [f"{goal.victory} victory is disabled in this game"], [])

    if goal.victory == "science":
        if t >= T(100) and len(s.cities) < 4:
            v.viable = False
            v.reasons.append(f"{len(s.cities)} cities at T{t}; science needs 4+ cities with campus chains")
        leader = max((r for r in s.rivals if r.science_vp > 0), key=lambda r: r.science_vp, default=None)
        if leader and s.our_science_vp == 0 and leader.science_vp >= 2:
            v.reasons.append(f"{leader.name} already has {leader.science_vp} space race points; you have none")
    elif goal.victory == "religious":
        if not s.our_religion and s.religions_max and s.religions_founded >= s.religions_max:
            v.viable = False
            v.reasons.append(f"all {s.religions_max} religions are founded and none is yours")
    elif goal.victory == "culture":
        theaters = sum("DISTRICT_THEATER" in c.districts for c in s.cities)
        if t >= T(120) and theaters == 0:
            v.reasons.append(f"no Theater Squares at T{t}")
    elif goal.victory == "diplomatic":
        if t >= T(120) and s.favor_per_turn <= 0:
            v.reasons.append("no diplomatic favor income; friendships, alliances and suzerainties produce it")
    elif goal.victory == "domination":
        strongest = max((r.military_strength for r in s.rivals), default=0)
        if s.our_military_strength and strongest > 2 * s.our_military_strength:
            v.reasons.append(f"the strongest rival you know has {strongest / s.our_military_strength:.1f}x your military")

    if not v.viable or len(v.reasons) >= 2:
        v.viable = False
        v.suggest = _alternatives(goal.victory, s)
    return v


def _alternatives(current: str, s: EmpireSnapshot) -> list[str]:
    alts = []
    if current != "diplomatic" and s.victory_enabled("VICTORY_DIPLOMATIC") and s.favor_per_turn > 0:
        alts.append("diplomatic (you have favor income)")
    if current != "culture" and s.victory_enabled("VICTORY_CULTURE") and any("DISTRICT_THEATER" in c.districts for c in s.cities):
        alts.append("culture (you have Theater Squares)")
    if current != "religious" and s.our_religion and s.victory_enabled("VICTORY_RELIGIOUS"):
        alts.append(f"religious (you founded {s.our_religion})")
    if current != "science" and len(s.cities) >= 6 and s.victory_enabled("VICTORY_TECHNOLOGY"):
        alts.append("science (you have the cities for it)")
    return alts


def status(goal: Goal | None, s: EmpireSnapshot, commitments: list[Commitment]) -> dict[str, Any]:
    out: dict[str, Any] = {"turn": s.turn, "goal": goal.victory if goal else None}
    n = len(s.cities)
    pace = goal.pace if goal else "minimum"
    ms = bm.city_milestones(pace)
    gap = bm.milestone_gap(ms, n, s.turn, s.speed_multiplier)
    nxt = bm.next_milestone(ms, n, s.speed_multiplier)
    out["cities"] = {
        "pace": pace,
        "have": n,
        "behind_by_turns": gap[1] if gap else 0,
        "next": {"cities": nxt[0].value, "by_turn": nxt[1]} if nxt else None,
    }
    egap = bm.milestone_gap(bm.EXPLORATION_MILESTONES, s.explored_pct, s.turn, s.speed_multiplier)
    out["exploration"] = {
        "explored_pct": round(s.explored_pct, 1),
        "behind_by_turns": egap[1] if egap else 0,
        "provisional": True,
    }
    out["districts"] = sum(c.specialty_districts for c in s.cities)
    if goal and goal.victory not in ("none", "score"):
        v = viability(goal, s)
        out["viability"] = {"viable": v.viable, "reasons": v.reasons, "consider": v.suggest}
        out["progress"] = _goal_progress(goal.victory, s)
    out["commitments"] = {
        "open": sum(c.status == "open" for c in commitments),
        "overdue": sum(c.status == "overdue" for c in commitments),
        "done": sum(c.status == "done" for c in commitments),
    }
    return out


def _goal_progress(victory: str, s: EmpireSnapshot) -> dict[str, Any]:
    if victory == "science":
        best = max((r.science_vp for r in s.rivals), default=0)
        return {"you": f"{s.our_science_vp}/{s.our_science_vp_needed or '?'} VP", "best_rival_vp": best}
    if victory == "diplomatic":
        best = max((r.diplomatic_vp for r in s.rivals), default=0)
        return {"you": f"{s.our_diplomatic_vp}/20 DVP", "best_rival_dvp": best, "favor_per_turn": s.favor_per_turn}
    if victory == "religious":
        return {"your_religion": s.our_religion or None, "religions": f"{s.religions_founded}/{s.religions_max}"}
    if victory == "culture":
        best = max((r.tourism for r in s.rivals), default=0)
        return {"your_tourism": s.our_tourism, "best_rival_tourism": best}
    if victory == "domination":
        best = max((r.military_strength for r in s.rivals), default=0)
        return {"your_military": s.our_military_strength, "best_rival_military": best}
    return {}


# -- commitments ----------------------------------------------------------

CHECK_KINDS = ("manual", "city_count", "tech", "civic", "district", "building", "government", "explored_pct")


def check_commitment(c: Commitment, s: EmpireSnapshot) -> bool | None:
    """True if the commitment's condition holds now, None if it can't be checked."""
    k, a = c.check_kind, c.check_arg.strip()
    if k == "manual":
        return None
    if k == "city_count":
        return len(s.cities) >= int(a)
    if k == "tech":
        return a in s.techs
    if k == "civic":
        return a in s.civics
    if k == "government":
        return s.government == a
    if k == "explored_pct":
        return s.explored_pct >= float(a)
    if k in ("district", "building"):
        # "CityName:DISTRICT_CAMPUS" or just "DISTRICT_CAMPUS" (any city)
        city, _, item = a.rpartition(":")
        for cv in s.cities:
            if city and cv.name.lower() != city.lower():
                continue
            if item in (cv.districts if k == "district" else cv.buildings):
                return True
        return False
    return None


def refresh_commitments(commitments: list[Commitment], s: EmpireSnapshot) -> list[tuple[Commitment, str]]:
    """Return (commitment, new_status) for every status change this turn."""
    changes = []
    for c in commitments:
        if c.status in ("done", "dropped"):
            continue
        ok = check_commitment(c, s)
        if ok:
            changes.append((c, "done"))
        elif c.status == "open" and s.turn > c.due_turn:
            changes.append((c, "overdue"))
    return changes
