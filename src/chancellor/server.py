"""Vizier — the Civ 6 mentor MCP server.

Tool names follow the feature catalog in "Civ 6 Mentor MCP: High-Value Asks
& Features". The server reads the game and draws on the map; it never
changes game state (no production, research, moves or deals). Batch actions
behind player approval (propose_batch / apply_batch) are a later milestone.

Environment:
  CHANCELLOR_FIXTURE=<path.json>  run against a recorded snapshot instead of a live game
  CHANCELLOR_DB=<path>            SQLite location (default ~/.chancellor/chancellor.sqlite3)
  CHANCELLOR_DEBUG_FULL_VISION=1  developer-only: disable the fog filter (output is stamped)
  CIV_MCP_PORT                    FireTuner port (default 4318; host is always localhost)
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP

from chancellor import benchmarks as bm
from chancellor import goals as goals_mod
from chancellor import narrate as nr
from chancellor.mentor import CityNotFound, Mentor
from chancellor.models import Goal
from chancellor.sources.base import SourceUnavailable
from chancellor.store import Store

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[Mentor]:
    fixture = os.environ.get("CHANCELLOR_FIXTURE")
    if fixture:
        from chancellor.sources.fixture import FixtureSource

        source = FixtureSource(fixture)
    else:
        from chancellor.sources.tuner import TunerSource

        source = TunerSource(port=int(os.environ.get("CIV_MCP_PORT", "4318")))
    store = Store()
    try:
        yield Mentor(source, store)
    finally:
        store.close()


mcp = FastMCP(
    "vizier",
    instructions=(
        "Vizier is a Civ 6 mentor for a human player. It sees only what the player could see "
        "(fog of war is enforced), never changes the game, and keeps advice to what was asked. "
        "Start a turn with get_turn_review. Offer 2-3 options with trade-offs rather than orders; "
        "hint before answering; respect the player's goal, even a roleplay or wonder game."
    ),
    lifespan=lifespan,
)


def _mentor(ctx: Context) -> Mentor:
    return ctx.request_context.lifespan_context


async def _run(ctx: Context, fn: Callable[[Mentor], Awaitable[str]]) -> str:
    m = _mentor(ctx)
    try:
        return m.fog.stamp(await fn(m))
    except ConnectionError as e:
        return (
            f"Can't reach the game: {e}\n"
            "Check: Civ 6 is running with a game loaded, EnableTuner is 1 in AppOptions.txt, "
            "and nothing else (FireTuner, the civ6-mcp server) holds the single tuner connection."
        )
    except (CityNotFound, SourceUnavailable, ValueError) as e:
        return str(e)


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True})
async def get_turn_review(ctx: Context, push_to_game: bool = True) -> str:
    """Check every rule for this turn and return the top alerts (at most 3).

    Covers rival victory progress, loyalty, amenities, housing, idle gold and
    faith, empty production queues, free trade route slots, exploration and
    expansion benchmarks, civilians in danger, barbarian camps, military
    balance, passive diplomacy, overdue plans and goal viability. Ranked by
    severity, then by root cause early in the game. Also refreshes the
    in-game alert panel if the ChancellorAlerts mod is installed.

    Call at the start of every turn.
    """

    async def go(m: Mentor) -> str:
        rv, snap, goal = await m.turn_review(push_to_game=push_to_game)
        return nr.turn_review(rv, snap, goal, coach=bool(goal and goal.help_level == "coach"))

    return await _run(ctx, go)


@mcp.tool(annotations={"readOnlyHint": True})
async def explain_alert(ctx: Context, alert_id: str) -> str:
    """Show the data behind one alert (use the id= from get_turn_review)."""

    async def go(m: Mentor) -> str:
        return nr.explain(await m.explain_alert(alert_id), alert_id)

    return await _run(ctx, go)


@mcp.tool()
async def dismiss_alert(ctx: Context, alert_id: str, snooze_turns: int = 10) -> str:
    """Hide an alert for a number of turns. Rules the player keeps dismissing
    are retired for the rest of the game (critical alerts never are)."""

    async def go(m: Mentor) -> str:
        until = await m.dismiss_alert(alert_id, max(1, snooze_turns))
        return f"Snoozed {alert_id} until T{until}."

    return await _run(ctx, go)


# ---------------------------------------------------------------------------
# Fix-it options
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True})
async def get_amenity_options(ctx: Context, city: str) -> str:
    """Every way to raise a city's amenities, with gain, turns to effect and
    cost, fastest first — plus the fastest combination that closes the gap.

    Args:
        city: city name (e.g. "Nagoya") or city id
    """

    async def go(m: Mentor) -> str:
        cv, needs, opts, combo = await m.amenity_options(city)
        gap = max(0, needs.get("amenities_needed", cv.amenities_needed) - needs.get("amenities", cv.amenities))
        return nr.fix_options("amenity", cv, needs, opts, combo, nr.amenity_headline(cv, needs), gap)

    return await _run(ctx, go)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_loyalty_options(ctx: Context, city: str) -> str:
    """How to keep a city from flipping: its loyalty breakdown and every fix
    ranked by speed.

    Args:
        city: city name or city id
    """

    async def go(m: Mentor) -> str:
        cv, needs, opts, combo = await m.loyalty_options(city)
        lpt = needs.get("loyalty_per_turn")
        gap = max(0.0, -(lpt if lpt is not None else cv.loyalty_per_turn))
        return nr.fix_options("loyalty", cv, needs, opts, combo, nr.loyalty_headline(cv, needs), gap)

    return await _run(ctx, go)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_housing_options(ctx: Context, city: str) -> str:
    """Housing breakdown for a city and every way to add housing, fastest first.

    Args:
        city: city name or city id
    """

    async def go(m: Mentor) -> str:
        cv, needs, opts, combo = await m.housing_options(city)
        gap = max(0.0, cv.population - cv.housing + 1)
        return nr.fix_options("housing", cv, needs, opts, combo, nr.housing_headline(cv, needs), gap)

    return await _run(ctx, go)


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True})
async def get_tile(ctx: Context, x: int, y: int) -> str:
    """One revealed tile: terrain, feature, resource, improvement, district,
    owner, road, appeal, whether it's worked. Unrevealed tiles return nothing."""

    async def go(m: Mentor) -> str:
        ts = [t for t in await m.tiles("area", x=x, y=y, radius=0) if (t.x, t.y) == (x, y)]
        return nr.tiles(ts) if ts else f"({x},{y}) hasn't been revealed."

    return await _run(ctx, go)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_tiles(
    ctx: Context,
    scope: str = "empire",
    filter: str = "",
    x: int = 0,
    y: int = 0,
    radius: int = 3,
    city: str = "",
    resource: str = "",
    improvement: str = "",
) -> str:
    """Search revealed tiles.

    Args:
        scope: "empire" (your territory), "city" (one city's tiles; set city),
            "area" (around x,y within radius), or "revealed" (everything you've
            seen — combine with resource/improvement/filter)
        filter: "", "unimproved_resources", "pillaged", "no_road", "unworked",
            "luxury" or "strategic"
        resource: e.g. "RESOURCE_OIL" (only resources your techs reveal)
        improvement: e.g. "IMPROVEMENT_MINE"

    Pair with highlight_tiles to show the results in-game.
    """

    async def go(m: Mentor) -> str:
        kwargs: dict = {"resource": resource.upper(), "improvement": improvement.upper()}
        if scope == "area":
            kwargs.update(x=x, y=y, radius=max(0, min(radius, 10)))
        elif scope == "city":
            kwargs["city_id"] = (await m.resolve_city(city)).city_id
        return nr.tiles(await m.tiles(scope, filter=filter, **kwargs))

    return await _run(ctx, go)


