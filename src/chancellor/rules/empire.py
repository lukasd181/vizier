"""City problems and idle resources."""

from __future__ import annotations

from chancellor import benchmarks as bm
from chancellor.gamedata import happiness_for
from chancellor.models import SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_WARNING, Alert
from chancellor.rules.base import RuleContext, rule


@rule("amenities")
def amenities(ctx: RuleContext) -> list[Alert]:
    out = []
    for c in ctx.snap.cities:
        net = c.net_amenities
        if net >= 0:
            continue
        level = happiness_for(net)
        if net <= -5:
            sev = SEVERITY_CRITICAL  # Unrest/Revolt: no growth, rebels can spawn
        elif net <= -3:
            sev = SEVERITY_WARNING
        else:
            sev = SEVERITY_INFO
        out.append(
            Alert(
                rule="amenities",
                key=f"city={c.city_id}",
                severity=sev,
                category="city",
                title=f"{c.name} is {level.key.lower()}",
                detail=(
                    f"{c.amenities} amenities for {c.amenities_needed} needed ({net:+d}): "
                    f"growth {level.growth_pct:+d}%, other yields {level.non_food_pct:+d}%."
                ),
                data={"city_id": c.city_id, "amenities": c.amenities, "needed": c.amenities_needed, "level": level.key},
                fix_tool="get_amenity_options",
            )
        )
    return out


@rule("loyalty")
def loyalty(ctx: RuleContext) -> list[Alert]:
    out = []
    for c in ctx.snap.cities:
        if c.loyalty_per_turn >= 0:
            continue
        turns = int(c.loyalty / -c.loyalty_per_turn) if c.loyalty_per_turn < 0 else None
        if turns is not None and turns <= 10:
            sev = SEVERITY_CRITICAL
        elif c.loyalty < 50:
            sev = SEVERITY_WARNING
        else:
            continue
        out.append(
            Alert(
                rule="loyalty",
                key=f"city={c.city_id}",
                severity=sev,
                category="city",
                title=f"{c.name} could flip in ~{turns} turns" if turns is not None else f"{c.name} is losing loyalty",
                detail=f"Loyalty {c.loyalty:.0f}/100, {c.loyalty_per_turn:+.1f} per turn.",
                data={"city_id": c.city_id, "loyalty": c.loyalty, "per_turn": c.loyalty_per_turn, "turns_to_zero": turns},
                fix_tool="get_loyalty_options",
            )
        )
    return out


@rule("housing")
def housing(ctx: RuleContext) -> list[Alert]:
    # GlobalParameters CITY_HOUSING_LEFT_*: growth is halved at 1 spare housing,
    # quartered at 0 and stops at -4.
    out = []
    for c in ctx.snap.cities:
        left = c.housing_left
        if left > 0:
            continue
        sev = SEVERITY_WARNING if left <= -4 else SEVERITY_INFO
        out.append(
            Alert(
                rule="housing",
                key=f"city={c.city_id}",
                severity=sev,
                category="city",
                title=f"{c.name} is out of housing",
                detail=f"{c.population} population, {c.housing:.1f} housing: growth {'has stopped' if left <= -4 else 'is cut to 25%'}.",
                data={"city_id": c.city_id, "population": c.population, "housing": c.housing},
                fix_tool="get_housing_options",
            )
        )
    return out


@rule("empty_queue")
def empty_queue(ctx: RuleContext) -> list[Alert]:
    empty = [c for c in ctx.snap.cities if c.queue_empty]
    if not empty:
        return []
    names = ", ".join(c.name for c in empty)
    return [
        Alert(
            rule="empty_queue",
            key="cities",
            severity=SEVERITY_WARNING,
            category="city",
            title=f"{len(empty)} cit{'y has' if len(empty) == 1 else 'ies have'} nothing to build",
            detail=f"Idle production in {names}.",
            data={"city_ids": [c.city_id for c in empty]},
            fix_tool=None,
        )
    ]


