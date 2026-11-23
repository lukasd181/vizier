"""Era score: golden ages to chase, dark ages to dodge.

Pro players plan around era score (a ten-turn countdown at the end of each
era); Vizier only alerts once the game's own countdown is running, using the
game's thresholds from the overview.
"""

from __future__ import annotations

from vizier.models import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING, Alert
from vizier.rules.base import RuleContext, rule

# How close to the golden threshold is worth a nudge.
GOLDEN_REACH = 6

ERA_SCORE_TIPS = (
    "districts with high adjacency (Campus +3, Commercial Hub/Harbor +4, Holy Site +3)",
    "settling near a natural wonder or on new terrain",
    "first-of-a-kind moments: first district of a type, first government, meeting civs",
    "clearing barbarian camps and tribal villages",
)


@rule("era_score")
def era_score(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    left = s.era_countdown
    if left <= 0 or s.era_golden_threshold <= 0:
        return []
    score, dark, golden = s.era_score, s.era_dark_threshold, s.era_golden_threshold
    tips = "Era score sources: " + "; ".join(ERA_SCORE_TIPS) + "."
    if score < dark:
        need = dark - score
        return [
            Alert(
                rule="era_score",
                key="dark",
                severity=SEVERITY_CRITICAL if left <= 3 else SEVERITY_WARNING,
                category="era",
                title=f"Dark Age risk: {need} more era score needed in {left} turn(s)",
                detail=f"Era score {score}; a normal age needs {dark}, a golden age {golden}. {tips}",
                data={"score": score, "dark": dark, "golden": golden, "turns_left": left},
                root_cause=3,
            )
        ]
    if score < golden and golden - score <= GOLDEN_REACH:
        need = golden - score
        return [
            Alert(
                rule="era_score",
                key="golden",
                severity=SEVERITY_INFO,
                category="era",
                title=f"{need} era score from a Golden Age, {left} turn(s) left",
                detail=f"Era score {score} of {golden}. {tips}",
                data={"score": score, "dark": dark, "golden": golden, "turns_left": left},
                root_cause=3,
            )
        ]
    return []
