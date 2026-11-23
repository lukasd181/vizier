"""Fix-it options: every way to fix a city problem, with gain, turns and cost.

Code lists and prices the options from the game's own numbers (production
turns and gold costs come straight from the city's build queue); Claude
combines and explains them. Gains the game doesn't expose are taken from the
REA-verified tables in gamedata and labelled with their confidence.
"""

from __future__ import annotations

import math
from typing import Any

from vizier import gamedata as gd
from vizier.models import CityView, EmpireSnapshot, FixOption


def _tables(rules: dict[str, Any] | None) -> dict[str, Any]:
    """Rule tables from the live ruleset when available, else gamedata's."""
    r = rules or {}
    return {
        "ent_b": r.get("entertainment_buildings") or gd.ENTERTAINMENT_BUILDINGS,
        "regional": r.get("regional_entertainment") or gd.REGIONAL_ENTERTAINMENT,
        "house_b": r.get("housing_buildings") or gd.HOUSING_BUILDINGS,
        "ent_d": r.get("entertainment_districts") or gd.ENTERTAINMENT_DISTRICTS,
        "house_d": r.get("housing_districts") or gd.HOUSING_DISTRICTS,
        "lux_cities": r.get("luxury_cities") or {},
    }


def _pretty(t: str) -> str:
    for pre in ("BUILDING_", "DISTRICT_", "POLICY_", "RESOURCE_", "UNIT_", "GOV_"):
        if t.startswith(pre):
            t = t[len(pre) :]
    return t.replace("_", " ").title()


def _slotted(policies: dict[str, Any]) -> set[str]:
    return {s["current_policy"] for s in policies.get("slots", []) if s.get("current_policy")}


def _available(policies: dict[str, Any]) -> set[str]:
    return {p["policy_type"] for p in policies.get("available", [])}


def _builder_turns(production: list[dict[str, Any]]) -> int | None:
    for o in production:
        if o.get("item_name") == "UNIT_BUILDER":
            return o.get("turns") or None
    return None


def _build_and_buy(
    production: list[dict[str, Any]], table: dict[str, int], gold: float, gain_unit: str, kind: str, note_fn=None
) -> list[FixOption]:
    out = []
    for o in production:
        item = o.get("item_name", "")
        if item not in table or o.get("is_repair"):
            continue
        gain = table[item]
        if gain <= 0:
            continue
        note = note_fn(item) if note_fn else ""
        if o.get("turns"):
            out.append(
                FixOption(
                    action=f"Build {_pretty(item)}",
                    kind=kind,
                    gain=gain,
                    gain_unit=gain_unit,
                    turns=int(o["turns"]),
                    cost=f"{o.get('cost', '?')} production",
                    notes=note,
                )
            )
        gc = o.get("gold_cost", -1)
        if gc is not None and gc > 0:
            short = gc - gold
            out.append(
                FixOption(
                    action=f"Buy {_pretty(item)}",
                    kind=kind,
                    gain=gain,
                    gain_unit=gain_unit,
                    turns=0 if short <= 0 else None,
                    cost=f"{gc} gold",
                    gold_cost=int(gc),
                    confidence="exact" if short <= 0 else "depends",
                    notes=(note + " " if note else "") + (f"Need {short:.0f} more gold." if short > 0 else ""),
                )
            )
    return out


# -- amenities --------------------------------------------------------------


