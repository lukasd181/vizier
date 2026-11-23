"""Live game over FireTuner (chancellor.tuner), with Vizier's own Lua queries.

Two round-trips per snapshot: the empire query (overview, met rivals, trade,
policies) and the state query (cities, units, camps, research, districts).

The game allows one tuner connection at a time, so only one program
(this server, civ6-mcp, FireTuner) can talk to a game at once.
"""

from __future__ import annotations

import logging
from typing import Any

from chancellor.sources import lua_queries as mq
from chancellor.sources.base import SnapshotResult
from chancellor.tuner import GameConnection

log = logging.getLogger(__name__)


class TunerSource:
    name = "tuner"

    def __init__(self, host: str = "127.0.0.1", port: int = 4318):
        self.conn = GameConnection(host, port)  # refuses non-localhost hosts

    async def game_identity(self) -> tuple[str, int]:
        return mq.parse_identity(await self._write(mq.build_identity_query()))

    async def _write(self, lua: str, timeout: float = 10.0) -> list[str]:
        return await self.conn.execute_write(lua, timeout=timeout)

    async def snapshot(self, known_camps: list[tuple[int, int]]) -> SnapshotResult:
        emp = mq.parse_empire(await self._write(mq.build_empire_query(), timeout=20.0))
        state = mq.parse_mentor_state(
            await self._write(mq.build_mentor_state_query(known_camps), timeout=20.0)
        )
        warnings: list[str] = list(state["warnings"])
        ov = emp["overview"]
        if not ov:
            warnings.append("empire overview unavailable")

        rivals: list[dict[str, Any]] = []
        for r in emp["rivals"]:
            rel = state["religion"].get(r["player_id"])
            cult = state["culture"].get(r["player_id"], (0, 0, 0))
            rivals.append(
                r
                | {
                    "met": True,  # the empire query only lists players we have met
                    "religion_name": rel[0] if rel else "",
                    "religion_civs_converted": rel[1] if rel else 0,
                    "culture_civs_dominated": cult[0],
                    "our_tourists_from_them": cult[1],
                    "our_staycationers": cult[2],
                }
            )

        me = emp["me"]
        explored, total_land = emp["explored"]
        era_name, era_score, era_dark, era_golden = emp["era"]
        founded, max_rel = emp["religions"]
        cap, active, ghosts = emp["trade"]
        pol = emp["policies"]
        game = {
            "turn": ov.get("turn", 0),
            "civ": ov.get("civ", ""),
            "leader": ov.get("leader", ""),
            "difficulty": emp["difficulty"],
            "speed_multiplier": emp["speed_multiplier"],
            "era": era_name,
            "gold": ov.get("gold", 0.0),
            "gold_per_turn": ov.get("gold_per_turn", 0.0),
            "faith": ov.get("faith", 0.0),
            "faith_per_turn": state["faith_per_turn"],
            "favor": ov.get("favor", 0),
            "favor_per_turn": ov.get("favor_per_turn", 0),
            "science_per_turn": ov.get("science_per_turn", 0.0),
            "culture_per_turn": ov.get("culture_per_turn", 0.0),
            "explored_land": explored,
            "total_land": total_land,
            "trade_capacity": cap,
            "trade_active": active,
            "trade_ghosts": ghosts,
            "religions_founded": founded,
            "religions_max": max_rel,
            "our_religion": emp["our_religion"],
            "alive_majors": state["alive_majors"],
            "our_military_strength": me.get("military_strength", 0),
            "our_science_vp": me.get("science_vp", 0),
            "our_science_vp_needed": me.get("science_vp_needed", 0),
            "our_diplomatic_vp": me.get("diplomatic_vp", 0),
            "our_tourism": me.get("tourism", 0),
            "techs": state["techs"],
            "civics": state["civics"],
            "government": state["government"],
            "enabled_victories": emp["enabled_victories"],
            "era_score": era_score,
            "era_dark_threshold": era_dark,
            "era_golden_threshold": era_golden,
            "era_countdown": state["era_countdown"],
            "age": state["age"],
            "luxuries": state["luxuries"],
            "research": state["research"],
            "governors": state["governors"],
            "has_pantheon": state["has_pantheon"],
            "unplaced_districts": state["unplaced_districts"],
            "slotted_policies": {sl["current_policy"] for sl in pol["slots"] if sl["current_policy"]},
            "available_policies": {a["policy_type"] for a in pol["available"]},
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
        return mq.parse_production(await self._write(mq.build_production_query(city_id), timeout=15.0))

    async def policies(self) -> dict[str, Any]:
        return mq.parse_policies(await self._write(mq.build_policies_query()))

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
