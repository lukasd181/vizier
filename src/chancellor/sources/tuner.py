"""Live game over FireTuner, using civ6-mcp as the client library.

civ6-mcp's GameState is MCP-free by design ("specialist servers import the
same GameState class but expose different tool subsets"); this source reuses
its connection, overview, victory, diplomacy, trade and production queries,
and adds the mentor's own fog-aware queries from lua_queries.

The game allows one tuner connection at a time, so don't run the civ6-mcp
server and this one against the same game simultaneously.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from civ_mcp.connection import GameConnection
from civ_mcp.game_state import GameState

from chancellor.sources import lua_queries as mq
from chancellor.sources.base import SnapshotResult

log = logging.getLogger(__name__)


class TunerSource:
    name = "tuner"

    def __init__(self, host: str = "127.0.0.1", port: int = 4318):
        # FireTuner stays on localhost: the spec's guardrail. Refuse anything else.
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("FireTuner must stay on localhost; remote access goes through the daemon")
        self.conn = GameConnection(host, port)
        self.gs = GameState(self.conn)

    async def game_identity(self) -> tuple[str, int]:
        return await self.gs.get_game_identity()

    async def _write(self, lua: str, timeout: float = 10.0) -> list[str]:
        return await self.conn.execute_write(lua, timeout=timeout)

    async def snapshot(self, known_camps: list[tuple[int, int]]) -> SnapshotResult:
        warnings: list[str] = []

        ov = await self.gs.get_game_overview()
        me = ov.player_id

        state = mq.parse_mentor_state(
            await self._write(mq.build_mentor_state_query(known_camps), timeout=20.0)
        )
        warnings.extend(state["warnings"])

        vp = None
        try:
            vp = await self.gs.get_victory_progress()
        except Exception as e:  # keep the review running; flag the gap
            warnings.append(f"victory progress unavailable: {e}")

        civs = {}
        try:
            civs = {c.player_id: c for c in await self.gs.get_diplomacy()}
        except Exception as e:
            warnings.append(f"diplomacy unavailable: {e}")

        trade_cap = trade_active = trade_ghosts = 0
        try:
            tr = await self.gs.get_trade_routes()
            trade_cap, trade_active, trade_ghosts = tr.capacity, tr.active_count, tr.ghost_count
        except Exception as e:
            warnings.append(f"trade routes unavailable: {e}")

        slotted: set[str] = set()
        available: set[str] = set()
        try:
            pol = await self.gs.get_policies()
            slotted = {sl.current_policy for sl in pol.slots if sl.current_policy}
            available = {p.policy_type for p in pol.available_policies}
        except Exception as e:
            warnings.append(f"policies unavailable: {e}")

        ours = None
        rivals: list[dict[str, Any]] = []
        for p in vp.players if vp else []:
            if p.player_id == me:
                ours = p
                continue
            civ = civs.get(p.player_id)
            actions = set(civ.available_actions or []) if civ else set()
            rel = state["religion"].get(p.player_id)
            cult = state["culture"].get(p.player_id, (0, 0, 0))
            rivals.append(
                {
                    "player_id": p.player_id,
                    # victory progress only prints met players; diplomacy says so explicitly
                    "met": p.name != "Unmet" and (civ.has_met if civ else True),
                    "name": p.name,
                    "score": p.score,
                    "num_cities": p.num_cities,
                    "military_strength": p.military_strength,
                    "science_vp": p.science_vp,
                    "science_vp_needed": p.science_vp_needed,
                    "diplomatic_vp": p.diplomatic_vp,
                    "tourism": p.tourism,
                    "has_religion": p.has_religion,
                    "religion_name": rel[0] if rel else "",
                    "religion_civs_converted": rel[1] if rel else 0,
                    "culture_civs_dominated": cult[0],
                    "our_tourists_from_them": cult[1],
                    "our_staycationers": cult[2],
                    "diplomatic_state": civ.diplomatic_state if civ else "UNKNOWN",
                    "at_war": civ.is_at_war if civ else False,
                    "we_have_delegation": civ.has_delegation if civ else False,
                    "we_have_embassy": civ.has_embassy if civ else False,
                    "can_declare_friendship": "DECLARE_FRIENDSHIP" in actions,
                    "can_form_alliance": "MAKE_ALLIANCE" in actions,
                    "is_friend": (civ.diplomatic_state == "DECLARED_FRIEND") if civ else False,
                    "is_ally": bool(civ and (civ.alliance_type or civ.diplomatic_state == "ALLIED")),
                }
            )

        game = {
            "turn": ov.turn,
            "civ": ov.civ_name,
            "leader": ov.leader_name,
            "difficulty": ov.difficulty,
            "speed_multiplier": ov.speed_cost_multiplier or 100,
            "era": ov.era_name,
            "gold": ov.gold,
            "gold_per_turn": ov.gold_per_turn,
            "faith": ov.faith,
            "faith_per_turn": state["faith_per_turn"],
            "favor": ov.diplomatic_favor,
            "favor_per_turn": ov.favor_per_turn,
            "science_per_turn": ov.science_yield,
            "culture_per_turn": ov.culture_yield,
            "explored_land": ov.explored_land,
            "total_land": ov.total_land,
            "trade_capacity": trade_cap,
            "trade_active": trade_active,
            "trade_ghosts": trade_ghosts,
            "religions_founded": ov.religions_founded,
            "religions_max": ov.religions_max,
            "our_religion": ov.our_religion or "",
            "alive_majors": state["alive_majors"],
            "our_military_strength": ours.military_strength if ours else 0,
            "our_science_vp": ours.science_vp if ours else 0,
            "our_science_vp_needed": ours.science_vp_needed if ours else 0,
            "our_diplomatic_vp": ours.diplomatic_vp if ours else 0,
            "our_tourism": ours.tourism if ours else 0,
            "techs": state["techs"],
            "civics": state["civics"],
            "government": state["government"],
            "enabled_victories": set(ov.enabled_victories or (vp.enabled_victories if vp else set())),
            "era_score": ov.era_score,
            "era_dark_threshold": ov.era_dark_threshold,
            "era_golden_threshold": ov.era_golden_threshold,
            "era_countdown": state["era_countdown"],
            "age": state["age"],
            "luxuries": state["luxuries"],
            "research": state["research"],
            "governors": state["governors"],
            "has_pantheon": state["has_pantheon"],
            "unplaced_districts": state["unplaced_districts"],
            "slotted_policies": slotted,
            "available_policies": available,
        }
        return SnapshotResult(
            game=game,
            cities=state["cities"],
            units=state["units"],
            rivals=rivals,
            camps_seen=state["camps_seen"],
            camps_gone=state["camps_gone"],
            warnings=warnings,
        )

    async def tiles(self, scope: str, **kwargs: Any) -> list[dict[str, Any]]:
        lines = await self._write(mq.build_tiles_query(scope, **kwargs), timeout=20.0)
        return mq.parse_tiles(lines)

    async def city_needs(self, city_id: int) -> dict[str, Any]:
        return mq.parse_city_needs(await self._write(mq.build_city_needs_query(city_id), timeout=15.0))

    async def production_options(self, city_id: int) -> list[dict[str, Any]]:
        return [asdict(o) for o in await self.gs.list_city_production(city_id)]

    async def policies(self) -> dict[str, Any]:
        st = await self.gs.get_policies()
        return {
            "government": st.government_type,
            "slots": [asdict(s) for s in st.slots],
            "available": [asdict(p) for p in st.available_policies],
        }

    async def park_sites(self) -> list[dict[str, Any]]:
        return mq.parse_park_sites(await self._write(mq.build_park_sites_query(), timeout=10.0))

    # -- UIWriter ----------------------------------------------------------

    async def highlight(self, tiles: list[tuple[int, int]], color: str, look_at: bool) -> int:
        for line in await self._write(mq.build_highlight_query(tiles, color, look_at)):
            if line.startswith("HIGHLIGHTED|"):
                return int(line.split("|")[1])
        return 0

    async def clear_highlights(self) -> None:
        await self._write(mq.build_clear_highlights_query())

    async def add_pin(self, x: int, y: int, label: str, icon: str = "") -> str:
        lines = await self._write(mq.build_add_pin_query(x, y, label, icon))
        if any(line.startswith("ERR:") for line in lines):
            raise RuntimeError(f"could not place pin at {x},{y}")
        for line in lines:
            if line.startswith("PIN|"):
                parts = line.split("|")
                return parts[2] if len(parts) > 2 else ""
        return ""

    async def clear_pins(self) -> int:
        for line in await self._write(mq.build_clear_pins_query()):
            if line.startswith("PINS_REMOVED|"):
                return int(line.split("|")[1])
        return 0

    async def push_alerts(self, turn: int, alerts: list[tuple[str, str, str]]) -> None:
        await self._write(mq.build_push_alerts_query(turn, alerts))
