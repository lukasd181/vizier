"""Where game state comes from.

TunerSource reads a live game over FireTuner (full features, disables
achievements). FixtureSource replays recorded snapshots for tests and
offline replay of game logs. A logs-and-autosave source for players who keep
achievements fits the same interface; features it can't support report
"unavailable" instead of guessing.

A source returns *raw* records tagged with visibility flags; the Mentor
passes them through fog.FogFilter before anything else sees them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class SnapshotResult:
    """Everything one turn review needs, before fog filtering."""

    game: dict[str, Any]  # EmpireSnapshot fields except cities/units/rivals/camps
    cities: list[dict[str, Any]]
    units: list[dict[str, Any]]
    rivals: list[dict[str, Any]]  # each has met: bool
    camps_seen: list[tuple[int, int, int]] = field(default_factory=list)  # x, y, dist
    camps_gone: list[tuple[int, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SourceUnavailable(RuntimeError):
    """The source can't answer this (e.g. no live game for a tile query)."""


@runtime_checkable
class StateSource(Protocol):
    name: str

    async def game_identity(self) -> tuple[str, int]:
        """(civ_type, random_seed) — keys per-game storage."""
        ...

    async def snapshot(self, known_camps: list[tuple[int, int]]) -> SnapshotResult: ...

    async def tiles(self, scope: str, **kwargs: Any) -> list[dict[str, Any]]: ...

    async def city_needs(self, city_id: int) -> dict[str, Any]: ...

    async def production_options(self, city_id: int) -> list[dict[str, Any]]: ...

    async def policies(self) -> dict[str, Any]: ...

    async def park_sites(self) -> list[dict[str, Any]]: ...


@runtime_checkable
class UIWriter(Protocol):
    """In-game UI effects. They change what's drawn, never game state —
    except pins, which are saved with the game and so need explicit opt-in."""

    async def highlight(self, tiles: list[tuple[int, int]], color: str, look_at: bool) -> int: ...

    async def clear_highlights(self) -> None: ...

    async def add_pin(self, x: int, y: int, label: str, icon: str = "") -> str:
        """Place a pin; returns the resolved icon type ("" for none, ICON_UNKNOWN if no match)."""
        ...

    async def clear_pins(self) -> int:
        """Remove only the pins Vizier placed; returns how many."""
        ...

    async def push_alerts(self, turn: int, alerts: list[tuple[str, str, str]]) -> None: ...
