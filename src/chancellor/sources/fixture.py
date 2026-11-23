"""Recorded game state from JSON — for tests, demos and replaying game logs.

Format (all keys optional except identity and snapshot):

    {
      "identity": ["civilization_rome", 1234],
      "snapshot": {<SnapshotResult fields, raw and unfiltered>},
      "tiles": [<raw tile rows with revealed/visible/resource_visible flags>],
      "city_needs": {"<city_id>": {...parse_city_needs output...}},
      "production": {"<city_id>": [{category, item_name, cost, turns, gold_cost}]},
      "policies": {"government": ..., "slots": [...], "available": [...]},
      "parks": [{x, y, appeal, city_id, city}]
    }

Raw rows may deliberately include hidden data: the fog tests rely on it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chancellor.sources.base import SnapshotResult, SourceUnavailable


class FixtureSource:
    name = "fixture"

    def __init__(self, data: dict[str, Any] | str | Path):
        if not isinstance(data, dict):
            data = json.loads(Path(data).read_text())
        self.data = data
        self.highlights: list[tuple[int, int]] = []
        self.pins: list[tuple[int, int, str]] = []
        self.pushed: list[tuple[int, list[tuple[str, str, str]]]] = []

    async def game_identity(self) -> tuple[str, int]:
        civ, seed = self.data["identity"]
        return civ, int(seed)

    async def snapshot(self, known_camps: list[tuple[int, int]]) -> SnapshotResult:
        s = self.data["snapshot"]
        game = dict(s["game"])
        for k in ("techs", "civics", "enabled_victories", "slotted_policies", "available_policies"):
            game[k] = set(game.get(k, []))
        return SnapshotResult(
            game=game,
            cities=s.get("cities", []),
            units=s.get("units", []),
            rivals=s.get("rivals", []),
            camps_seen=[tuple(c) for c in s.get("camps_seen", [])],
            camps_gone=[tuple(c) for c in s.get("camps_gone", [])],
            warnings=s.get("warnings", []),
        )

    async def tiles(self, scope: str, **kwargs: Any) -> list[dict[str, Any]]:
        rows = self.data.get("tiles", [])
        if scope == "area":
            x, y, r = kwargs.get("x", 0), kwargs.get("y", 0), kwargs.get("radius", 2)
            rows = [t for t in rows if abs(t["x"] - x) <= r and abs(t["y"] - y) <= r]
        elif scope == "city":
            rows = [t for t in rows if t.get("city_id") == kwargs.get("city_id")]
        elif scope == "empire":
            rows = [t for t in rows if t.get("owner") == "me"]
        if kwargs.get("resource"):
            rows = [t for t in rows if t.get("resource") == kwargs["resource"]]
        if kwargs.get("improvement"):
            rows = [t for t in rows if t.get("improvement") == kwargs["improvement"]]
        return rows

    async def city_needs(self, city_id: int) -> dict[str, Any]:
        try:
            return self.data["city_needs"][str(city_id)]
        except KeyError:
            raise SourceUnavailable(f"no recorded needs for city {city_id}") from None

    async def production_options(self, city_id: int) -> list[dict[str, Any]]:
        return self.data.get("production", {}).get(str(city_id), [])

    async def policies(self) -> dict[str, Any]:
        return self.data.get("policies", {"government": "", "slots": [], "available": []})

    async def park_sites(self) -> list[dict[str, Any]]:
        return self.data.get("parks", [])

    async def rules(self) -> dict[str, Any]:
        return self.data.get("rules", {})

    async def settle_spots(self, limit: int) -> tuple[list[dict[str, Any]], int]:
        spots = self.data.get("settle", [])
        return spots[:limit], len(spots)

    # UIWriter — records calls so tests can assert on them
    async def highlight(self, tiles: list[tuple[int, int]], color: str, look_at: bool) -> int:
        self.highlights = list(tiles)
        return len(tiles)

    async def clear_highlights(self) -> None:
        self.highlights = []

    async def add_pin(self, x: int, y: int, label: str, icon: str = "") -> str:
        from chancellor.sources.lua_queries import icon_candidates

        known = ("DISTRICT_COMMERCIAL_HUB", "DISTRICT_CAMPUS", "IMPROVEMENT_FARM", "UNIT_SETTLER")
        resolved = next((c for c in icon_candidates(icon) if c in known), "ICON_UNKNOWN" if icon else "")
        self.pins.append((x, y, label, resolved))
        return resolved

    async def clear_pins(self) -> int:
        n = len(self.pins)
        self.pins = []
        return n

    async def push_alerts(self, turn: int, alerts: list[tuple[str, str, str]]) -> None:
        self.pushed.append((turn, alerts))
