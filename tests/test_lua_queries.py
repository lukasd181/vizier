"""Execute the real Lua queries against a fake Civ 6 API (tests/fake_civ6.lua).

This can't prove the game accepts every call — only a live game can — but it
does prove the queries run end to end, that the source-side fog checks drop
planted hidden data, and that the parsers read what the Lua prints.
"""

from pathlib import Path

import pytest
from conftest import HIDDEN_MARKERS

from vizier.fog import FogFilter, find_leaks
from vizier.sources import lua_queries as q

lupa = pytest.importorskip("lupa")

FAKE = (Path(__file__).parent / "fake_civ6.lua").read_text()


def execute(lua_source: str) -> list[str]:
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(FAKE)
    # The queries are chunks with top-level `return`s; wrap so they run as a function.
    rt.execute("local f = assert(load(...)); f()", lua_source)
    out = rt.globals().OUT
    return [out[i] for i in range(1, len(out) + 1)]


ALL_BUILDERS = {
    "state": lambda: q.build_mentor_state_query([(3, 3), (2, 0)]),
    "tiles_area": lambda: q.build_tiles_query("area", x=2, y=2, radius=3),
    "tiles_city": lambda: q.build_tiles_query("city", city_id=65536),
    "tiles_revealed": lambda: q.build_tiles_query("revealed"),
    "tiles_resource": lambda: q.build_tiles_query("revealed", resource="RESOURCE_SILK"),
    "needs": lambda: q.build_city_needs_query(65536),
    "park": q.build_park_sites_query,
}


@pytest.mark.parametrize("name", ALL_BUILDERS)
def test_query_runs_and_ends_with_sentinel(name):
    lines = execute(ALL_BUILDERS[name]())
    assert lines[-1] == "---END---"
    assert not [l for l in lines if l.startswith("WARN|")], lines


@pytest.mark.parametrize("name", ALL_BUILDERS)
def test_query_output_has_no_hidden_data(name):
    lines = execute(ALL_BUILDERS[name]())
    assert find_leaks("\n".join(lines), HIDDEN_MARKERS) == []


def test_state_query_parses():
    st = q.parse_mentor_state(execute(q.build_mentor_state_query([(3, 3), (2, 0)])))
    assert st["government"] == "GOVERNMENT_CHIEFDOM"
    assert st["techs"] == {"TECH_POTTERY"} and st["civics"] == {"CIVIC_CODE_OF_LAWS"}
    assert st["alive_majors"] == 3
    (kyoto,) = st["cities"]
    assert (kyoto["name"], kyoto["amenities"], kyoto["amenities_needed"]) == ("Kyoto", 2, 3)
    assert kyoto["currently_building"] == "BUILDING_ARENA" and kyoto["specialty_districts"] == 1
    assert kyoto["has_garrison"] is True  # the warrior stands on the city
    builder = next(u for u in st["units"] if u["unit_type"] == "UNIT_BUILDER")
    # the visible barbarian at (2,2) is 1 away; the one in fog at (5,5) is ignored;
    # Spain's visible warrior isn't hostile (not at war)
    assert builder["threat_distance"] == 1 and builder["threat_desc"] == "Barbarian UNIT_WARRIOR"
    assert builder["is_civilian"] is True
    # camp at (3,3) is visible; the one at (5,0) is only revealed, so it isn't reported
    assert st["camps_seen"] == [(3, 3, 3)]
    # remembered camp at (2,0) is in sight and gone; (3,3) is still there
    assert st["camps_gone"] == [(2, 0)]
    # Korea (met) founded Buddhism, majority in 2 civs (us + Korea); Spain's religion is hidden
    assert st["religion"] == {1: ("Buddhism", 2)}
    assert set(st["culture"]) == {1}
    assert st["era_countdown"] == 7 and st["age"] == "golden"
    assert st["luxuries"] == {"RESOURCE_SILK": 2}
    assert st["research"]["tech"] == {"item": "TECH_MILITARY_ENGINEERING", "progress": 70.0, "cost": 100.0,
                                      "boosted": False, "boost_pct": 40, "trigger": "Build a quarry"}
    assert st["research"]["civic"]["item"] == "CIVIC_CODE_OF_LAWS" and st["research"]["civic"]["boost_pct"] == 0
    assert st["governors"] == {"can_appoint": True, "can_promote": False, "unassigned": 0}
    assert st["has_pantheon"] is True
    assert st["unplaced_districts"] == [{"district": "DISTRICT_COMMERCIAL_HUB", "cost": 97, "city": "Kyoto"}]


