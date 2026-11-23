"""Early-game tempo: the small efficiencies pros never miss.

From Herson's "Civ 6 Overexplained: How to play the early game like a Pro"
(multiplayer meta) and Ursa Ryan's Deity science playthrough, both 2025-26:

* Never finish a tech or civic before its eureka/inspiration — research
  something else while you set the boost up.
* District costs rise with your tech/civic progress until you place one, so
  place each newly unlocked district type right away to lock its price.
* Serfdom (+2 builder charges) is "game-definingly strong": slot it the turn
  Feudalism lands. Swap God King out once the pantheon is in.
* Use every governor title; the Government Plaza's Audience Chamber makes
  spreading them around worth food and housing.
"""

from __future__ import annotations

from chancellor.models import SEVERITY_INFO, SEVERITY_WARNING, Alert
from chancellor.rules.base import RuleContext, rule


def _pretty(t: str) -> str:
    for pre in ("TECH_", "CIVIC_", "DISTRICT_", "POLICY_"):
        if t.startswith(pre):
            t = t[len(pre):]
    return t.replace("_", " ").title()


@rule("eureka_guard")
def eureka_guard(ctx: RuleContext) -> list[Alert]:
    """Finishing (or nearly finishing) an item before its boost wastes the boost:
    the eureka adds boost_pct% of the cost, and anything past 100% is lost."""
    out = []
    for kind, r in ctx.snap.research.items():
        if not r or r.get("boosted") or not r.get("boost_pct") or r.get("cost", 0) <= 0:
            continue
        pct = 100 * r["progress"] / r["cost"]
        wasted_from = 100 - r["boost_pct"]
        if pct < wasted_from:
            continue
        name = _pretty(r["item"])
        word = "eureka" if kind == "tech" else "inspiration"
        out.append(
            Alert(
                rule="eureka_guard",
                key=f"{kind}={r['item']}",
                severity=SEVERITY_WARNING,
                category="economy",
                title=f"{name} is {pct:.0f}% done without its {word}",
                detail=(
                    f"The {word} is worth {r['boost_pct']}% of the cost; past {wasted_from}% progress some of it is wasted. "
                    f"Switch to another {'tech' if kind == 'tech' else 'civic'} until you trigger it"
                    + (f" ({r['trigger']})." if r.get("trigger") else ".")
                ),
                data=r | {"kind": kind, "percent": round(pct, 1)},
            )
        )
    return out


@rule("district_lock_in")
def district_lock_in(ctx: RuleContext) -> list[Alert]:
    rows = ctx.snap.unplaced_districts
    if not rows or not ctx.snap.cities:
        return []
    gov = next((r for r in rows if r["district"] == "DISTRICT_GOVERNMENT"), None)
    names = ", ".join(f"{_pretty(r['district'])} ({r['cost']} in {r['city']})" for r in rows[:5])
    detail = (
        f"Unlocked but placed in no city: {names}. District costs keep rising with every tech and civic you finish "
        "until you place one; placing it locks the price, and you can switch back to other production."
    )
    if gov:
        detail += " Pros place the Government Plaza very early: it's cheaper than other districts and gives a governor title."
    return [
        Alert(
            rule="district_lock_in",
            key="unplaced",
            severity=SEVERITY_INFO,
            category="economy",
            title=f"Lock in district costs: {len(rows)} type(s) unlocked and not placed",
            detail=detail,
            data={"districts": rows},
        )
    ]


@rule("policy_swaps")
def policy_swaps(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    out = []
    if (
        "CIVIC_FEUDALISM" in s.civics
        and "POLICY_SERFDOM" in s.available_policies
        and "POLICY_SERFDOM" not in s.slotted_policies
    ):
        out.append(
            Alert(
                rule="policy_swaps",
                key="serfdom",
                severity=SEVERITY_WARNING,
                category="economy",
                title="Slot Serfdom: new builders get +2 charges",
                detail=(
                    "Builders cost more each time you make one, so Serfdom (3 → 5 charges) roughly halves the "
                    "production per charge. This is the moment to build builders everywhere and chop."
                ),
                data={},
            )
        )
    if s.has_pantheon and "POLICY_GOD_KING" in s.slotted_policies:
        out.append(
            Alert(
                rule="policy_swaps",
                key="god_king",
                severity=SEVERITY_INFO,
                category="economy",
                title="Swap out God King: you already have your pantheon",
                detail="God King's job was the faith for a pantheon. Urban Planning (+1 production in every city) is better now.",
                data={},
            )
        )
    return out


@rule("governor_titles")
def governor_titles(ctx: RuleContext) -> list[Alert]:
    g = ctx.snap.governors
    if not g:
        return []
    bits = []
    if g.get("can_appoint"):
        bits.append("a new governor can be appointed")
    if g.get("can_promote"):
        bits.append("a governor can be promoted")
    if g.get("unassigned", 0) > 0:
        bits.append(f"{g['unassigned']} appointed governor(s) aren't assigned to a city")
    if not bits:
        return []
    return [
        Alert(
            rule="governor_titles",
            key="titles",
            severity=SEVERITY_INFO,
            category="city",
            title="Unused governor title" + ("s" if len(bits) > 1 else ""),
            detail=(
                "; ".join(bits).capitalize()
                + ". Governors take turns to establish, so the clock only starts once they're placed. "
                "With the Audience Chamber, every city with a governor gets +3 food and +3 housing."
            ),
            data=dict(g),
        )
    ]
