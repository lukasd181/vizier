"""Missed threats that lose games: rival victory progress, from met civs only.

CivBench: in 8 of 20 losses the agent never checked the visible victory
threat. Thresholds use the game's own Victories.CriticalPercentage where it
has one (gamedata.VICTORY_CRITICAL_PCT).
"""

from __future__ import annotations

from vizier.gamedata import DIPLOMATIC_VICTORY_POINTS_REQUIRED, VICTORY_CRITICAL_PCT
from vizier.models import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING, Alert
from vizier.rules.base import RuleContext, per_turn_rate, rule, turns_to_reach


def _rival_metric(pid: int, key: str):
    def get(summary: dict) -> float | None:
        r = summary.get("rivals", {}).get(str(pid))
        return None if r is None else r.get(key)

    return get


def _eta_text(eta: int | None) -> str:
    if eta is None:
        return "pace unknown (need a few turns of history)"
    if eta == 0:
        return "threshold reached"
    return f"~{eta} turns at the current pace"


@rule("rival_victory")
def rival_victory(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    alerts: list[Alert] = []
    majors = max(s.alive_majors, len(s.rivals) + 1)
    for r in s.rivals:
        # Science: space race victory points
        if s.victory_enabled("VICTORY_TECHNOLOGY") and r.science_vp_needed > 0 and r.science_vp > 0:
            pct = 100 * r.science_vp / r.science_vp_needed
            rate = per_turn_rate(ctx.history, _rival_metric(r.player_id, "sci_vp"))
            eta = turns_to_reach(r.science_vp, r.science_vp_needed, rate)
            sev = SEVERITY_CRITICAL if pct >= VICTORY_CRITICAL_PCT["VICTORY_TECHNOLOGY"] else SEVERITY_WARNING
            alerts.append(
                Alert(
                    rule="rival_victory",
                    key=f"science:player={r.player_id}",
                    severity=sev,
                    category="victory",
                    title=f"{r.name} is in the space race",
                    detail=f"{r.science_vp}/{r.science_vp_needed} science victory points ({pct:.0f}%), {_eta_text(eta)}.",
                    data={"player_id": r.player_id, "vp": r.science_vp, "needed": r.science_vp_needed, "eta_turns": eta},
                    fix_tool="get_rivals",
                    root_cause=0 if sev == SEVERITY_CRITICAL else 4,
                )
            )

        # Religion: majority religion in how many major civs (incl. us)
        if s.victory_enabled("VICTORY_RELIGIOUS") and r.religion_civs_converted > 0 and majors > 1:
            n = r.religion_civs_converted
            pct = 100 * n / majors
            if pct >= 50:
                rate = per_turn_rate(ctx.history, _rival_metric(r.player_id, "rel_civs"), window=20)
                eta = turns_to_reach(n, majors, rate)
                crit = pct >= VICTORY_CRITICAL_PCT["VICTORY_RELIGIOUS"] or n >= majors - 1
                alerts.append(
                    Alert(
                        rule="rival_victory",
                        key=f"religion:player={r.player_id}",
                        severity=SEVERITY_CRITICAL if crit else SEVERITY_WARNING,
                        category="victory",
                        title=f"{r.name}'s {r.religion_name or 'religion'} is spreading",
                        detail=f"Majority religion in {n} of {majors} civilizations; they win at {majors}. {_eta_text(eta)}.",
                        data={"player_id": r.player_id, "civs": n, "majors": majors, "eta_turns": eta},
                        fix_tool="get_rivals",
                        root_cause=0 if crit else 4,
                    )
                )

        # Diplomatic: victory points, win instantly at 20
        if s.victory_enabled("VICTORY_DIPLOMATIC") and r.diplomatic_vp >= 10:
            need = DIPLOMATIC_VICTORY_POINTS_REQUIRED
            pct = 100 * r.diplomatic_vp / need
            if pct >= VICTORY_CRITICAL_PCT["VICTORY_DIPLOMATIC"]:
                sev = SEVERITY_CRITICAL
            elif r.diplomatic_vp >= 15:
                sev = SEVERITY_WARNING
            else:
                sev = SEVERITY_INFO
            rate = per_turn_rate(ctx.history, _rival_metric(r.player_id, "dvp"), window=30)
            alerts.append(
                Alert(
                    rule="rival_victory",
                    key=f"diplomatic:player={r.player_id}",
                    severity=sev,
                    category="victory",
                    title=f"{r.name} has {r.diplomatic_vp}/{need} diplomatic victory points",
                    detail=f"They win the moment they reach {need}, not at the next session. {_eta_text(turns_to_reach(r.diplomatic_vp, need, rate))}.",
                    data={"player_id": r.player_id, "dvp": r.diplomatic_vp},
                    fix_tool="get_rivals",
                    root_cause=0 if sev == SEVERITY_CRITICAL else 4,
                )
            )

        # Culture: civs they dominate, among the ones we know
        known_others = len(s.rivals)  # rivals we've met + us, minus them
        if s.victory_enabled("VICTORY_CULTURE") and r.culture_civs_dominated > 0 and known_others > 0:
            pct = 100 * r.culture_civs_dominated / known_others
            dominates_us = r.our_tourists_from_them > r.our_staycationers
            if pct >= VICTORY_CRITICAL_PCT["VICTORY_CULTURE"] or dominates_us:
                alerts.append(
                    Alert(
                        rule="rival_victory",
                        key=f"culture:player={r.player_id}",
                        severity=SEVERITY_CRITICAL if pct >= VICTORY_CRITICAL_PCT["VICTORY_CULTURE"] else SEVERITY_WARNING,
                        category="victory",
                        title=f"{r.name} is culturally dominant",
                        detail=(
                            f"Dominates {r.culture_civs_dominated} of the {known_others} civs you know of"
                            + (
                                f", including you ({r.our_tourists_from_them} of their tourists vs your {r.our_staycationers} domestic)."
                                if dominates_us
                                else "."
                            )
                        ),
                        data={
                            "player_id": r.player_id,
                            "dominated": r.culture_civs_dominated,
                            "known": known_others,
                            "dominates_us": dominates_us,
                        },
                        fix_tool="get_rivals",
                        root_cause=0 if pct >= 75 else 4,
                    )
                )
    return alerts