def test_tiles_fog_at_source():
    rows = q.parse_tiles(execute(q.build_tiles_query("revealed")))
    by = {(r["x"], r["y"]): r for r in rows}
    assert (5, 5) not in by  # unrevealed
    fort = by[(4, 0)]  # revealed, not visible
    assert (fort["improvement"], fort["district"], fort["feature"], fort["owner"]) == ("", "", "", "")
    assert by[(2, 1)]["resource"] == ""  # niter needs a tech
    assert by[(1, 0)]["resource"] == "RESOURCE_SILK"
    worked = by[(0, 1)]
    assert worked["worked"] and worked["has_road"] and worked["city_id"] == 65536
    # and the Python layer agrees
    tiles = FogFilter(full_vision=False).tiles(rows)
    assert len(tiles) == len(rows)


def test_city_needs_parses():
    needs = q.parse_city_needs(execute(q.build_city_needs_query(65536)))
    assert (needs["amenities"], needs["amenities_needed"], needs["population"]) == (2, 3, 5)
    assert needs["amenity_sources"]["Luxuries"] == 2
    assert needs["housing_sources"]["Water"] == 3.0
    (silk,) = needs["unimproved_luxuries"]
    assert silk["resource"] == "RESOURCE_SILK" and silk["builder_id"] == 11 and silk["builder_distance"] == 1
    assert needs["loyalty"] == 90.0 and needs["turns_to_conversion"] == 9
    assert ("Pressure from Korea", -6.0) in needs["loyalty_sources"]


def test_park_sites_only_revealed():
    sites = q.parse_park_sites(execute(q.build_park_sites_query()))
    assert [(s["x"], s["y"]) for s in sites] == [(1, 0)]
    assert sites[0]["city"] == "Kyoto"


def test_city_not_found_raises():
    with pytest.raises(ValueError):
        q.parse_city_needs(execute(q.build_city_needs_query(999)))


def test_mod_lua_compiles():
    src = (Path(__file__).parent.parent / "mod" / "VizierAlerts" / "UI" / "VizierAlerts.lua").read_text()
    rt = lupa.LuaRuntime()
    err = rt.eval("function(s) local f, e = load(s); return e end")(src)
    assert err is None, err


def test_ui_queries_compile():
    rt = lupa.LuaRuntime()
    check = rt.eval("function(s) local f, e = load(s); return e end")
    for src in (
        q.build_highlight_query([(1, 2), (3, 4)], "teal"),
        q.build_clear_highlights_query(),
        q.build_add_pin_query(1, 2, 'Silk "here"'),
        q.build_add_pin_query(1, 2, 'Hub', 'commercial hub'),
        q.build_clear_pins_query(),
        q.build_push_alerts_query(7, [("critical", 'Korea "wins"', "line\nbreak \\ slash")]),
        q.build_turn_seq_query(),
    ):
        assert check(src) is None, src


def test_icon_candidates():
    assert q.icon_candidates("commercial hub")[0] == "DISTRICT_COMMERCIAL_HUB"
    assert q.icon_candidates("DISTRICT_CAMPUS") == ["DISTRICT_CAMPUS"]
    assert q.icon_candidates("") == []


def test_pin_icon_resolves_in_fake_game():
    lua = q.build_add_pin_query(1, 0, "Hub", "campus")
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(FAKE)
    rt.execute("""
      local pins = {}
      PlayerConfigurations[0].GetMapPin = function(self, x, y)
        local p = {id = 7}
        function p:GetID() return self.id end
        function p:SetName(n) self.name = n end
        function p:SetIconName(n) self.icon = n; PIN_ICON = n end
        return p
      end
      Network = {BroadcastPlayerInfo = function() end}
    """)
    rt.execute("local f = assert(load(...)); f()", lua)
    out = rt.globals().OUT
    lines = [out[i] for i in range(1, len(out) + 1)]
    assert "PIN|7|DISTRICT_CAMPUS" in lines
    assert rt.globals().PIN_ICON == "ICON_DISTRICT_CAMPUS"


def test_identity_query():
    assert q.parse_identity(execute(q.build_identity_query())) == ("america", -2096689920)


