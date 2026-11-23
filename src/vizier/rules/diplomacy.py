"""Passive diplomacy: friendships, alliances and delegations left on the table.

CivBench game 1: 495 favor, no friendships or alliances in 323 turns.
"""

from __future__ import annotations

from vizier.models import SEVERITY_INFO, Alert
from vizier.rules.base import RuleContext, rule


@rule("diplomacy")
def diplomacy(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    out = []
    friend_ready = [r for r in s.rivals if r.can_declare_friendship and not r.is_friend and not r.at_war]
    if friend_ready:
        out.append(
            Alert(
                rule="diplomacy",
                key="friendship",
                severity=SEVERITY_INFO,
                category="diplomacy",
                title=f"Friendship is available with {', '.join(r.name for r in friend_ready)}",
                detail="Friendships add diplomatic favor every turn and stop surprise wars.",
                data={"player_ids": [r.player_id for r in friend_ready]},
                fix_tool="get_rivals",
            )
        )
    ally_ready = [r for r in s.rivals if r.can_form_alliance and not r.is_ally]
    if ally_ready:
        out.append(
            Alert(
                rule="diplomacy",
                key="alliance",
                severity=SEVERITY_INFO,
                category="diplomacy",
                title=f"An alliance is available with {', '.join(r.name for r in ally_ready)}",
                detail="Alliances share visibility, add favor, and level up into yield bonuses.",
                data={"player_ids": [r.player_id for r in ally_ready]},
                fix_tool="get_rivals",
            )
        )
    no_delegation = [r for r in s.rivals if not r.we_have_delegation and not r.we_have_embassy and not r.at_war]
    if no_delegation and s.gold >= 25:
        out.append(
            Alert(
                rule="diplomacy",
                key="delegation",
                severity=SEVERITY_INFO,
                category="diplomacy",
                title=f"No delegation in {', '.join(r.name for r in no_delegation)}",
                detail="A delegation costs 25 gold and improves relations; it also lets you see their capital.",
                data={"player_ids": [r.player_id for r in no_delegation]},
            )
        )
    if "favor" not in ctx.suspect and s.favor >= 200:
        out.append(
            Alert(
                rule="diplomacy",
                key="favor",
                severity=SEVERITY_INFO,
                category="diplomacy",
                title=f"{s.favor} diplomatic favor unspent",
                detail="Favor buys World Congress votes and can be traded for gold or resources.",
                data={"favor": s.favor, "favor_per_turn": s.favor_per_turn},
            )
        )
    return out
