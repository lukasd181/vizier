"""Plain-text renderings of mentor results for the LLM.

Short, number-first, and explicit about what is an estimate. The LLM adds
the judgement ("which matters now and why"); these only state facts.
"""

from __future__ import annotations

import json
from typing import Any

from chancellor.fog import tile_to_dict
from chancellor.models import SEVERITY_NAMES, CityView, Commitment, EmpireSnapshot, FixOption, Goal, TileView
from chancellor.rules import Review

_SEV_MARK = {1: "!!", 2: "!", 3: "-"}


def turn_review(rv: Review, snap: EmpireSnapshot, goal: Goal | None, coach: bool = False) -> str:
    lines = [
        f"Turn {snap.turn} · {snap.civ} · {len(snap.cities)} cities · "
        f"{snap.gold:.0f} gold ({snap.gold_per_turn:+.0f}) · {snap.faith:.0f} faith · "
        f"explored {snap.explored_pct:.0f}%",
        _era_line(snap),
        *_research_lines(snap),
        f"Goal: {goal.victory} ({goal.help_level}, {goal.pace} pace)" if goal else "Goal: not set (set_goal to tailor advice)",
        *_city_lines(snap),
        *_unit_lines(snap),
        "",
    ]
    if goal and goal.help_level == "off":
        lines.append("Help level is off: no alerts. Ask anything and I'll still answer.")
        return "\n".join(lines)
    if not rv.top:
        lines.append("Nothing needs your attention this turn.")
    else:
        lines.append(f"Top {len(rv.top)} of {len(rv.all)} alerts:")
        for a in rv.top:
            lines.append(f"{_SEV_MARK[a.severity]} [{SEVERITY_NAMES[a.severity]}] {a.title}")
            lines.append(f"   {a.detail}")
            tail = f"   id={a.id}"
            if a.fix_tool:
                tail += f" · options: {a.fix_tool}"
            lines.append(tail)
    rest = [a for a in rv.all if a not in rv.top and a.id not in rv.suppressed]
    if rest:
        lines.append("")
        lines.append("Also noted (not shown in-game): " + "; ".join(a.title for a in rest[:6]) + ("…" if len(rest) > 6 else ""))
    if coach and rv.top:
        lines.append("")
        lines.append(
            "Coach mode: before giving answers, ask the player which of these they'd tackle first and why; "
            "explain the reasoning behind each alert in a sentence."
        )
    if rv.errors:
        lines.append("")
        lines.append("Rule errors (please report): " + "; ".join(rv.errors))
    return "\n".join(lines)


def _name(t: str) -> str:
    for pre in ("UNIT_", "BUILDING_", "DISTRICT_", "PROJECT_"):
        if t.startswith(pre):
            t = t[len(pre):]
    return t.replace("_", " ").title()


def _city_lines(snap: EmpireSnapshot) -> list[str]:
    if not snap.cities:
        return []
    out = ["Cities:"]
    for c in snap.cities:
        if c.queue_empty:
            building = "building NOTHING"
        else:
            turns = f", {c.production_turns_left} turn(s)" if c.production_turns_left else ""
            building = f"building {_name(c.currently_building)}{turns}"
        loyalty = f" · loyalty {c.loyalty:.0f} ({c.loyalty_per_turn:+.1f})" if c.loyalty_per_turn < 0 else ""
        out.append(
            f"  {c.name} (pop {c.population}{', capital' if c.is_capital else ''}): {building} · "
            f"{c.production:.0f} production · amenities {c.net_amenities:+d} · "
            f"housing {c.housing:.0f} for {c.population} pop{loyalty}"
        )
    return out


def _unit_lines(snap: EmpireSnapshot, limit: int = 10) -> list[str]:
    if not snap.units:
        return []
    # Civilians in danger first, then civilians, then the rest.
    units = sorted(snap.units, key=lambda u: (u.threat_distance is None, not u.is_civilian, u.unit_type))
    out = ["Units:"]
    for u in units[:limit]:
        moves = f"{u.moves_remaining:g} move(s) left" if u.moves_remaining else "no moves left"
        hp = f" · {u.health} HP" if u.health < 100 else ""
        threat = " ".join(_name(w) if w.startswith("UNIT_") else w for w in u.threat_desc.split())
        danger = f" · {threat} {u.threat_distance} tile(s) away!" if u.threat_distance is not None else ""
        out.append(f"  {_name(u.unit_type)} at ({u.x},{u.y}) · {moves}{hp}{danger}")
    if len(units) > limit:
        rest: dict[str, int] = {}
        for u in units[limit:]:
            rest[_name(u.unit_type)] = rest.get(_name(u.unit_type), 0) + 1
        out.append("  …and " + ", ".join(f"{n} {k}" for k, n in rest.items()))
    return out