def _parse_tiles(tiles: str) -> list[tuple[int, int]]:
    """Accept "x,y;x,y" or a JSON list of [x, y] pairs."""
    s = tiles.strip()
    if s.startswith("["):
        return [(int(a), int(b)) for a, b in json.loads(s)]
    out = []
    for part in s.replace(" ", "").split(";"):
        if part:
            a, b = part.split(",")
            out.append((int(a), int(b)))
    return out


@mcp.tool()
async def highlight_tiles(
    ctx: Context,
    tiles: str,
    color: str = "green",
    label: str = "",
    pin: bool = False,
    look_at: bool = True,
    icon: str = "",
) -> str:
    """Highlight hexes on the map and move the camera to the first one.

    Highlights use the game's movement-highlight style ("red" uses the
    attack style). They vanish with clear_highlights, or when a unit is
    selected or a lens opens.

    To mark what goes on a tile, pass icon: a district, improvement,
    building or unit, e.g. "commercial hub", "campus", "farm",
    "DISTRICT_HOLY_SITE". That drops a map pin showing the game's own icon
    for it. Pins are saved in the game file, so only add them when the
    player asks; at most 5 per call; clear_highlights removes them.

    Args:
        tiles: "x,y;x,y;..." or JSON [[x,y],...]
        color: green | red (style; other values fall back to green)
        label: pin text (defaults to the icon name)
        pin: drop a plain pin with label even without an icon
        icon: district / improvement / building / unit to show on the pin
    """

    async def go(m: Mentor) -> str:
        n, pins, resolved = await m.highlight(_parse_tiles(tiles), color, label, pin, look_at, icon)
        msg = f"Highlighted {n} revealed tile(s)."
        if pins:
            shown = label or icon.strip().replace("_", " ").title()
            msg += f" Added {pins} pin(s) labelled '[Vizier] {shown}'"
            if resolved == "ICON_UNKNOWN":
                msg += f", but no district/improvement/building/unit matched '{icon}', so they have the default icon"
            elif resolved:
                msg += f" with the {resolved} icon"
            msg += "."
        return msg

    return await _run(ctx, go)


