"""The mentor service: source → fog filter → store → rules.

MCP-free, so the same logic can sit behind the
MCP server, a test, or a replay harness.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from vizier import goals as goals_mod
from vizier import options as opt
from vizier.fog import FogFilter
from vizier.models import (
    SEVERITY_NAMES,
    CityView,
    Commitment,
    EmpireSnapshot,
    FixOption,
    Goal,
    TileView,
    UnitView,
)
from vizier.rules import Review, review
from vizier.rules.base import RuleContext, per_turn_rate, turns_to_reach
from vizier.sources.base import StateSource, UIWriter
from vizier.sources.lua_queries import TILE_SCOPES
from vizier.store import Store, game_key

log = logging.getLogger(__name__)


class CityNotFound(LookupError):
    pass


class Mentor:
    def __init__(self, source: StateSource, store: Store, fog: FogFilter | None = None):
        self.source = source
        self.store = store
        self.fog = fog or FogFilter()
        self._key: str | None = None
        self.last_snapshot: EmpireSnapshot | None = None
        self.last_warnings: list[str] = []

    @property
    def writer(self) -> UIWriter | None:
        return self.source if isinstance(self.source, UIWriter) else None

    async def key(self) -> str:
        civ, seed = await self.source.game_identity()
        k = game_key(civ, seed)
        if k != self._key:
            self._key = k
            self.last_snapshot = None
        return k

    # -- snapshot -------------------------------------------------------------

    async def snapshot(self) -> EmpireSnapshot:
        key = await self.key()
        known = [(c["x"], c["y"]) for c in self.store.camps(key)]
        res = await self.source.snapshot(known)
        game = dict(res.game)
        turn = int(game["turn"])
        self.store.update_camps(key, turn, res.camps_seen, res.camps_gone)
        snap = EmpireSnapshot(
            **game,
            cities=[CityView(**c) for c in res.cities],
            units=[UnitView(**u) for u in res.units],
            rivals=self.fog.rivals(res.rivals),
            camps=self.fog.camps(
                [{"x": c["x"], "y": c["y"], "distance_to_city": c["distance"], "seen": True} for c in self.store.camps(key)]
            ),
            full_vision=self.fog.full_vision,
        )
        self.last_snapshot = snap
        self.last_warnings = list(res.warnings)
        return snap

    @staticmethod
    def summarize(s: EmpireSnapshot) -> dict[str, Any]:
        """Per-turn record for trends, turns-to-win and post-game review."""
        return {
            "cities": len(s.cities),
            "explored_pct": round(s.explored_pct, 1),
            "gold": s.gold,
            "faith": s.faith,
            "favor": s.favor,
            "favor_per_turn": s.favor_per_turn,
            "science": s.science_per_turn,
            "culture": s.culture_per_turn,
            "districts": sum(c.specialty_districts for c in s.cities),
            "military": s.our_military_strength,
            "rivals": {
                str(r.player_id): {
                    "name": r.name,
                    "sci_vp": r.science_vp,
                    "dvp": r.diplomatic_vp,
                    "rel_civs": r.religion_civs_converted,
                    "cult_dom": r.culture_civs_dominated,
                    "mil": r.military_strength,
                    "cities": r.num_cities,
                }
                for r in s.rivals
            },
        }

    # -- turn review ------------------------------------------------------------

    async def turn_review(self, push_to_game: bool = True) -> tuple[Review, EmpireSnapshot, Goal | None]:
        snap = await self.snapshot()
        key = await self.key()
        self.store.record_summary(key, snap.turn, self.summarize(snap))

        for c, status in goals_mod.refresh_commitments(self.store.list_commitments(key), snap):
            self.store.update_commitment(key, c.id, status, snap.turn if status == "done" else None)

        goal = self.store.get_goal(key)
        ctx = RuleContext(
            snap=snap,
            goal=goal,
            history=self.store.summaries(key, since_turn=snap.turn - 40),
            commitments=self.store.list_commitments(key),
            camps=self.store.camps(key),
            source_warnings=self.last_warnings,
        )
        rv = review(
            ctx,
            help_level=goal.help_level if goal else "advisor",
            snoozed=self.store.snoozed_ids(key, snap.turn),
            dismiss_counts=self.store.dismiss_counts(key),
            shown_counts=self.store.shown_counts(key),
        )
        self.store.record_alerts(key, snap.turn, rv.all, {a.id for a in rv.top})

        if push_to_game and self.writer is not None and (goal is None or goal.help_level != "off"):
            try:
                await self.writer.push_alerts(
                    snap.turn, [(SEVERITY_NAMES[a.severity], a.title, a.detail) for a in rv.top]
                )
            except Exception:
                log.debug("Could not push alerts to the in-game panel", exc_info=True)
        return rv, snap, goal

    async def explain_alert(self, alert_id: str) -> dict[str, Any] | None:
        return self.store.get_alert(await self.key(), alert_id)

    async def dismiss_alert(self, alert_id: str, snooze_turns: int) -> int:
        snap = self.last_snapshot or await self.snapshot()
        self.store.dismiss(await self.key(), alert_id, snap.turn, snooze_turns)
        return snap.turn + snooze_turns

    # -- fix-it options ------------------------------------------------------------

    async def resolve_city(self, city: str | int) -> CityView:
        snap = self.last_snapshot or await self.snapshot()
        q = str(city).strip()
        for c in snap.cities:
            if q == str(c.city_id) or q.lower() == c.name.lower():
                return c
        matches = [c for c in snap.cities if q.lower() in c.name.lower()]
        if len(matches) == 1:
            return matches[0]
        names = ", ".join(c.name for c in snap.cities)
        raise CityNotFound(f"No city matching '{city}'. Your cities: {names}")

    async def _city_inputs(self, city: str | int) -> tuple[CityView, dict, list, dict, EmpireSnapshot]:
        snap = await self.snapshot()
        cv = await self.resolve_city(city)
        needs = await self.source.city_needs(cv.city_id)
        production = await self.source.production_options(cv.city_id)
        policies = await self.source.policies()
        return cv, needs, production, policies, snap

    async def amenity_options(self, city: str | int) -> tuple[CityView, dict, list[FixOption], list[FixOption]]:
        cv, needs, production, policies, snap = await self._city_inputs(city)
        opts = opt.amenity_options(cv, needs, production, policies, snap, await self.source.rules())
        gap = max(0, -cv.net_amenities)
        return cv, needs, opts, opt.combine_fastest(opts, gap)

    async def loyalty_options(self, city: str | int) -> tuple[CityView, dict, list[FixOption], list[FixOption]]:
        cv, needs, production, policies, snap = await self._city_inputs(city)
        opts = opt.loyalty_options(cv, needs, production, policies, snap)
        gap = max(0.0, -(needs.get("loyalty_per_turn") or cv.loyalty_per_turn))
        return cv, needs, opts, opt.combine_fastest(opts, gap)

    async def housing_options(self, city: str | int) -> tuple[CityView, dict, list[FixOption], list[FixOption]]:
        cv, needs, production, _policies, snap = await self._city_inputs(city)
        opts = opt.housing_options(cv, needs, production, snap, await self.source.rules())
        gap = max(0.0, cv.population - cv.housing + 1)
        return cv, needs, opts, opt.combine_fastest(opts, gap)

    # -- map ---------------------------------------------------------------------

    async def tiles(self, scope: str, filter: str = "", **kwargs: Any) -> list[TileView]:
        if scope not in TILE_SCOPES:
            raise ValueError(f"scope must be one of {TILE_SCOPES}")
        rows = await self.source.tiles(scope, **kwargs)
        tiles = self.fog.tiles(rows)
        if filter == "unimproved_resources":
            tiles = [t for t in tiles if t.resource and not t.improvement and not t.district and t.owner == "me"]
        elif filter == "pillaged":
            tiles = [t for t in tiles if t.pillaged]
        elif filter == "no_road":
            tiles = [t for t in tiles if t.visible and not t.has_road and t.owner == "me"]
        elif filter == "unworked":
            tiles = [t for t in tiles if t.owner == "me" and not t.worked and not t.district]
        elif filter == "luxury":
            tiles = [t for t in tiles if t.resource_class == "luxury"]
        elif filter == "strategic":
            tiles = [t for t in tiles if t.resource_class == "strategic"]
        elif filter:
            raise ValueError(f"unknown filter '{filter}'")
        return tiles

    async def park_sites(self) -> list[dict[str, Any]]:
        return await self.source.park_sites()

    async def settle_spots(self, limit: int = 5) -> tuple[list[dict[str, Any]], int]:
        return await self.source.settle_spots(max(1, min(limit, 10)))

    async def highlight(
        self,
        tiles: list[tuple[int, int]],
        color: str,
        label: str,
        pin: bool,
        look_at: bool,
        icon: str = "",
    ) -> tuple[int, int, str]:
        """Highlight tiles; with pin or icon, also drop labelled map pins (max 5).

        Returns (tiles highlighted, pins placed, resolved icon type)."""
        if self.writer is None:
            raise RuntimeError(f"The {self.source.name} source can't draw on the map")
        n = await self.writer.highlight(tiles, color, look_at)
        pins, resolved = 0, ""
        if icon and not label:
            label = icon.strip().replace("_", " ").title()
        if (pin or icon) and label:
            for x, y in tiles[:5]:
                resolved = await self.writer.add_pin(x, y, label, icon)
                pins += 1
        return n, pins, resolved

    async def clear_highlights(self) -> int:
        """Clear highlights and Vizier's own pins; returns pins removed."""
        if self.writer is None:
            return 0
        await self.writer.clear_highlights()
        return await self.writer.clear_pins()

    # -- planning ----------------------------------------------------------------

    async def set_goal(self, goal: Goal) -> Goal:
        snap = self.last_snapshot or await self.snapshot()
        goal.set_turn = snap.turn
        self.store.set_goal(await self.key(), goal)
        return goal

    async def goal(self) -> Goal | None:
        return self.store.get_goal(await self.key())

    async def goal_status(self) -> dict[str, Any]:
        snap = await self.snapshot()
        key = await self.key()
        for c, status in goals_mod.refresh_commitments(self.store.list_commitments(key), snap):
            self.store.update_commitment(key, c.id, status, snap.turn if status == "done" else None)
        return goals_mod.status(self.store.get_goal(key), snap, self.store.list_commitments(key))

    async def add_commitment(self, text: str, due_turn: int, check_kind: str, check_arg: str) -> Commitment:
        if check_kind not in goals_mod.CHECK_KINDS:
            raise ValueError(f"check must be one of {goals_mod.CHECK_KINDS}")
        snap = self.last_snapshot or await self.snapshot()
        if due_turn <= snap.turn:
            raise ValueError(f"due_turn must be after the current turn ({snap.turn})")
        return self.store.add_commitment(await self.key(), text, snap.turn, due_turn, check_kind, check_arg)

    async def commitments(self, include_closed: bool) -> list[Commitment]:
        key = await self.key()
        snap = self.last_snapshot or await self.snapshot()
        for c, status in goals_mod.refresh_commitments(self.store.list_commitments(key), snap):
            self.store.update_commitment(key, c.id, status, snap.turn if status == "done" else None)
        return self.store.list_commitments(key, include_closed=include_closed)

    async def update_commitment(self, cid: int, status: str) -> bool:
        if status not in ("open", "done", "dropped"):
            raise ValueError("status must be open, done or dropped")
        snap = self.last_snapshot or await self.snapshot()
        return self.store.update_commitment(await self.key(), cid, status, snap.turn if status == "done" else None)

    # -- rivals ------------------------------------------------------------------

    async def rivals(self) -> tuple[EmpireSnapshot, list[dict[str, Any]]]:
        snap = await self.snapshot()
        key = await self.key()
        hist = self.store.summaries(key, since_turn=snap.turn - 40)
        out = []
        for r in snap.rivals:
            def metric(k: str, pid: int = r.player_id):
                return lambda sm: sm.get("rivals", {}).get(str(pid), {}).get(k)

            eta: dict[str, int | None] = {}
            if r.science_vp_needed and r.science_vp:
                eta["science"] = turns_to_reach(r.science_vp, r.science_vp_needed, per_turn_rate(hist, metric("sci_vp")))
            if r.diplomatic_vp:
                eta["diplomatic"] = turns_to_reach(r.diplomatic_vp, 20, per_turn_rate(hist, metric("dvp"), 30))
            if r.religion_civs_converted:
                majors = max(snap.alive_majors, len(snap.rivals) + 1)
                eta["religious"] = turns_to_reach(
                    r.religion_civs_converted, majors, per_turn_rate(hist, metric("rel_civs"), 20)
                )
            d = asdict(r)
            d["military_ratio"] = (
                round(r.military_strength / snap.our_military_strength, 2) if snap.our_military_strength else None
            )
            d["turns_to_win"] = eta
            out.append(d)
        return snap, out

    # -- post-game ----------------------------------------------------------------

    async def game_review(self) -> dict[str, Any]:
        key = await self.key()
        hist = self.store.summaries(key)
        alerts = self.store.alert_history(key)
        commitments = self.store.list_commitments(key)
        first = {}
        for t, s in hist:
            for n in (2, 3, 4, 6):
                if s.get("cities", 0) >= n and f"city_{n}" not in first:
                    first[f"city_{n}"] = t
        critical = [a for a in alerts if a["severity"] == 1]
        return {
            "turns_recorded": len(hist),
            "span": [hist[0][0], hist[-1][0]] if hist else None,
            "milestones": first,
            "trend": [{"turn": t, **{k: s.get(k) for k in ("cities", "explored_pct", "gold", "science", "culture", "military")}} for t, s in hist[:: max(1, len(hist) // 20)]],
            "critical_alerts": [
                {"turn": a["turn"], "alert": a["alert_id"], "title": a["title"], "shown": bool(a["shown"])} for a in critical
            ],
            "alerts_by_rule": _count_by(alerts, "rule"),
            "commitments": {
                "done": sum(c.status == "done" for c in commitments),
                "overdue": sum(c.status == "overdue" for c in commitments),
                "dropped": sum(c.status == "dropped" for c in commitments),
                "open": sum(c.status == "open" for c in commitments),
            },
            "goal": asdict(g) if (g := self.store.get_goal(key)) else None,
        }


def _count_by(rows: list[dict[str, Any]], k: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r[k]] = out.get(r[k], 0) + 1
    return out