def test_empire_query_parses_and_hides_unmet():
    lines = execute(q.build_empire_query())
    assert find_leaks("\n".join(lines), HIDDEN_MARKERS) == []
    emp = q.parse_empire(lines)
    ov = emp["overview"]
    assert (ov["turn"], ov["civ"], ov["leader"], ov["gold"], ov["gold_per_turn"]) == (11, "Japan", "Teddy Roosevelt", 60.0, 5.0)
    assert ov["favor"] == 7 and ov["favor_per_turn"] == 1  # tier-1 government
    assert emp["era"] == ("Ancient Era", 2, 11, 25)
    assert emp["difficulty"] == "Prince" and emp["speed_multiplier"] == 100
    assert emp["enabled_victories"] == {"VICTORY_TECHNOLOGY", "VICTORY_SCORE"}
    assert emp["me"] == {"military_strength": 20, "science_vp": 0, "science_vp_needed": 50, "diplomatic_vp": 2, "tourism": 1}
    (korea,) = emp["rivals"]  # Spain (unmet) is not listed
    assert (korea["name"], korea["military_strength"], korea["science_vp"], korea["diplomatic_state"]) == ("Korea", 45, 3, "NEUTRAL")
    assert korea["can_declare_friendship"] and not korea["can_form_alliance"]
    assert emp["trade"] == (1, 0, 1)  # the only route's trader no longer exists → ghost
    total = emp["explored"][1]
    assert 0 < emp["explored"][0] <= total
    assert emp["policies"]["slots"][0] == {"slot_index": 0, "slot_type": "SLOT_ECONOMIC", "current_policy": "POLICY_GOD_KING"}
    assert {a["policy_type"] for a in emp["policies"]["available"]} == {"POLICY_GOD_KING", "POLICY_SURVEY"}


def test_production_query_parses():
    opts = q.parse_production(execute(q.build_production_query(65536)))
    by = {o["item_name"]: o for o in opts}
    assert set(by) == {"UNIT_SETTLER", "BUILDING_MONUMENT", "DISTRICT_COMMERCIAL_HUB"}
    assert by["BUILDING_MONUMENT"] == {"category": "BUILDING", "item_name": "BUILDING_MONUMENT", "cost": 80, "turns": 8,
                                       "gold_cost": 240, "is_repair": False}
    assert by["DISTRICT_COMMERCIAL_HUB"]["gold_cost"] == -1


def test_settle_query_ranks_legal_revealed_sites():
    lines = execute(q.build_settle_query(limit=3))
    assert find_leaks("\n".join(lines), HIDDEN_MARKERS) == []
    spots, total = q.parse_settle(lines)
    assert total > 0 and spots
    best = spots[0]
    # (4,2): fresh water, hills, a mountain next to it, and the game's advisor's pick
    assert (best["x"], best["y"]) == (4, 2)
    assert best["fresh_water"] and best["hills"] and best["adjacent_mountains"] == 1 and best["game_recommends"]
    for s in spots:
        assert s["distance"] >= 4  # IsValidFoundLocation in the fake: 4+ from the capital
        assert not (s["x"] >= 4 and s["y"] >= 4)  # never an unrevealed plot
    for a in spots:
        for b in spots:
            if a is not b:
                assert max(abs(a["x"] - b["x"]), abs(a["y"] - b["y"])) >= 4


def test_rules_query_reads_live_tables():
    rules = q.parse_rules(execute(q.build_rules_query()))
    assert rules["entertainment_buildings"] == {"BUILDING_ARENA": 2, "BUILDING_PALACE": 2}
    assert rules["housing_buildings"] == {"BUILDING_PALACE": 1}
    assert rules["luxury_cities"]["RESOURCE_SILK"] == 4


def test_settle_counts_reef_and_owned_luxuries():
    spots, _ = q.parse_settle(execute(q.build_settle_query(limit=3)))
    best = spots[0]
    assert (best["x"], best["y"]) == (4, 2)
    # mountain (+1) + reef (+2) next to it
    assert best["adjacent_reefs"] == 1 and best["campus_adjacency"] == 3
    # Silk is already in our borders, so it never counts as a new luxury type
    for s in spots:
        if "RESOURCE_SILK" in s["luxuries"]:
            assert s["new_luxury_types"] == 0


def _run_with_mode(lua_source: str, mode_lua: str) -> list[str]:
    rt = lupa.LuaRuntime(unpack_returned_tuples=True)
    rt.execute(FAKE)
    rt.execute(mode_lua)
    rt.execute("local f = assert(load(...)); f()", lua_source)
    out = rt.globals().OUT
    return [out[i] for i in range(1, len(out) + 1)]


@pytest.mark.parametrize(
    "mode_lua, blocked",
    [
        ("", False),  # single player: no multiplayer flag set
        ("GameConfiguration.IsAnyMultiplayer = function() return true end", True),
        ("GameConfiguration.IsHotseat = function() return true end", True),  # not covered by IsAnyMultiplayer
        ("GameConfiguration.IsPlayByCloud = function() return true end", True),
    ],
)
def test_single_player_guard(mode_lua, blocked):
    lines = _run_with_mode(q.LUA_SINGLE_PLAYER_GUARD + q.build_mentor_state_query([]), mode_lua)
    if blocked:
        assert lines == ["ERR:MULTIPLAYER", "---END---"]  # nothing else read
    else:
        assert any(l.startswith("CITY|") for l in lines)
