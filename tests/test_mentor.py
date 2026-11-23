"""End-to-end through Mentor with the recorded mid-game fixture."""

import pytest
from conftest import run

from chancellor.mentor import CityNotFound
from chancellor.models import Goal


def test_turn_review_top_three_and_ranking(mentor):
    rv, snap, goal = run(mentor.turn_review())
    assert snap.turn == 85 and goal is None
    assert len(rv.top) == 3
    # Critical first (Nagoya: 40 loyalty at -5/turn flips in 8), then — T85 being early
    # game — warnings by root cause: exploration (18% < 25% by T80), expansion (city 3 due T75).
    assert [a.id for a in rv.top] == ["loyalty:city=131073", "exploration:explored", "expansion:cities<3"]
    all_ids = {a.id for a in rv.all}
    assert "rival_victory:diplomatic:player=1" in all_ids  # Korea 15/20
    assert "rival_victory:religion:player=1" in all_ids  # 3 of 5 civs
    assert "amenities:city=131073" in all_ids
    assert "loyalty:city=131073" in all_ids
    assert "civilian_at_risk:unit=1" in all_ids
    assert "barbarian_camp:camp=16,9" in all_ids
    assert "empty_queue:cities" in all_ids
    assert "idle_gold:treasury" in all_ids
    assert "trade_slot:routes" in all_ids
    assert "diplomacy:friendship" in all_ids


def test_alerts_pushed_to_game_panel(mentor):
    rv, snap, _ = run(mentor.turn_review())
    turn, pushed = mentor.source.pushed[-1]
    assert turn == 85 and [p[1] for p in pushed] == [a.title for a in rv.top]


def test_help_level_off_pushes_nothing(mentor):
    run(mentor.set_goal(Goal("science", help_level="off")))
    rv, _, _ = run(mentor.turn_review())
    assert rv.top == [] and mentor.source.pushed == []


def test_explain_and_dismiss(mentor):
    rv, _, _ = run(mentor.turn_review())
    a = next(a for a in rv.all if a.rule == "idle_gold")
    rec = run(mentor.explain_alert(a.id))
    assert rec["data"]["gold"] == 640 and rec["history"] == [85]
    until = run(mentor.dismiss_alert(a.id, 5))
    assert until == 90
    rv2, _, _ = run(mentor.turn_review())
    assert a.id in rv2.suppressed


def test_commitments_auto_done_and_overdue(mentor):
    run(mentor.snapshot())
    c1 = run(mentor.add_commitment("Get writing", 90, "tech", "TECH_WRITING"))
    c2 = run(mentor.add_commitment("Third city", 86, "city_count", "3"))
    mentor.store.db.execute("UPDATE commitments SET due_turn = 80 WHERE id = ?", (c2.id,))
    mentor.store.db.commit()
    rv, _, _ = run(mentor.turn_review())
    statuses = {c.id: c.status for c in run(mentor.commitments(True))}
    assert statuses == {c1.id: "done", c2.id: "overdue"}
    assert f"commitment_overdue:commitment={c2.id}" in {a.id for a in rv.all}


def test_commitment_validation(mentor):
    run(mentor.snapshot())
    with pytest.raises(ValueError):
        run(mentor.add_commitment("past", 10, "manual", ""))
    with pytest.raises(ValueError):
        run(mentor.add_commitment("bad", 99, "vibes", ""))


def test_goal_status_benchmarks(mentor):
    run(mentor.set_goal(Goal("science")))
    st = run(mentor.goal_status())
    assert st["cities"]["have"] == 2 and st["cities"]["behind_by_turns"] == 10
    assert st["cities"]["next"] == {"cities": 3, "by_turn": 75}
    assert st["viability"]["viable"] is True  # T85 < T100
    assert st["exploration"]["explored_pct"] == 18.0


def test_amenity_options_for_nagoya(mentor):
    cv, needs, opts, combo = run(mentor.amenity_options("nagoya"))
    actions = [o.action for o in opts]
    # Silk is a new luxury type (Wine is already held, so its plot isn't offered)
    assert "Improve Silk at (11,10)" in actions
    assert not any("Wine" in a for a in actions)
    assert actions[0] == "Improve Silk at (11,10)"  # fastest option that actually helps
    assert "Build Entertainment Complex" in actions
    # Retainers needs a garrison; Nagoya has none, so it gains 0 here and sorts last
    assert actions[-1] == "Slot Retainers" and opts[-1].gain == 0
    # 3 needed, only +2 has known timing: the combination takes both and stops short
    assert [o.action for o in combo] == ["Improve Silk at (11,10)", "Build Entertainment Complex"]