def amenity_options(
    city: CityView,
    needs: dict[str, Any],
    production: list[dict[str, Any]],
    policies: dict[str, Any],
    snap: EmpireSnapshot,
    rules: dict[str, Any] | None = None,
) -> list[FixOption]:
    t = _tables(rules)
    opts: list[FixOption] = []
    held = needs.get("luxuries_held", {})

    # 1. Luxuries in our borders that aren't improved (a new type helps up to 4 cities)
    seen_types: set[str] = set()
    builder_build = _builder_turns(production)
    for lux in needs.get("unimproved_luxuries", []):
        rtype = lux["resource"]
        new_type = held.get(rtype, 0) == 0
        if rtype in seen_types or not new_type:
            continue
        seen_types.add(rtype)
        if lux["builder_id"] >= 0:
            turns = math.ceil(lux["builder_distance"] / max(lux["builder_moves"], 1))
            cost = "1 builder charge"
            conf = "estimate"
            note = f"Nearest builder is {lux['builder_distance']} tiles away (straight-line; terrain can slow it)."
        else:
            turns = builder_build
            cost = "a new builder"
            conf = "estimate"
            note = "No builder with charges; " + (f"one takes {builder_build} turns here." if builder_build else "build or buy one.")
        opts.append(
            FixOption(
                action=f"{'Repair' if lux['pillaged'] else 'Improve'} {_pretty(rtype)} at ({lux['x']},{lux['y']})",
                kind="luxury",
                gain=1,
                gain_unit="amenity",
                turns=turns,
                cost=cost,
                confidence=conf,
                notes=note
                + f" A new luxury type gives +1 amenity to up to {t['lux_cities'].get(rtype, 4)} cities, neediest first."
                + " Needs the improvement's tech.",
            )
        )

    # 2. Entertainment buildings and districts this city can make now
    opts += _build_and_buy(
        production,
        t["ent_b"],
        snap.gold,
        "amenity",
        "building",
        note_fn=lambda b: "Also reaches nearby cities (regional)." if b in t["regional"] else "",
    )
    opts += [
        o
        for o in _build_and_buy(production, t["ent_d"], snap.gold, "amenity", "district")
        if o.action.startswith("Build")  # districts can't be bought
    ]

    # 3. Policy cards (amounts verified; conditions summarised)
    slotted, available = _slotted(policies), _available(policies)
    for pol, pa in gd.POLICY_AMENITIES.items():
        if pa.amount > 0 and pol in available and pol not in slotted:
            applies = _policy_applies(pol, city)
            opts.append(
                FixOption(
                    action=f"Slot {_pretty(pol)}",
                    kind="policy",
                    gain=pa.amount if applies else 0,
                    gain_unit="amenity",
                    turns=0,
                    cost="a policy slot",
                    confidence="exact" if applies is not None else "estimate",
                    notes=f"+{pa.amount} in {pa.condition}."
                    + ("" if applies else " This city doesn't qualify yet.")
                    + " Free to swap when a civic completes.",
                )
            )
        elif pa.amount < 0 and pol in slotted:
            opts.append(
                FixOption(
                    action=f"Unslot {_pretty(pol)}",
                    kind="policy",
                    gain=-pa.amount,
                    gain_unit="amenity",
                    turns=0,
                    cost="its benefit",
                    notes=f"This card costs {pa.amount} amenities.",
                )
            )

    # 4. Amenities the game says are being lost
    losses = needs.get("amenity_losses", {})
    if losses.get("WarWeariness", 0) > 0:
        at_war = [r.name for r in snap.rivals if r.at_war]
        opts.append(
            FixOption(
                action="Make peace" + (f" with {', '.join(at_war)}" if at_war else ""),
                kind="peace",
                gain=losses["WarWeariness"],
                gain_unit="amenity",
                turns=None,
                cost="a peace deal",
                confidence="depends",
                notes="War weariness is costing this city amenities; it also decays slowly after peace.",
            )
        )
    if losses.get("Bankruptcy", 0) > 0:
        opts.append(
            FixOption(
                action="Get gold per turn back above zero",
                kind="economy",
                gain=losses["Bankruptcy"],
                gain_unit="amenity",
                turns=0,
                cost="cut maintenance or raise income",
                notes="A negative treasury costs amenities in every city.",
            )
        )

    # 5. Trading for a luxury we lack
    if city.net_amenities < 0:
        opts.append(
            FixOption(
                action="Trade for a luxury type you don't have",
                kind="trade",
                gain=1,
                gain_unit="amenity",
                turns=None,
                cost="a deal",
                confidence="depends",
                notes="Each new luxury type helps up to 4 cities. Check what the AI offers in its trade screen first.",
            )
        )
    return rank(opts)


def _policy_applies(pol: str, city: CityView) -> bool | None:
    if pol == "POLICY_RETAINERS":
        return city.has_garrison
    if pol == "POLICY_LIBERALISM":
        return city.specialty_districts >= 2
    if pol == "POLICY_NEW_DEAL":
        return city.specialty_districts >= 3
    if pol == "POLICY_CIVIL_PRESTIGE":
        return city.has_governor
    if pol == "POLICY_SPORTS_MEDIA":
        return "BUILDING_STADIUM" in city.buildings
    return None


# -- loyalty ----------------------------------------------------------------


