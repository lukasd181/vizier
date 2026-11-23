"""The one visibility filter between the game and every mentor tool.

FireTuner's GameCore and InGame contexts can read the whole map. Sources tag
each raw record with what the local player can see (revealed / visible /
resource_visible / met) and this module is the only place that turns raw
records into the views rules and tools consume. The Lua queries already
filter at the source; this is the second, testable layer.

Rules:
  * Tiles must be revealed. For revealed-but-not-visible plots only static
    facts survive (terrain, and resources the player's techs reveal);
    improvements, owners, districts, roads, pillage state and appeal can
    change after the player last looked, so they are blanked.
  * Resources only when resource_visible (the engine's IsResourceVisible).
  * Rivals only when met.
  * Barbarian camps only when seen; remembered camps carry their last-seen turn.

Debug full vision (CHANCELLOR_DEBUG_FULL_VISION=1) disables filtering for
developer testing only; every tool output is then stamped with a banner.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any, Iterable

from chancellor.models import CampView, RivalView, TileView

FULL_VISION_ENV = "CHANCELLOR_DEBUG_FULL_VISION"
FULL_VISION_BANNER = (
    "⚠ DEBUG FULL VISION IS ON — output may include hidden information. "
    "Developer testing only."
)

_DYNAMIC_TILE_FIELDS = (
    "feature",
    "improvement",
    "pillaged",
    "district",
    "owner",
    "owner_id",
    "city_id",
    "worked",
    "has_road",
    "appeal",
)
_TILE_DEFAULTS = {f.name: f.default for f in TileView.__dataclass_fields__.values()}


def full_vision_enabled() -> bool:
    return os.environ.get(FULL_VISION_ENV, "") == "1"


class FogFilter:
    def __init__(self, full_vision: bool | None = None):
        self.full_vision = full_vision_enabled() if full_vision is None else full_vision

    # -- tiles -------------------------------------------------------------

    def tiles(self, rows: Iterable[dict[str, Any]]) -> list[TileView]:
        out: list[TileView] = []
        for r in rows:
            if not self.full_vision and not r.get("revealed", False):
                continue
            fields = {k: r[k] for k in _TILE_DEFAULTS if k in r}
            if not self.full_vision:
                if not r.get("resource_visible", False):
                    fields["resource"] = ""
                    fields["resource_class"] = ""
                if not r.get("visible", False):
                    for k in _DYNAMIC_TILE_FIELDS:
                        fields[k] = _TILE_DEFAULTS[k]
            out.append(TileView(**fields))
        return out

    # -- rivals ------------------------------------------------------------

    def rivals(self, rows: Iterable[dict[str, Any]]) -> list[RivalView]:
        allowed = set(RivalView.__dataclass_fields__)
        return [
            RivalView(**{k: v for k, v in r.items() if k in allowed})
            for r in rows
            if self.full_vision or r.get("met", False)
        ]

    # -- camps -------------------------------------------------------------

    def camps(self, rows: Iterable[dict[str, Any]]) -> list[CampView]:
        return [
            CampView(x=r["x"], y=r["y"], distance_to_city=r["distance_to_city"])
            for r in rows
            if self.full_vision or r.get("seen", False)
        ]

    def stamp(self, text: str) -> str:
        return f"{FULL_VISION_BANNER}\n{text}" if self.full_vision else text


def find_leaks(output: str, hidden_markers: Iterable[str]) -> list[str]:
    """Return every hidden marker that appears in a tool's output.

    Tests plant markers (e.g. a resource only a hidden plot holds, an unmet
    civ's name) in raw source data and assert this comes back empty.
    """
    return [m for m in hidden_markers if m and m in output]


def tile_to_dict(t: TileView) -> dict[str, Any]:
    """Compact dict: coordinates always, other fields only when set.

    (Compared with `is`/`==` per type — 0 == False in Python, so a membership
    test against False would drop x=0.)
    """
    out: dict[str, Any] = {}
    for k, v in asdict(t).items():
        if k in ("x", "y", "terrain"):
            out[k] = v
        elif v is None or v is False or v == "" or (k in ("owner_id", "city_id") and v == -1):
            continue
        else:
            out[k] = v
    return out
