"""Civilians in danger, barbarian camps, and military balance — from visible units only."""

from __future__ import annotations

from vizier.models import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING, Alert
from vizier.rules.base import RuleContext, rule


@rule("civilian_at_risk")
def civilian_at_risk(ctx: RuleContext) -> list[Alert]:
    out = []
    for u in ctx.snap.civilians:
        if u.threat_distance is None or u.threat_distance > 2:
            continue
        pretty = u.unit_type.replace("UNIT_", "").replace("_", " ").title()
        out.append(
            Alert(
                rule="civilian_at_risk",
                key=f"unit={u.unit_id}",
                severity=SEVERITY_CRITICAL if u.unit_type == "UNIT_SETTLER" else SEVERITY_WARNING,
                category="military",
                title=f"{pretty} at ({u.x},{u.y}) is {u.threat_distance} tile{'s' if u.threat_distance > 1 else ''} from {u.threat_desc}",
                detail="Civilians have no combat strength; one move and it's captured. Move it toward a city or escort it.",
                data={"unit_id": u.unit_id, "x": u.x, "y": u.y, "distance": u.threat_distance, "threat": u.threat_desc},
                root_cause=3,
            )
        )
    return out


@rule("barbarian_camp")
def barbarian_camp(ctx: RuleContext) -> list[Alert]:
    out = []
    for c in ctx.camps:
        if c["distance"] > 8:
            continue
        age = ctx.snap.turn - c["first_seen_turn"]
        sev = SEVERITY_WARNING if c["distance"] <= 5 else SEVERITY_INFO
        seen = "in sight now" if c["last_seen_turn"] == ctx.snap.turn else f"last seen T{c['last_seen_turn']}"
        out.append(
            Alert(
                rule="barbarian_camp",
                key=f"camp={c['x']},{c['y']}",
                severity=sev,
                category="military",
                title=f"Barbarian camp {c['distance']} tiles from your nearest city",
                detail=(
                    f"At ({c['x']},{c['y']}), {seen}, known for {age} turns. "
                    "Camps send stronger units the longer they stand; clearing one early is cheap."
                ),
                data=c,
                root_cause=3,
            )
        )
    return out


@rule("military_balance")
def military_balance(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    if s.our_military_strength <= 0:
        return []
    out = []
    for r in s.rivals:
        ratio = r.military_strength / s.our_military_strength
        if r.at_war and ratio >= 1.5:
            sev = SEVERITY_CRITICAL
        elif ratio >= 2.0:
            sev = SEVERITY_WARNING
        else:
            continue
        out.append(
            Alert(
                rule="military_balance",
                key=f"player={r.player_id}",
                severity=sev,
                category="military",
                title=f"{r.name} has {ratio:.1f}x your military" + (" and is at war with you" if r.at_war else ""),
                detail=f"Strength {r.military_strength} vs your {s.our_military_strength}.",
                data={"player_id": r.player_id, "theirs": r.military_strength, "ours": s.our_military_strength, "at_war": r.at_war},
                fix_tool="get_rivals",
                root_cause=3,
            )
        )
    return out