@mcp.tool()
async def clear_highlights(ctx: Context) -> str:
    """Remove Vizier's hex highlights and the map pins Vizier placed.
    Pins the player made themselves are left alone."""

    async def go(m: Mentor) -> str:
        removed = await m.clear_highlights()
        return "Highlights cleared." + (f" Removed {removed} Vizier pin(s)." if removed else "")

    return await _run(ctx, go)


@mcp.tool()
async def rank_settle_spots(ctx: Context, top: int = 3, pin: bool = False) -> str:
    """Where should the next city go? Ranks revealed, legal sites near your empire.

    Legality comes from the game (IsValidFoundLocation); scores weigh nearby
    food and production, fresh water, coast, luxuries (new types count more),
    hills and adjacent mountains (Campus adjacency). Sites the game's own
    settler advisor recommends are flagged. Only tiles you've revealed count.

    Args:
        top: how many sites (1-10); each is at least 4 tiles from the others
        pin: drop map tacks with the settler icon on the sites (saved in the
            game file; clear_highlights removes them)
    """

    async def go(m: Mentor) -> str:
        spots, total = await m.settle_spots(top)
        text = nr.settle_spots(spots, total)
        if pin and spots:
            tiles = [(s["x"], s["y"]) for s in spots]
            await m.highlight(tiles, "green", "", False, True)  # highlight + camera on #1
            if m.writer is not None:
                for i, (x, y) in enumerate(tiles, 1):
                    await m.writer.add_pin(x, y, f"City site #{i}", "settler")
            text += f"\nPinned {len(tiles)} site(s) with the settler icon and moved the camera to #1."
        return text

    return await _run(ctx, go)


@mcp.tool(annotations={"readOnlyHint": True})
async def find_park_sites(ctx: Context) -> str:
    """Tiles where a Naturalist could start a National Park now.

    Uses the game's own rule check (Game.GetNationalParks():GetPossibleParkTiles),
    so shape, borders, appeal and improvement rules are the engine's.
    A park gives +2 amenities to its city and +1 to up to 4 nearby cities.
    """

    async def go(m: Mentor) -> str:
        sites = await m.park_sites()
        if not sites:
            return "No valid National Park sites right now (needs Charming/Breathtaking, unimproved tiles in one city's borders)."
        lines = [f"{len(sites)} tile(s) a Naturalist can use:"]
        for s in sites[:40]:
            lines.append(f"({s['x']},{s['y']}) appeal {s['appeal']} · {s['city'] or 'unowned'}")
        lines.append("Keep districts and improvements off these tiles to keep the option.")
        return "\n".join(lines)

    return await _run(ctx, go)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


@mcp.tool()
async def set_goal(
    ctx: Context,
    victory: str,
    style: str = "",
    difficulty: str = "",
    help_level: str = "advisor",
    pace: str = "minimum",
) -> str:
    """Store the player's goal so advice fits it.

    Args:
        victory: science | culture | religious | diplomatic | domination | score | none
        style: free text, e.g. "peaceful builder", "wonder-whore", "roleplay Rome"
        difficulty: e.g. "Deity"
        help_level: off | watchdog (only critical alerts) | advisor (alerts + answers) |
            coach (explains reasoning, asks the player questions)
        pace: expansion benchmark — "minimum" (CivBench floor: city 4 by T80-100) or
            "pro" (a pro player's pace: 4 cities mid-Classical, 7 by Medieval, 12+ after)
    """

    async def go(m: Mentor) -> str:
        v, h = victory.lower().strip(), help_level.lower().strip()
        if v not in goals_mod.VICTORIES:
            raise ValueError(f"victory must be one of {goals_mod.VICTORIES}")
        if h not in goals_mod.HELP_LEVELS:
            raise ValueError(f"help_level must be one of {goals_mod.HELP_LEVELS}")
        p = pace.lower().strip()
        if p not in bm.PACES:
            raise ValueError(f"pace must be one of {bm.PACES}")
        g = await m.set_goal(Goal(victory=v, style=style, difficulty=difficulty, help_level=h, pace=p))
        return (
            f"Goal set at T{g.set_turn}: {g.victory}"
            + (f" ({g.style})" if g.style else "")
            + f", help level {g.help_level}, {g.pace} expansion pace."
        )

    return await _run(ctx, go)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_goal_status(ctx: Context) -> str:
    """Am I on track? Cities and exploration vs benchmarks (behind by N
    turns), districts, progress on the chosen victory vs the best visible
    rival, a viability check with pivot suggestions, and plan follow-through."""

    async def go(m: Mentor) -> str:
        return nr.goal_status(await m.goal_status())

    return await _run(ctx, go)


