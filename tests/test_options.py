from chancellor.models import CityView, EmpireSnapshot, FixOption
from chancellor.options import amenity_options, combine_fastest, rank


def test_rank_fastest_first_unknown_last():
    opts = [
        FixOption("slow", "building", 2, "amenity", 10, "x"),
        FixOption("unknown", "trade", 1, "amenity", None, "x"),
        FixOption("now", "policy", 1, "amenity", 0, "x"),
        FixOption("now-bigger", "policy", 2, "amenity", 0, "x"),
    ]
    assert [o.action for o in rank(opts)] == ["now-bigger", "now", "slow", "unknown"]


def test_combine_skips_build_when_buy_chosen():
    opts = rank(
        [
            FixOption("Buy Arena", "building", 2, "amenity", 0, "300 gold", gold_cost=300),
            FixOption("Build Arena", "building", 2, "amenity", 8, "150 production"),
            FixOption("Improve Silk", "luxury", 1, "amenity", 2, "charge"),
        ]
    )
    assert [o.action for o in combine_fastest(opts, 3)] == ["Buy Arena", "Improve Silk"]


def test_buy_needs_gold():
    city = CityView(1, "A", 0, 0, 5, 0, 3, 6.0)
    snap = EmpireSnapshot(turn=50, civ="X", leader="Y", gold=100)
    prod = [{"item_name": "BUILDING_ARENA", "cost": 150, "turns": 8, "gold_cost": 300, "is_repair": False}]
    opts = amenity_options(city, {}, prod, {}, snap)
    buy = next(o for o in opts if o.action == "Buy Arena")
    assert buy.turns is None and "200 more gold" in buy.notes
    assert next(o for o in opts if o.action == "Build Arena").gain == 2  # Buildings.Entertainment


def test_negative_policy_offered_for_removal():
    city = CityView(1, "A", 0, 0, 5, 0, 3, 6.0)
    snap = EmpireSnapshot(turn=150, civ="X", leader="Y")
    pol = {"slots": [{"current_policy": "POLICY_ROBBER_BARONS"}], "available": []}
    opts = amenity_options(city, {}, [], pol, snap)
    rm = next(o for o in opts if o.action == "Unslot Robber Barons")
    assert rm.gain == 2


def test_live_rules_override_gamedata():
    # REA found the live ruleset's Palace/Arena values can differ from gamedata's
    city = CityView(1, "A", 0, 0, 5, 0, 3, 6.0)
    snap = EmpireSnapshot(turn=50, civ="X", leader="Y", gold=0)
    prod = [{"item_name": "BUILDING_ARENA", "cost": 150, "turns": 8, "gold_cost": -1, "is_repair": False}]
    live = {"entertainment_buildings": {"BUILDING_ARENA": 3}, "luxury_cities": {"RESOURCE_SILK": 6}}
    arena = next(o for o in amenity_options(city, {}, prod, {}, snap, live) if o.action == "Build Arena")
    assert arena.gain == 3
    needs = {"unimproved_luxuries": [{"resource": "RESOURCE_SILK", "x": 1, "y": 1, "pillaged": False,
                                      "builder_id": 1, "builder_distance": 2, "builder_moves": 2}]}
    silk = next(o for o in amenity_options(city, needs, [], {}, snap, live) if "Silk" in o.action)
    assert "up to 6 cities" in silk.notes