def loyalty_options(
    city: CityView,
    needs: dict[str, Any],
    production: list[dict[str, Any]],
    policies: dict[str, Any],
    snap: EmpireSnapshot,
) -> list[FixOption]:
    opts: list[FixOption] = []
    sources = needs.get("loyalty_sources", [])

    if not needs.get("governor_here") and needs.get("unassigned_governor"):
        opts.append(
            FixOption(
                action="Assign a governor here",
                kind="governor",
                gain=gd.GOVERNOR_LOYALTY_ESTIMATE,
                gain_unit="loyalty/turn",
                turns=gd.GOVERNOR_TURNS_TO_ESTABLISH,
                cost="an unassigned governor",
                confidence="estimate",
                notes=f"Takes effect once established (base {gd.GOVERNOR_TURNS_TO_ESTABLISH} turns). The +{gd.GOVERNOR_LOYALTY_ESTIMATE} isn't in the game database; verify in the loyalty breakdown.",
            )
        )

    opts += _build_and_buy(production, gd.BUILDING_LOYALTY, snap.gold, "loyalty/turn", "building")

    slotted, available = _slotted(policies), _available(policies)
    for pol, (amount, cond) in gd.POLICY_LOYALTY.items():
        if amount > 0 and pol in available and pol not in slotted:
            applies = {
                "POLICY_LIMITANEI": city.has_garrison,
                "POLICY_MARTIAL_LAW": city.has_garrison,
                "POLICY_PRAETORIUM": city.has_governor,
            }.get(pol)
            opts.append(
                FixOption(
                    action=f"Slot {_pretty(pol)}",
                    kind="policy",
                    gain=amount if applies is not False else 0,
                    gain_unit="loyalty/turn",
                    turns=0,
                    cost="a policy slot",
                    confidence="exact" if applies is not None else "estimate",
                    notes=f"+{amount} in {cond}." + (" Garrison a unit here first." if applies is False and "garrison" in cond else ""),
                )
            )
        elif amount < 0 and pol in slotted:
            opts.append(
                FixOption(
                    action=f"Unslot {_pretty(pol)}",
                    kind="policy",
                    gain=-amount,
                    gain_unit="loyalty/turn",
                    turns=0,
                    cost="its benefit",
                    notes=f"This card costs {amount} loyalty per turn in every city.",
                )
            )

    # Amenity level feeds loyalty: getting a displeased city to content is worth +3..+6.
    level = gd.happiness_for(city.net_amenities)
    now = gd.HAPPINESS_LOYALTY[level.key]
    if now < 0:
        opts.append(
            FixOption(
                action=f"Raise amenities to Content ({-city.net_amenities} more)",
                kind="economy",
                gain=-now,
                gain_unit="loyalty/turn",
                turns=None,
                cost="see get_amenity_options",
                confidence="exact",
                notes=f"{level.key.title()} costs {now} loyalty per turn.",
            )
        )

    for src, val in sources:
        low = src.lower()
        if val < 0 and "religion" in low and snap.our_religion:
            opts.append(
                FixOption(
                    action=f"Convert the city to {snap.our_religion}",
                    kind="religion",
                    gain=2 * gd.RELIGION_LOYALTY,
                    gain_unit="loyalty/turn",
                    turns=None,
                    cost="missionaries or apostles",
                    confidence="estimate",
                    notes=f"A foreign majority religion costs {gd.RELIGION_LOYALTY}/turn; yours adds {gd.RELIGION_LOYALTY}.",
                )
            )
        if val < 0 and ("starv" in low or "food" in low):
            opts.append(
                FixOption(
                    action="Stop the starvation",
                    kind="economy",
                    gain=-gd.STARVATION_LOYALTY,
                    gain_unit="loyalty/turn",
                    turns=0,
                    cost="work food tiles or change focus",
                    notes="Starving cities lose 4 loyalty per turn.",
                )
            )
    return rank(opts)


# -- housing ----------------------------------------------------------------


def housing_options(
    city: CityView,
    needs: dict[str, Any],
    production: list[dict[str, Any]],
    snap: EmpireSnapshot,
    rules: dict[str, Any] | None = None,
) -> list[FixOption]:
    t = _tables(rules)
    opts = _build_and_buy(production, t["house_b"], snap.gold, "housing", "building")
    opts += [
        o
        for o in _build_and_buy(production, t["house_d"], snap.gold, "housing", "district")
        if o.action.startswith("Build")  # districts can't be bought
    ]
    for o in production:
        if o.get("item_name") == "DISTRICT_AQUEDUCT" and o.get("turns"):
            water = needs.get("housing_sources", {}).get("Water", 0)
            # GlobalParameters: aqueduct raises a city to 6 housing from water
            # (CITY_POPULATION_AQUEDUCT_MIN) or +2 if it already had fresh water.
            gain = max(6 - water, 2) if water < 6 else 2
            opts.append(
                FixOption(
                    action="Build Aqueduct",
                    kind="district",
                    gain=gain,
                    gain_unit="housing",
                    turns=int(o["turns"]),
                    cost=f"{o.get('cost', '?')} production",
                    confidence="estimate",
                    notes="Needs a tile next to the city centre and a river, lake, oasis or mountain.",
                )
            )
    builder_turns = _builder_turns(production)
    opts.append(
        FixOption(
            action="Build farms (or pastures/plantations with the right civics)",
            kind="unit",
            gain=0.5,
            gain_unit="housing",
            turns=builder_turns,
            cost="1 builder charge each",
            confidence="estimate",
            notes="Each farm adds 0.5 housing.",
        )
    )
    return rank(opts)


# -- ranking ----------------------------------------------------------------


def rank(opts: list[FixOption]) -> list[FixOption]:
    """Fastest first; unknown timing last; bigger gain breaks ties. Options
    that gain nothing for this city yet (e.g. a card it doesn't qualify for)
    go to the bottom."""
    return sorted(opts, key=lambda o: (o.gain <= 0, o.turns is None, o.turns or 0, -o.gain, o.gold_cost or 0))


def combine_fastest(opts: list[FixOption], needed: float) -> list[FixOption]:
    """Greedy: take the fastest options until the gap is closed. Skips a Buy
    when the matching Build is already chosen (and vice versa), and options
    with no gain."""
    chosen: list[FixOption] = []
    total = 0.0
    items: set[str] = set()
    for o in opts:
        if total >= needed:
            break
        if o.gain <= 0 or o.turns is None:
            continue
        item = o.action.split(" ", 1)[-1]
        if item in items:
            continue
        chosen.append(o)
        items.add(item)
        total += o.gain
    return chosen
