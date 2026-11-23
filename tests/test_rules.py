from vizier.models import CityView, EmpireSnapshot, Goal, RivalView, UnitView
from vizier.rules import MAX_ALERTS, review, run_rules
from vizier.rules.base import RuleContext


def snap(**kw) -> EmpireSnapshot:
    base = dict(turn=50, civ="Japan", leader="Hojo", total_land=1000, explored_land=300, alive_majors=4)
    base.update(kw)
    return EmpireSnapshot(**base)


def city(i=1, **kw) -> CityView:
    base = dict(city_id=i, name=f"City{i}", x=i, y=i, population=4, amenities=2, amenities_needed=2, housing=8.0)
    base.update(kw)
    return CityView(**base)


def ids(alerts):
    return {a.id for a in alerts}


def test_quiet_empire_has_no_alerts():
    s = snap(
        cities=[city(1, currently_building="BUILDING_MONUMENT"), city(2, currently_building="UNIT_SETTLER")],
        units=[UnitView(9, "UNIT_SCOUT", 0, 0, is_recon=True)],
    )
    alerts, errors = run_rules(RuleContext(snap=s))
    assert errors == []
    assert alerts == []


def test_space_race_critical_at_game_threshold():
    # Victories.CriticalPercentage for technology is 60
    s = snap(rivals=[RivalView(1, "Korea", science_vp=30, science_vp_needed=50)])
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "rival_victory")
    assert a.severity == 1
    s = snap(rivals=[RivalView(1, "Korea", science_vp=10, science_vp_needed=50)])
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "rival_victory")
    assert a.severity == 2


def test_religion_threat_counts_all_majors():
    s = snap(alive_majors=5, rivals=[RivalView(1, "Russia", religion_civs_converted=4, religion_name="Orthodoxy")])
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.key.startswith("religion"))
    assert a.severity == 1 and "4 of 5" in a.detail


def test_diplomatic_turns_to_win_uses_history():
    s = snap(turn=60, rivals=[RivalView(1, "Korea", diplomatic_vp=16)])
    hist = [(50, {"rivals": {"1": {"dvp": 12}}}), (60, {"rivals": {"1": {"dvp": 16}}})]
    a = next(a for a in run_rules(RuleContext(snap=s, history=hist))[0] if a.key.startswith("diplomatic"))
    assert "~10 turns" in a.detail  # 4 DVP in 10 turns → 4 more needs 10


def test_disabled_victory_is_ignored():
    s = snap(enabled_victories={"VICTORY_SCORE"}, rivals=[RivalView(1, "Korea", science_vp=45, science_vp_needed=50)])
    assert not [a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "rival_victory"]


def test_amenity_severity_follows_happiness_table():
    sev = {}
    for net in (-1, -3, -5):
        s = snap(cities=[city(1, amenities=3 + net, amenities_needed=3, currently_building="X")])
        a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "amenities")
        sev[net] = a.severity
    assert sev == {-1: 3, -3: 2, -5: 1}


def test_loyalty_flip_soon_is_critical():
    s = snap(cities=[city(1, loyalty=30, loyalty_per_turn=-5, currently_building="X")])
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "loyalty")
    assert a.severity == 1 and "6 turns" in a.title


def test_expansion_benchmark_scales_with_speed():
    # City 2 due by T40 standard; on Epic (150) that's T60.
    standard = snap(turn=50, cities=[city(1, currently_building="X")])
    epic = snap(turn=50, speed_multiplier=150, cities=[city(1, currently_building="X")])
    assert "expansion:cities<2" in ids(run_rules(RuleContext(snap=standard))[0])
    assert "expansion:cities<2" not in ids(run_rules(RuleContext(snap=epic))[0])


def test_early_game_ranks_root_causes_first():
    s = snap(
        turn=60,
        explored_land=50,  # 5% — behind exploration
        gold=800,  # idle gold (warning-free path: info at <1000)
        cities=[city(1, currently_building="X")],  # behind on city 2
        units=[],
    )
    rv = review(RuleContext(snap=s))
    rules_in_order = [a.rule for a in rv.top]
    assert rules_in_order[0] == "exploration"
    assert "expansion" in rules_in_order
    assert len(rv.top) <= MAX_ALERTS


def test_cap_at_three():
    cities = [city(i, amenities=0, amenities_needed=3, currently_building="NONE") for i in range(1, 6)]
    rv = review(RuleContext(snap=snap(turn=150, cities=cities)))
    assert len(rv.all) > 3 and len(rv.top) == 3


def test_watchdog_shows_only_critical_victory_and_loyalty():
    s = snap(
        cities=[city(1, amenities=0, amenities_needed=6, currently_building="NONE")],
        rivals=[RivalView(1, "Korea", diplomatic_vp=19)],
    )
    rv = review(RuleContext(snap=s), help_level="watchdog")
    assert [a.rule for a in rv.top] == ["rival_victory"]


def test_off_shows_nothing():
    s = snap(rivals=[RivalView(1, "Korea", diplomatic_vp=19)])
    assert review(RuleContext(snap=s), help_level="off").top == []


