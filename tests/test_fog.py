"""The guardrail test: no tool output may contain hidden data."""

import json
import os

import pytest
from conftest import HIDDEN_MARKERS, MIDGAME, run

from vizier import narrate as nr
from vizier.fog import FULL_VISION_BANNER, FogFilter, find_leaks, tile_to_dict


def test_unrevealed_tiles_dropped():
    rows = json.loads(MIDGAME.read_text())["tiles"]
    tiles = FogFilter(full_vision=False).tiles(rows)
    assert (20, 20) not in {(t.x, t.y) for t in tiles}


def test_revealed_not_visible_keeps_only_static_facts():
    rows = json.loads(MIDGAME.read_text())["tiles"]
    t = next(t for t in FogFilter(full_vision=False).tiles(rows) if (t.x, t.y) == (18, 11))
    assert t.terrain == "TERRAIN_TUNDRA"
    assert t.resource == "RESOURCE_DEER"
    assert (t.improvement, t.district, t.feature, t.owner, t.has_road, t.appeal) == ("", "", "", "", False, None)


def test_resource_hidden_by_tech_is_blanked():
    rows = json.loads(MIDGAME.read_text())["tiles"]
    t = next(t for t in FogFilter(full_vision=False).tiles(rows) if (t.x, t.y) == (15, 14))
    assert t.resource == "" and t.resource_class == ""


def test_unmet_rivals_dropped():
    rows = json.loads(MIDGAME.read_text())["snapshot"]["rivals"]
    assert [r.name for r in FogFilter(full_vision=False).rivals(rows)] == ["Korea"]


def test_tile_at_origin_keeps_coordinates():
    rows = json.loads(MIDGAME.read_text())["tiles"]
    t = next(t for t in FogFilter(full_vision=False).tiles(rows) if (t.x, t.y) == (0, 0))
    d = tile_to_dict(t)
    assert d["x"] == 0 and d["y"] == 0


def test_no_leaks_in_any_mentor_output(mentor):
    """Every text the mentor can produce from the fixture, scanned for markers."""
    outputs = []
    rv, snap, goal = run(mentor.turn_review())
    outputs.append(nr.turn_review(rv, snap, goal))
    for a in rv.all:
        outputs.append(nr.explain(run(mentor.explain_alert(a.id)), a.id))
    s, rows = run(mentor.rivals())
    outputs.append(nr.rivals(s, rows))
    for scope, kw in [("revealed", {}), ("empire", {}), ("area", {"x": 18, "y": 18, "radius": 5})]:
        outputs.append(nr.tiles(run(mentor.tiles(scope, **kw))))
    outputs.append(nr.goal_status(run(mentor.goal_status())))
    outputs.append(json.dumps(run(mentor.game_review()), default=str))
    cv, needs, opts, combo = run(mentor.amenity_options("Nagoya"))
    outputs.append(nr.fix_options("amenity", cv, needs, opts, combo, nr.amenity_headline(cv, needs)))
    leaks = find_leaks("\n".join(outputs), HIDDEN_MARKERS)
    assert leaks == [], f"hidden data leaked: {leaks}"


def test_full_vision_is_stamped(monkeypatch):
    monkeypatch.setenv("VIZIER_DEBUG_FULL_VISION", "1")
    f = FogFilter()
    assert f.full_vision
    assert f.stamp("x").startswith(FULL_VISION_BANNER)


def test_full_vision_off_by_default(monkeypatch):
    monkeypatch.delenv("VIZIER_DEBUG_FULL_VISION", raising=False)
    assert FogFilter().full_vision is False
    assert FogFilter().stamp("x") == "x"