def _research_lines(snap: EmpireSnapshot) -> list[str]:
    out = []
    for kind, label, word in (("tech", "Researching", "eureka"), ("civic", "Civic", "inspiration")):
        r = snap.research.get(kind)
        if not r or r.get("cost", 0) <= 0:
            continue
        name = r["item"].split("_", 1)[-1].replace("_", " ").title()
        pct = 100 * r["progress"] / r["cost"]
        if not r.get("boost_pct"):
            boost = f"no {word}"
        elif r.get("boosted"):
            boost = f"{word} done"
        else:
            boost = f"{word} not yet: {r.get('trigger') or '?'}"
        out.append(f"{label}: {name} {pct:.0f}% · {boost}")
    return out


def _era_line(snap: EmpireSnapshot) -> str:
    if snap.era_golden_threshold <= 0:
        return f"Era: {snap.era or '?'}"
    age = f" · {snap.age} age" if snap.age else ""
    left = f" · era ends in {snap.era_countdown} turn(s)" if snap.era_countdown > 0 else ""
    return (
        f"Era: {snap.era}{age} · era score {snap.era_score} "
        f"(normal age at {snap.era_dark_threshold}, golden at {snap.era_golden_threshold}){left}"
    )


def explain(alert: dict[str, Any] | None, alert_id: str) -> str:
    if alert is None:
        return f"No record of alert '{alert_id}' in this game. Run get_turn_review first."
    turns = alert.get("history", [])
    since = f"first raised T{turns[0]}, {len(turns)} turn(s) total" if turns else ""
    return "\n".join(
        [
            f"{alert['title']} ({SEVERITY_NAMES.get(alert['severity'], '?')}, rule {alert['rule']})",
            alert["detail"],
            since,
            "Data behind it:",
            json.dumps(alert["data"], indent=2, default=str),
        ]
    )


def fix_options(
    problem: str,
    city: CityView,
    needs: dict[str, Any],
    opts: list[FixOption],
    combo: list[FixOption],
    headline: str,
    gap: float = 0,
) -> str:
    lines = [f"{city.name} — {headline}", ""]
    if not opts:
        lines.append(f"No {problem} options found from what this city can do right now.")
        return "\n".join(lines)
    lines.append(f"{len(opts)} option(s), fastest first:")
    for i, o in enumerate(opts, 1):
        when = "now" if o.turns == 0 else (f"{o.turns} turn(s)" if o.turns is not None else "depends")
        conf = "" if o.confidence == "exact" else f" [{o.confidence}]"
        lines.append(f"{i}. {o.action}: {o.gain:+g} {o.gain_unit}, {when}, costs {o.cost}{conf}")
        if o.notes:
            lines.append(f"   {o.notes}")
    if combo:
        total = sum(o.gain for o in combo)
        slowest = max((o.turns or 0) for o in combo)
        lines += [
            "",
            f"Fastest combination: {' + '.join(o.action for o in combo)} → {total:+g} {combo[0].gain_unit} within {slowest} turn(s).",
        ]
        if gap and total < gap:
            lines.append(
                f"That closes {total:g} of the {gap:g} needed; the rest depends on options with uncertain timing (deals, peace) or none listed."
            )
    elif gap:
        lines += ["", f"No option with known timing closes any of the {gap:g} needed."]
    return "\n".join(lines)


def amenity_headline(city: CityView, needs: dict[str, Any]) -> str:
    have, need = needs.get("amenities", city.amenities), needs.get("amenities_needed", city.amenities_needed)
    srcs = ", ".join(f"{k} {v:+d}" for k, v in needs.get("amenity_sources", {}).items() if v)
    lost = ", ".join(f"{k} -{v}" for k, v in needs.get("amenity_losses", {}).items() if v)
    net = have - need
    s = f"{have} amenities for {need} needed ({net:+d})"
    if 0 <= net < 3:
        s += f"; {3 - net} more reaches Happy (+10% yields)"
    elif 3 <= net < 5:
        s += f"; {5 - net} more reaches Ecstatic (+20% yields)"
    if srcs:
        s += f". From: {srcs}"
    if lost:
        s += f". Lost to: {lost}"
    return s


def loyalty_headline(city: CityView, needs: dict[str, Any]) -> str:
    loy = needs.get("loyalty") if needs.get("loyalty") is not None else city.loyalty
    lpt = needs.get("loyalty_per_turn") if needs.get("loyalty_per_turn") is not None else city.loyalty_per_turn
    srcs = ", ".join(f"{s} {v:+.1f}" for s, v in needs.get("loyalty_sources", []))
    s = f"loyalty {loy:.0f}/100, {lpt:+.1f}/turn"
    if lpt < 0:
        s += f" (~{int(loy / -lpt)} turns to zero)"
    if srcs:
        s += f". Breakdown: {srcs}"
    return s


def housing_headline(city: CityView, needs: dict[str, Any]) -> str:
    srcs = ", ".join(f"{k} {v:+g}" for k, v in needs.get("housing_sources", {}).items() if v)
    s = f"{city.population} pop, {city.housing:.1f} housing ({city.housing_left:+.1f} spare)"
    return s + (f". From: {srcs}" if srcs else "")


