# the-chancellor

**Vizier**, a standalone Civ 6 mentor for human players, as an MCP server.

Vizier talks to a running Civ 6 over the game's own debug port (FireTuner) to
*coach a person*. It catches the threats the game UI hides, prices every fix
with exact numbers, and tracks your plans. It sees only what you could see,
never changes the game, and shows at most 3 alerts a turn.

It implements the MVP and the v2 quick wins from *Civ 6 Mentor MCP:
High-Value Asks & Features*: the turn watcher, fix-it options, goal status,
the in-game alert panel, prompt shortcuts, commitments and tile highlights.

## How it works

```
Claude ──MCP──▶ server.py ──▶ Mentor ──▶ StateSource ──tuner.py──▶ Civ 6 (port 4318)
                                │           (TunerSource | FixtureSource)
                                ├─ fog.FogFilter   one visibility filter for everything
                                ├─ rules/          deterministic checks, ranked, capped at 3
                                ├─ options.py      fix-it options: gain · turns · cost
                                ├─ goals.py        benchmarks, viability, commitments
                                └─ store.py        SQLite: goals, plans, alert history, camp memory
```

- **Code detects and computes; Claude prioritises and explains.** Every rule
  is a plain function over an `EmpireSnapshot` and runs every turn.
- **Standalone.** The only dependency is the `mcp` package. `tuner.py` speaks
  the FireTuner protocol and `sources/lua_queries.py` holds every game query.
  Both started from [civ6-mcp](https://github.com/lmwilki/civ6-mcp) (MIT; see
  `NOTICE`), which isn't needed at runtime.
- **Game rules come from the shipped game.** Amenity thresholds, entertainment
  buildings and policy amounts were read from the game's compiled database
  with REA. See [docs/game-data-evidence.md](docs/game-data-evidence.md).

## Tools

| Area | Tools |
|---|---|
| Alerts | `get_turn_review`, `explain_alert`, `dismiss_alert` |
| Fix-it options | `get_amenity_options`, `get_loyalty_options`, `get_housing_options` |
| Map | `get_tile`, `get_tiles`, `highlight_tiles`, `clear_highlights`, `find_park_sites` |
| Planning | `set_goal`, `get_goal_status`, `add_commitment`, `list_commitments`, `update_commitment`, `get_rivals` |
| Coaching | `get_game_review`; prompts `/turn-check`, `/plan-victory`, `/war-check`, `/post-game-review` |

The turn watcher runs 28 rules:
- rival victory (science, religion, diplomatic and culture, from met civs only, with turns-to-win)
- loyalty, amenities, housing, empty queues
- idle gold and faith, free trade route slots
- exploration and city-count benchmarks, late districts
- civilians near visible enemies, remembered barbarian camps, military balance
- friendships, alliances and delegations left on the table
- overdue plans, victory-path viability
- era score (dark/golden age), amenity thresholds, spare luxuries, settling without amenities
- eureka guard, district cost lock-in, Serfdom/God King swaps, unused governor titles
- data-sanity checks (frozen favor, ghost trade routes)

## Guardrails

| Spec guardrail | Where |
|---|---|
| Fog of war: one filter, and a test that fails on any leak | `fog.py`, the source-side checks in `lua_queries.py`, and `tests/test_fog.py`, `test_server.py`, `test_lua_queries.py` (hidden markers planted in raw data) |
| No autoplay; approval before actions | No tool changes game state. Highlights are display-only; pins (saved in the game file) need `pin=True` |
| Alert fatigue | Max 3, ranked; `dismiss_alert` snoozes; rules dismissed ≥5 times at ≥80% are retired (never critical ones) |
| FireTuner stays local | `TunerSource` refuses any non-localhost host |
| Debug full vision | `CHANCELLOR_DEBUG_FULL_VISION=1`, off by default; every output gets a warning banner |
| Help levels | `set_goal(help_level=off/watchdog/advisor/coach)` |
| Rank by root cause | Early game: exploration → expansion → the rest; later: by category |
| Sanity-check the data | `rules/sanity.py` flags suspect values and silences the rules that depend on them |

Revealed tiles you can't currently see show only terrain and resources.
Improvements, owners and districts can change after you last looked, and the
tuner would report the current truth. Barbarian camps are remembered from when
you last saw them.

## Setup

1. **Civ 6:** set `EnableTuner 1` in
   `~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid Meier's Civilization VI/AppOptions.txt`
   and restart. Achievements are disabled while the tuner is on.
2. **Install** (Python 3.12+):
   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install -e .
   ```
   With uv: `uv sync`.
3. **Connect:** `.mcp.json` registers the `chancellor` server for Claude Code.
   Approve it when a new session asks (or `/mcp`). Then use the project skills
   `/turn-check`, `/plan-victory`, `/war-check` and `/post-game-review`, or just
   ask in plain words. Without an MCP client, call any tool from the shell:
   `.venv/bin/python -m chancellor.cli get_turn_review` (`--list` for all,
   `--fixture tests/fixtures/midgame.json` for the demo game).
   The game allows only one tuner connection, so run Vizier in one app at a
   time, and close FireTuner or any other tuner client first.
4. **Optional in-game panel:** copy `mod/ChancellorAlerts` into
   `~/Library/Application Support/Sid Meier's Civilization VI/Mods/` and enable
   *Vizier Alerts* under Additional Content.

No game handy? `CHANCELLOR_FIXTURE=tests/fixtures/midgame.json .venv/bin/python -m chancellor`
runs the server against a recorded mid-game.

## Tests

```bash
.venv/bin/pip install pytest lupa
.venv/bin/python -m pytest
```

96 tests. `test_tuner.py` drives the FireTuner client against a fake game
speaking the real wire protocol. `test_lua_queries.py` runs the real Lua queries against a fake Civ 6
API (`tests/fake_civ6.lua`) in an embedded Lua runtime. That proves they run,
parse and drop hidden data, but only a live game can prove the engine accepts
every call.

## Not built yet

- v2 big bets: `rank_district_sites` / `rank_district_pairs`, `rank_settle_spots`,
  `rank_production`, `rank_purchases`, `rank_trade_routes`, `compare_policies`
- v3: `propose_batch` / `apply_batch` (approval-gated actions), `get_player_trends`
- A logs-and-autosave `StateSource` for players who keep achievements
- Replaying CivBench logs through the rules (Next steps #1): that needs the
  dataset, plus a "what could the player see" filter over its omniscient rival fields