def test_snoozed_and_retired_rules_are_suppressed():
    s = snap(gold=700, cities=[city(1, currently_building="X"), city(2, currently_building="X")], units=[UnitView(9, "UNIT_SCOUT", 0, 0, is_recon=True)])
    rv = review(RuleContext(snap=s), snoozed={"idle_gold:treasury"})
    assert "idle_gold:treasury" in rv.suppressed
    rv = review(RuleContext(snap=s), dismiss_counts={"idle_gold": 5}, shown_counts={"idle_gold": 6})
    assert "retired" in rv.suppressed["idle_gold:treasury"]


def test_critical_alerts_ignore_snooze():
    s = snap(rivals=[RivalView(1, "Korea", diplomatic_vp=19)])
    rv = review(RuleContext(snap=s), snoozed={"rival_victory:diplomatic:player=1"})
    assert rv.top and rv.top[0].id == "rival_victory:diplomatic:player=1"


def test_suspect_favor_silences_favor_advice():
    hist = [(t, {"favor": 0, "favor_per_turn": 0}) for t in range(100, 125)]
    s = snap(turn=125, favor=0, favor_per_turn=0, rivals=[RivalView(1, "Korea")])
    alerts, _ = run_rules(RuleContext(snap=s, history=hist))
    assert "data_favor:favor" in ids(alerts)


def test_ghost_routes_pause_idle_route_alert():
    s = snap(trade_capacity=3, trade_active=1, trade_ghosts=1)
    got = ids(run_rules(RuleContext(snap=s))[0])
    assert "data_trade:ghost_routes" in got and "trade_slot:routes" not in got


def test_goal_viability_pivot():
    s = snap(turn=110, cities=[city(i, currently_building="X") for i in (1, 2, 3)], favor_per_turn=3)
    alerts, _ = run_rules(RuleContext(snap=s, goal=Goal("science")))
    a = next(a for a in alerts if a.rule == "goal_viability")
    assert "3 cities" in a.detail and "diplomatic" in a.detail


def test_civilian_next_to_barbarian():
    s = snap(units=[UnitView(1, "UNIT_SETTLER", 3, 3, is_civilian=True, threat_distance=1, threat_desc="Barbarian UNIT_WARRIOR")])
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "civilian_at_risk")
    assert a.severity == 1


def test_broken_rule_does_not_hide_others(monkeypatch):
    from vizier.rules import base

    def boom(ctx):
        raise RuntimeError("nope")

    monkeypatch.setattr(base, "RULES", base.RULES + [("boom", boom)])
    import vizier.rules as rules_pkg

    monkeypatch.setattr(rules_pkg, "RULES", base.RULES)
    s = snap(rivals=[RivalView(1, "Korea", diplomatic_vp=19)])
    alerts, errors = rules_pkg.run_rules(RuleContext(snap=s))
    assert errors and "boom" in errors[0]
    assert any(a.rule == "rival_victory" for a in alerts)


def test_turn_one_is_quiet():
    # Live game at T1: settler not founded yet, no scout built yet — nothing to nag about.
    s = snap(turn=1, explored_land=26, units=[UnitView(1, "UNIT_SETTLER", 5, 5, is_civilian=True)])
    assert run_rules(RuleContext(snap=s))[0] == []


def test_unsettled_capital_after_turn_three():
    s = snap(turn=5, explored_land=50, units=[UnitView(1, "UNIT_SETTLER", 5, 5, is_civilian=True)])
    assert "expansion:capital" in ids(run_rules(RuleContext(snap=s))[0])



def test_era_dark_age_risk():
    s = snap(era_score=10, era_dark_threshold=14, era_golden_threshold=26, era_countdown=3)
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "era_score")
    assert a.severity == 1 and "4 more" in a.title


def test_era_golden_within_reach():
    s = snap(era_score=22, era_dark_threshold=14, era_golden_threshold=26, era_countdown=8)
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "era_score")
    assert a.severity == 3 and a.title.startswith("4 era score from a Golden Age")


def test_era_quiet_without_countdown():
    s = snap(era_score=0, era_dark_threshold=14, era_golden_threshold=26, era_countdown=0)
    assert not [a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "era_score"]


def test_amenity_one_away_from_threshold():
    s = snap(cities=[city(1, amenities=5, amenities_needed=3, currently_building="X"),   # net 2 → Happy
                     city(2, amenities=7, amenities_needed=3, currently_building="X"),   # net 4 → Ecstatic
                     city(3, amenities=4, amenities_needed=3, currently_building="X")])  # net 1 → nothing
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "amenity_threshold")
    assert a.data["cities"] == [1, 2] and "+10%" in a.detail and "+20%" in a.detail


