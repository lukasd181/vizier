"""Flag data that looks wrong instead of advising on it.

CivBench hit a favor display stuck at 0 for 200+ turns and a bug that
disabled trade routes. Sanity rules run first; what they mark suspect, the
other rules leave alone.
"""

from __future__ import annotations

from chancellor import benchmarks as bm
from chancellor.models import SEVERITY_INFO, Alert
from chancellor.rules.base import RuleContext, rule


@rule("data_favor", sanity=True)
def favor_stuck(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    if s.turn < bm.scale(100, s.speed_multiplier) or s.favor != 0 or s.favor_per_turn != 0:
        return []
    zeros = [t for t, sm in ctx.history if sm.get("favor") == 0 and sm.get("favor_per_turn") == 0]
    if len(zeros) < 20 or not s.rivals:
        return []
    ctx.suspect.add("favor")
    return [
        Alert(
            rule="data_favor",
            key="favor",
            severity=SEVERITY_INFO,
            category="data",
            title="Diplomatic favor has read 0 for 20+ turns",
            detail="That's unusual this late with civs met. Check the in-game number; the mentor won't advise on favor until it moves.",
            data={"turns_at_zero": len(zeros)},
        )
    ]


@rule("data_trade", sanity=True)
def trade_ghosts(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    if s.trade_ghosts <= 0:
        return []
    ctx.suspect.add("trade_capacity")
    return [
        Alert(
            rule="data_trade",
            key="ghost_routes",
            severity=SEVERITY_INFO,
            category="data",
            title=f"{s.trade_ghosts} trade route record(s) look stale",
            detail="The game reports routes that no trader is running. Idle-route alerts are paused until this clears.",
            data={"ghosts": s.trade_ghosts},
        )
    ]


@rule("data_source", sanity=True)
def source_warnings(ctx: RuleContext) -> list[Alert]:
    if not ctx.source_warnings:
        return []
    return [
        Alert(
            rule="data_source",
            key="warnings",
            severity=SEVERITY_INFO,
            category="data",
            title=f"{len(ctx.source_warnings)} part(s) of the game state couldn't be read",
            detail="; ".join(ctx.source_warnings[:3]),
            data={"warnings": ctx.source_warnings},
        )
    ]
