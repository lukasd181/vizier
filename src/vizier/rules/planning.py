"""Forgotten plans and the wrong victory path.

CivBench agents carried out only 48-66% of their own plans; this turns plans
into checks that fire every turn.
"""

from __future__ import annotations

from vizier import goals
from vizier.models import SEVERITY_INFO, SEVERITY_WARNING, Alert
from vizier.rules.base import RuleContext, rule


@rule("commitment_overdue")
def commitment_overdue(ctx: RuleContext) -> list[Alert]:
    out = []
    for c in ctx.commitments:
        if c.status != "overdue":
            continue
        late = ctx.snap.turn - c.due_turn
        out.append(
            Alert(
                rule="commitment_overdue",
                key=f"commitment={c.id}",
                severity=SEVERITY_WARNING if late >= 5 else SEVERITY_INFO,
                category="planning",
                title=f"Plan overdue by {late} turns: {c.text}",
                detail=f"Due T{c.due_turn}. Do it, reschedule it, or drop it so it stops nagging.",
                data={"commitment_id": c.id, "due_turn": c.due_turn, "check": f"{c.check_kind}:{c.check_arg}"},
                fix_tool="list_commitments",
            )
        )
    return out


@rule("goal_viability")
def goal_viability(ctx: RuleContext) -> list[Alert]:
    g = ctx.goal
    if g is None or g.victory in ("none", "score"):
        return []
    v = goals.viability(g, ctx.snap)
    if v.viable:
        return []
    return [
        Alert(
            rule="goal_viability",
            key=f"goal={g.victory}",
            severity=SEVERITY_WARNING,
            category="planning",
            title=f"Your {g.victory} victory path looks hard to win",
            detail="; ".join(v.reasons) + (f". Worth considering: {', '.join(v.suggest)}." if v.suggest else "."),
            data={"reasons": v.reasons, "alternatives": v.suggest},
            fix_tool="get_goal_status",
            root_cause=4,
        )
    ]