@mcp.tool()
async def add_commitment(ctx: Context, text: str, due_turn: int, check: str = "manual") -> str:
    """Track a plan; it's checked every turn and flagged when overdue.

    Args:
        text: the plan in the player's words, e.g. "Settle the river site north of Kyoto"
        due_turn: turn it should be done by
        check: how to auto-detect completion — "manual", "city_count:4",
            "tech:TECH_WRITING", "civic:CIVIC_POLITICAL_PHILOSOPHY",
            "district:Kyoto:DISTRICT_CAMPUS", "building:BUILDING_LIBRARY",
            "government:GOVERNMENT_CLASSICAL_REPUBLIC" or "explored_pct:25"
    """

    async def go(m: Mentor) -> str:
        kind, _, arg = check.partition(":")
        c = await m.add_commitment(text, due_turn, kind or "manual", arg)
        auto = "" if c.check_kind == "manual" else f", auto-checked ({c.check_kind} {c.check_arg})"
        return f"Commitment #{c.id} added: due T{c.due_turn}{auto}."

    return await _run(ctx, go)


@mcp.tool(annotations={"readOnlyHint": True})
async def list_commitments(ctx: Context, include_closed: bool = False) -> str:
    """List tracked plans with status (open / overdue / done / dropped)."""

    async def go(m: Mentor) -> str:
        cs = await m.commitments(include_closed)
        return nr.commitments(cs, m.last_snapshot.turn if m.last_snapshot else 0)

    return await _run(ctx, go)


@mcp.tool()
async def update_commitment(ctx: Context, commitment_id: int, status: str) -> str:
    """Mark a commitment done, dropped, or open again."""

    async def go(m: Mentor) -> str:
        ok = await m.update_commitment(commitment_id, status.lower())
        return f"Commitment #{commitment_id} → {status}." if ok else f"No commitment #{commitment_id}."

    return await _run(ctx, go)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_rivals(ctx: Context) -> str:
    """Rivals you've met: strength vs yours, relationship, victory progress
    with turns-to-win at the current pace, and diplomacy left undone."""

    async def go(m: Mentor) -> str:
        snap, rows = await m.rivals()
        return nr.rivals(snap, rows)

    return await _run(ctx, go)


# ---------------------------------------------------------------------------
# Coaching
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True})
async def get_game_review(ctx: Context) -> str:
    """Raw material for a post-game review: milestone turns, metric trends,
    every critical alert (and whether it was shown), alert counts by rule,
    and plan follow-through. Recorded from turn reviews in this game."""

    async def go(m: Mentor) -> str:
        return json.dumps(await m.game_review(), indent=2, default=str)

    return await _run(ctx, go)


@mcp.prompt(name="turn-check")
def turn_check() -> str:
    """Start-of-turn digest."""
    return (
        "Call get_turn_review. Tell me, in at most three short bullets, what deserves my attention "
        "this turn and why, given my goal. For each, offer 2-3 options with trade-offs and let me pick. "
        "Don't list things that are fine. If an alert has an options tool, only call it if I ask."
    )


@mcp.prompt(name="plan-victory")
def plan_victory(victory: str = "") -> str:
    """Check the victory plan and adjust it."""
    target = f" for a {victory} victory" if victory else ""
    return (
        f"Help me plan{target}. Call get_goal_status and get_rivals. Tell me whether the path is viable, "
        "how far ahead or behind the benchmarks I am, and the 3 most important things for the next "
        "10-20 turns. Offer to save each as a commitment with add_commitment. Don't spoil surprises: "
        "no full-game plans."
    )


@mcp.prompt(name="war-check")
def war_check(rival: str = "") -> str:
    """Am I safe? Should I attack?"""
    who = f" against {rival}" if rival else ""
    return (
        f"Assess my military situation{who}. Call get_rivals and get_turn_review. Compare visible strength, "
        "note walls and visible units near my borders (get_tiles scope=area around border cities if needed), "
        "and give me 2-3 options — defend, deter, or attack — with the risks of each. Only visible information."
    )


@mcp.prompt(name="post-game-review")
def post_game_review() -> str:
    """Why did I win or lose?"""
    return (
        "Call get_game_review. Find the story: the 2-3 turning points, warnings that fired and weren't acted on, "
        "and where I fell behind the benchmarks. End with one focused thing to practise next game."
    )


def main() -> None:
    logging.basicConfig(level=os.environ.get("CHANCELLOR_LOG", "WARNING"))
    mcp.run()


if __name__ == "__main__":
    main()