def test_luxury_surplus_scales_with_city_count():
    one_city = snap(cities=[city(1, currently_building="X")], luxuries={"RESOURCE_SUGAR": 2, "RESOURCE_SILK": 1})
    a = next(a for a in run_rules(RuleContext(snap=one_city))[0] if a.rule == "luxury_surplus")
    assert a.data["spare"] == {"RESOURCE_SUGAR": 1} and "1 Sugar" in a.title
    five_cities = snap(cities=[city(i, currently_building="X") for i in range(1, 6)], luxuries={"RESOURCE_SUGAR": 2})
    assert not [a for a in run_rules(RuleContext(snap=five_cities))[0] if a.rule == "luxury_surplus"]


def test_pro_pace_is_stricter():
    # T65 with 2 cities: fine against CivBench (city 3 by T75), 5 turns late on pro pace (city 4 by T60)
    s = snap(turn=65, cities=[city(1, currently_building="X"), city(2, currently_building="X")])
    assert not [a for a in run_rules(RuleContext(snap=s, goal=Goal("science")))[0] if a.rule == "expansion"]
    pro = [a for a in run_rules(RuleContext(snap=s, goal=Goal("science", pace="pro")))[0] if a.rule == "expansion"]
    assert pro and "Pro pace: city 4" in pro[0].detail


def test_settle_amenities_guard():
    tight = [city(i, amenities=3, amenities_needed=3, currently_building="X") for i in (1, 2, 3)]
    tight[0].currently_building = "UNIT_SETTLER"
    a = next(a for a in run_rules(RuleContext(snap=snap(cities=tight)))[0] if a.rule == "settle_amenities")
    assert "3 of 3" in a.title
    roomy = [city(i, amenities=6, amenities_needed=3, currently_building="UNIT_SETTLER") for i in (1, 2, 3)]
    assert not [a for a in run_rules(RuleContext(snap=snap(cities=roomy)))[0] if a.rule == "settle_amenities"]



def test_eureka_guard_fires_past_waste_point():
    r = {"item": "TECH_IRRIGATION", "progress": 65, "cost": 100, "boosted": False, "boost_pct": 40, "trigger": "Farm a resource"}
    a = next(a for a in run_rules(RuleContext(snap=snap(research={"tech": r})))[0] if a.rule == "eureka_guard")
    assert "65% done without its eureka" in a.title and "Farm a resource" in a.detail
    early = dict(r, progress=50)
    boosted = dict(r, boosted=True)
    no_boost = dict(r, boost_pct=0)
    for rr in (early, boosted, no_boost):
        assert not [a for a in run_rules(RuleContext(snap=snap(research={"tech": rr})))[0] if a.rule == "eureka_guard"]


def test_district_lock_in_mentions_gov_plaza():
    s = snap(cities=[city(1, currently_building="X")],
             unplaced_districts=[{"district": "DISTRICT_COMMERCIAL_HUB", "cost": 62, "city": "City1"},
                                 {"district": "DISTRICT_GOVERNMENT", "cost": 40, "city": "City1"}])
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "district_lock_in")
    assert "Commercial Hub (62 in City1)" in a.detail and "Government Plaza" in a.detail


def test_serfdom_and_god_king_swaps():
    s = snap(civics={"CIVIC_FEUDALISM"}, available_policies={"POLICY_SERFDOM"}, slotted_policies={"POLICY_GOD_KING"},
             has_pantheon=True)
    got = ids(run_rules(RuleContext(snap=s))[0])
    assert {"policy_swaps:serfdom", "policy_swaps:god_king"} <= got
    s = snap(civics={"CIVIC_FEUDALISM"}, available_policies={"POLICY_SERFDOM"}, slotted_policies={"POLICY_SERFDOM"})
    assert "policy_swaps:serfdom" not in ids(run_rules(RuleContext(snap=s))[0])


def test_governor_titles():
    a = next(a for a in run_rules(RuleContext(snap=snap(governors={"can_appoint": True, "can_promote": False, "unassigned": 1})))[0]
             if a.rule == "governor_titles")
    assert "appointed" in a.detail and "1 appointed governor" in a.detail
    assert not [a for a in run_rules(RuleContext(snap=snap(governors={"can_appoint": False, "can_promote": False, "unassigned": 0})))[0]
                if a.rule == "governor_titles"]


def test_idle_gold_threshold_lower_early():
    two = [city(1, currently_building="X"), city(2, currently_building="X")]
    early = snap(turn=30, gold=250, cities=two)
    late = snap(turn=120, gold=250, cities=two)
    assert "idle_gold:treasury" in ids(run_rules(RuleContext(snap=early))[0])
    assert "idle_gold:treasury" not in ids(run_rules(RuleContext(snap=late))[0])


def test_luxury_surplus_uses_live_per_resource_reach():
    # Cinnamon-style luxury feeding 6 cities: 6 cities need just 1 copy
    s = snap(cities=[city(i, currently_building="X") for i in range(1, 7)],
             luxuries={"RESOURCE_CINNAMON": 2}, luxury_cities={"RESOURCE_CINNAMON": 6})
    a = next(a for a in run_rules(RuleContext(snap=s))[0] if a.rule == "luxury_surplus")
    assert a.data["spare"] == {"RESOURCE_CINNAMON": 1}