def tiles(ts: list[TileView], limit: int = 60) -> str:
    if not ts:
        return "No revealed tiles match."
    out = [f"{len(ts)} tile(s)" + (f", first {limit}:" if len(ts) > limit else ":")]
    for t in ts[:limit]:
        d = tile_to_dict(t)
        x, y = d.pop("x"), d.pop("y")
        out.append(f"({x},{y}) " + " ".join(f"{k}={v}" for k, v in d.items()))
    out.append("Only revealed tiles; for tiles not in sight, only terrain and resources are shown.")
    return "\n".join(out)


def goal_status(st: dict[str, Any]) -> str:
    return json.dumps(st, indent=2, default=str)


def commitments(cs: list[Commitment], turn: int) -> str:
    if not cs:
        return "No commitments yet. add_commitment turns a plan into something I check every turn."
    out = []
    for c in cs:
        check = "" if c.check_kind == "manual" else f" [auto: {c.check_kind} {c.check_arg}]"
        when = f"done T{c.done_turn}" if c.status == "done" else f"due T{c.due_turn}"
        if c.status in ("open", "overdue") and turn > c.due_turn:
            when += f", {turn - c.due_turn} late"
        out.append(f"#{c.id} {c.status.upper()} {when}: {c.text}{check}")
    return "\n".join(out)


def rivals(snap: EmpireSnapshot, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "You haven't met any other civilizations yet."
    out = [f"Your military strength: {snap.our_military_strength}"]
    for r in rows:
        rel = "ALLY" if r["is_ally"] else ("FRIEND" if r["is_friend"] else r["diplomatic_state"])
        out.append(
            f"{r['name']} (id {r['player_id']}): {rel}{' · AT WAR' if r['at_war'] else ''} · score {r['score']} · "
            f"{r['num_cities']} cities · military {r['military_strength']}"
            + (f" ({r['military_ratio']}x yours)" if r["military_ratio"] else "")
        )
        parts = []
        if r["science_vp"]:
            parts.append(f"space race {r['science_vp']}/{r['science_vp_needed']}")
        if r["diplomatic_vp"]:
            parts.append(f"diplomatic {r['diplomatic_vp']}/20")
        if r["religion_civs_converted"]:
            parts.append(f"{r['religion_name'] or 'religion'} majority in {r['religion_civs_converted']} civs")
        if r["culture_civs_dominated"]:
            parts.append(f"culturally dominates {r['culture_civs_dominated']} known civs")
        if parts:
            out.append("   victory: " + ", ".join(parts))
        eta = {k: v for k, v in r["turns_to_win"].items() if v is not None}
        if eta:
            out.append("   at current pace: " + ", ".join(f"{k} in ~{v} turns" for k, v in eta.items()))
        todo = []
        if not r["we_have_delegation"] and not r["we_have_embassy"]:
            todo.append("no delegation")
        if r["can_declare_friendship"]:
            todo.append("friendship available")
        if r["can_form_alliance"]:
            todo.append("alliance available")
        if todo:
            out.append("   diplomacy: " + ", ".join(todo))
    out.append("Only civilizations you have met; numbers are what the World Rankings screen shows.")
    return "\n".join(out)


def settle_spots(spots: list[dict[str, Any]], total: int) -> str:
    if not spots:
        return "No legal, revealed city sites found within 9 tiles. Explore further to reveal more land."
    out = [f"Top {len(spots)} of {total} legal revealed sites (each at least 4 tiles from the others):"]
    for i, s in enumerate(spots, 1):
        tags = []
        if s["fresh_water"]:
            tags.append("fresh water")
        elif s["coastal"]:
            tags.append("coast")
        else:
            tags.append("no fresh water")
        if s["hills"]:
            tags.append("hills")
        if s["luxuries"]:
            lux = ", ".join(sorted({r.replace("RESOURCE_", "").title() for r in s["luxuries"]}))
            tags.append(f"luxury: {lux}" + (f" ({s['new_luxury_types']} new type)" if s["new_luxury_types"] else ""))
        if s.get("campus_adjacency"):
            bits = []
            if s["adjacent_mountains"]:
                bits.append(f"{s['adjacent_mountains']} mountain")
            if s.get("adjacent_reefs"):
                bits.append(f"{s['adjacent_reefs']} reef")
            tags.append(f"Campus adjacency nearby ~+{s['campus_adjacency']}" + (f" ({', '.join(bits)})" if bits else ""))
        if s["strategics"]:
            tags.append(f"{s['strategics']} strategic")
        if s["foreign_tiles"]:
            tags.append(f"{s['foreign_tiles']} foreign tile(s) nearby")
        rec = " · the game's advisor recommends this too" if s["game_recommends"] else ""
        out.append(
            f"{i}. ({s['x']},{s['y']}) score {s['score']} · {s['distance']} tiles away · "
            f"food {s['food']} / production {s['production']} nearby{rec}"
        )
        out.append("   " + "; ".join(tags))
        if s["unrevealed_nearby"] >= 4:
            out.append(f"   {s['unrevealed_nearby']} nearby tiles still unexplored: worth a look before committing")
    out.append("Scores weigh nearby food and production (first ring double), fresh water, luxuries, hills and mountains; only revealed tiles count.")
    return "\n".join(out)