@rule("idle_gold")
def idle_gold(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    early = s.turn < bm.scale(bm.IDLE_GOLD_EARLY_UNTIL, s.speed_multiplier)
    threshold = bm.IDLE_GOLD_EARLY if early else bm.IDLE_GOLD
    if s.gold < threshold:
        return []
    return [
        Alert(
            rule="idle_gold",
            key="treasury",
            severity=SEVERITY_WARNING if s.gold >= 2 * threshold else SEVERITY_INFO,
            category="economy",
            title=f"{s.gold:.0f} gold is sitting idle",
            detail=(
                f"{s.gold_per_turn:+.0f}/turn. Gold doesn't compound in the treasury; a builder, settler, tile or building does."
                + (" Early on, a trader or monument bought now is worth far more than gold later." if early else "")
            ),
            data={"gold": s.gold, "gold_per_turn": s.gold_per_turn},
            fix_tool=None,
        )
    ]


@rule("idle_faith")
def idle_faith(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    if s.faith < bm.IDLE_FAITH:
        return []
    return [
        Alert(
            rule="idle_faith",
            key="faith",
            severity=SEVERITY_INFO,
            category="economy",
            title=f"{s.faith:.0f} faith is unspent",
            detail="Faith buys builders, settlers (with the right policies), Great People and religious units.",
            data={"faith": s.faith, "faith_per_turn": s.faith_per_turn},
        )
    ]


@rule("trade_slot")
def trade_slot(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    if "trade_capacity" in ctx.suspect:
        return []
    free = s.trade_capacity - s.trade_active
    if free <= 0:
        return []
    return [
        Alert(
            rule="trade_slot",
            key="routes",
            severity=SEVERITY_WARNING,
            category="economy",
            title=f"{free} trade route slot{'s' if free > 1 else ''} unused",
            detail=f"{s.trade_active}/{s.trade_capacity} routes running. Build or reassign a Trader.",
            data={"capacity": s.trade_capacity, "active": s.trade_active},
        )
    ]


# Happinesses table (gamedata): net +3 = Happy (+10% yields), net +5 = Ecstatic (+20%).
# Below those, extra amenities change nothing, so only the next step is worth chasing.
HAPPY_AT, ECSTATIC_AT = 3, 5
# Each copy of a luxury gives an amenity to up to 4 cities (one copy per city
# per type), so copies beyond ceil(cities / 4) do nothing for you.
CITIES_PER_LUXURY = 4


@rule("amenity_threshold")
def amenity_threshold(ctx: RuleContext) -> list[Alert]:
    close = []
    for c in ctx.snap.cities:
        net = c.net_amenities
        if net == HAPPY_AT - 1:
            close.append((c, "Happy", "+10%"))
        elif net == ECSTATIC_AT - 1:
            close.append((c, "Ecstatic", "+20%"))
    if not close:
        return []
    names = ", ".join(f"{c.name} → {lvl} ({bonus})" for c, lvl, bonus in close)
    return [
        Alert(
            rule="amenity_threshold",
            key="one_away",
            severity=SEVERITY_INFO,
            category="economy",
            title=f"{len(close)} cit{'y is' if len(close) == 1 else 'ies are'} 1 amenity from a yield bonus",
            detail=f"{names} on all yields. Amenities only pay off at net +3 and +5.",
            data={"cities": [c.city_id for c, _, _ in close]},
            fix_tool="get_amenity_options",
        )
    ]


@rule("luxury_surplus")
def luxury_surplus(ctx: RuleContext) -> list[Alert]:
    s = ctx.snap
    if not s.cities or not s.luxuries:
        return []
    useful = -(-len(s.cities) // CITIES_PER_LUXURY)  # ceil
    spare = {k: v - useful for k, v in s.luxuries.items() if v > useful}
    if not spare:
        return []
    pretty = ", ".join(f"{n} {k.replace('RESOURCE_', '').title()}" for k, n in spare.items())
    return [
        Alert(
            rule="luxury_surplus",
            key="spare",
            severity=SEVERITY_INFO,
            category="economy",
            title=f"Spare luxuries to sell: {pretty}",
            detail=(
                f"With {len(s.cities)} cit{'y' if len(s.cities) == 1 else 'ies'}, {useful} cop{'y' if useful == 1 else 'ies'} "
                "of each luxury covers you; extra copies give no amenities. The AI pays gold or gold per turn for them, "
                "which buys settlers and buildings anywhere. Keep them if you'll found more cities soon."
            ),
            data={"spare": spare, "useful_copies": useful},
        )
    ]
