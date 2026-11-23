"""Drive the real MCP server over the protocol, against the fixture."""

import pytest
from conftest import HIDDEN_MARKERS, MIDGAME, run
from mcp.shared.memory import create_connected_server_and_client_session

from chancellor.fog import find_leaks


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHANCELLOR_FIXTURE", str(MIDGAME))
    monkeypatch.setenv("CHANCELLOR_DB", str(tmp_path / "server.sqlite3"))
    monkeypatch.delenv("CHANCELLOR_DEBUG_FULL_VISION", raising=False)


async def _calls(calls):
    from chancellor.server import mcp

    out = []
    async with create_connected_server_and_client_session(mcp._mcp_server) as client:
        for name, args in calls:
            res = await client.call_tool(name, args)
            out.append("".join(c.text for c in res.content if hasattr(c, "text")))
    return out


def test_every_tool_over_mcp_without_leaks(env):
    calls = [
        ("set_goal", {"victory": "diplomatic", "help_level": "advisor"}),
        ("get_turn_review", {}),
        ("explain_alert", {"alert_id": "loyalty:city=131073"}),
        ("get_amenity_options", {"city": "Nagoya"}),
        ("get_loyalty_options", {"city": "Nagoya"}),
        ("get_housing_options", {"city": "Nagoya"}),
        ("get_tile", {"x": 11, "y": 10}),
        ("get_tile", {"x": 20, "y": 20}),
        ("get_tiles", {"scope": "revealed"}),
        ("get_tiles", {"scope": "empire", "filter": "unimproved_resources"}),
        ("get_tiles", {"scope": "city", "city": "Nagoya"}),
        ("highlight_tiles", {"tiles": "11,10;13,13"}),
        ("clear_highlights", {}),
        ("find_park_sites", {}),
        ("get_goal_status", {}),
        ("add_commitment", {"text": "Settle a third city", "due_turn": 95, "check": "city_count:3"}),
        ("list_commitments", {}),
        ("get_rivals", {}),
        ("dismiss_alert", {"alert_id": "idle_gold:treasury"}),
        ("get_game_review", {}),
    ]
    outs = run(_calls(calls))
    by = dict(zip([f"{n}{i}" for i, (n, _) in enumerate(calls)], outs))
    text = "\n".join(outs)

    assert find_leaks(text, HIDDEN_MARKERS) == []
    assert "Top 3 of" in by["get_turn_review1"]
    assert "Loyalty 40/100" in by["explain_alert2"]
    assert "Improve Silk at (11,10)" in by["get_amenity_options3"]
    assert "Fastest combination" in by["get_amenity_options3"]
    assert "Assign a governor here" in by["get_loyalty_options4"]
    assert "hasn't been revealed" in by["get_tile7"]
    assert "Highlighted 2" in by["highlight_tiles11"]
    assert "(11,10) appeal 4" in by["find_park_sites13"]
    assert "Commitment #1 added: due T95, auto-checked (city_count 3)" in by["add_commitment15"]
    assert "Korea" in by["get_rivals17"] and "friendship available" in by["get_rivals17"]
    assert "Snoozed idle_gold:treasury until T95" in by["dismiss_alert18"]


def test_bad_inputs_return_messages_not_errors(env):
    outs = run(
        _calls(
            [
                ("get_amenity_options", {"city": "Atlantis"}),
                ("set_goal", {"victory": "vibes"}),
                ("add_commitment", {"text": "x", "due_turn": 1}),
                ("get_tiles", {"scope": "galaxy"}),
            ]
        )
    )
    assert "No city matching 'Atlantis'" in outs[0]
    assert "victory must be one of" in outs[1]
    assert "due_turn must be after" in outs[2]
    assert "scope must be one of" in outs[3]