def test_loyalty_options_for_nagoya(mentor):
    cv, needs, opts, combo = run(mentor.loyalty_options(131073))
    actions = [o.action for o in opts]
    assert "Assign a governor here" in actions
    assert "Buy Monument" in actions and "Build Monument" in actions
    assert any(a.startswith("Raise amenities to Content") for a in actions)
    gov = next(o for o in opts if o.action == "Assign a governor here")
    assert gov.confidence == "estimate" and gov.turns == 5


def test_city_lookup(mentor):
    assert run(mentor.resolve_city("kyo")).name == "Kyoto"
    with pytest.raises(CityNotFound):
        run(mentor.resolve_city("Osaka"))


def test_tile_filters(mentor):
    unimproved = run(mentor.tiles("empire", filter="unimproved_resources"))
    assert [(t.x, t.y) for t in unimproved] == [(11, 10)]  # niter is hidden by tech
    pillaged = run(mentor.tiles("revealed", filter="pillaged"))
    assert [(t.x, t.y) for t in pillaged] == [(13, 13)]
    with pytest.raises(ValueError):
        run(mentor.tiles("empire", filter="nonsense"))


def test_highlight_and_pins(mentor):
    n, pins, icon = run(mentor.highlight([(11, 10), (13, 13)], "green", "Silk", pin=False, look_at=True))
    assert n == 2 and pins == 0 and mentor.source.pins == []
    n, pins, icon = run(mentor.highlight([(11, 10)], "green", "Silk", pin=True, look_at=False))
    assert pins == 1 and mentor.source.pins == [(11, 10, "Silk", "")]


def test_highlight_with_district_icon(mentor):
    n, pins, icon = run(mentor.highlight([(7, 26)], "green", "", pin=False, look_at=True, icon="commercial hub"))
    assert (n, pins, icon) == (1, 1, "DISTRICT_COMMERCIAL_HUB")
    assert mentor.source.pins == [(7, 26, "Commercial Hub", "DISTRICT_COMMERCIAL_HUB")]
    _, _, icon = run(mentor.highlight([(1, 1)], "green", "", pin=False, look_at=False, icon="spaceship"))
    assert icon == "ICON_UNKNOWN"
    assert run(mentor.clear_highlights()) == 2 and mentor.source.pins == []


def test_camp_memory_survives_losing_sight(mentor):
    run(mentor.snapshot())
    mentor.source.data["snapshot"]["camps_seen"] = []
    snap = run(mentor.snapshot())
    assert [(c.x, c.y) for c in snap.camps] == [(16, 9)]
    mentor.source.data["snapshot"]["camps_gone"] = [[16, 9]]
    snap = run(mentor.snapshot())
    assert snap.camps == []


def test_game_review_records_history(mentor):
    run(mentor.turn_review())
    gr = run(mentor.game_review())
    assert gr["turns_recorded"] == 1 and gr["milestones"] == {"city_2": 85}


def test_rivals_turns_to_win_from_history(mentor):
    key = run(mentor.key())
    mentor.store.record_summary(key, 75, {"rivals": {"1": {"dvp": 10}}})
    snap, rows = run(mentor.rivals())
    korea = rows[0]
    assert korea["name"] == "Korea" and korea["military_ratio"] == 2.33
    # 5 DVP in 10 turns at T75→T85 needs ~10 turns for the remaining 5 — but T85's
    # own summary isn't recorded until a turn review, so the rate needs two points.
    assert "diplomatic" in korea["turns_to_win"]



def test_goal_pace_round_trips_and_migrates(tmp_path):
    import sqlite3
    from chancellor.store import Store
    db = tmp_path / "old.sqlite3"
    con = sqlite3.connect(db)  # a database from before the pace column existed
    con.execute("CREATE TABLE goals (game_key TEXT PRIMARY KEY, victory TEXT NOT NULL, style TEXT NOT NULL DEFAULT '', "
                "difficulty TEXT NOT NULL DEFAULT '', help_level TEXT NOT NULL DEFAULT 'advisor', set_turn INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO goals VALUES ('g', 'science', '', '', 'advisor', 1)")
    con.commit(); con.close()
    st = Store(db)
    assert st.get_goal("g").pace == "minimum"
    st.set_goal("g", Goal("science", pace="pro"))
    assert st.get_goal("g").pace == "pro"
    st.close()



def test_turn_review_shows_cities_and_units(mentor):
    from chancellor import narrate as nr
    rv, snap, goal = run(mentor.turn_review())
    text = nr.turn_review(rv, snap, goal)
    assert "Kyoto (pop 7, capital): building Library, 4 turn(s)" in text
    assert "Nagoya (pop 6): building NOTHING" in text and "loyalty 40 (-5.0)" in text
    # civilians in danger are listed first
    units = text.split("Units:")[1].strip().splitlines()
    assert units[0].startswith("Builder at (12,12)") and "Barbarian Horseman 2 tile(s) away!" in units[0]
    assert "Warrior at (10,10)" in text
