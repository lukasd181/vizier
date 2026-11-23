# Changelog

All notable changes to Vizier. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-11-22

The first release: the MVP and v2 quick wins from *Civ 6 Mentor MCP:
High-Value Asks & Features*.

### Added
- **Turn watcher:** `get_turn_review` runs 28 deterministic rules every turn,
  ranks them by severity (and by root cause early in the game), and shows at
  most 3. Each review also lists cities, units, research, civics and era score.
  `explain_alert` shows the data behind an alert; `dismiss_alert` snoozes it,
  and rules you keep dismissing retire.
- **Rules:** rival victory with turns-to-win; loyalty, amenities, housing and
  idle production; idle gold and faith; unused trade routes; exploration and
  expansion benchmarks (CivBench minimum or a pro pace); late districts;
  civilians at risk; barbarian camps; military balance; passive diplomacy;
  overdue plans; victory-path viability; era score; amenity thresholds; spare
  luxuries; settling without amenities; eureka guard; district cost lock-in;
  Serfdom and God King swaps; unused governor titles; data-sanity checks.
- **Fix-it options:** `get_amenity_options`, `get_loyalty_options` and
  `get_housing_options` list every fix with gain, turns and cost, plus the
  fastest combination.
- **Map:** `get_tile`, `get_tiles` (fog-filtered), `highlight_tiles` with
  map tacks showing the game's own district, improvement, building and unit
  icons, `clear_highlights`, `find_park_sites` (the engine's own park rule)
  and `rank_settle_spots` (legal sites scored by yields, water, luxuries and
  Campus adjacency, with the game's settler-advisor picks flagged).
- **Planning:** goals with help levels and pace, auto-checked commitments,
  `get_rivals`, and `get_game_review` for post-game analysis.
- **Prompts and skills:** `turn-check`, `plan-victory`, `war-check`,
  `post-game-review`, as MCP prompts and Claude Code skills.
- **Fog of war, enforced twice:** filtered in the Lua at the source and again
  in Python, with leak tests on planted hidden data.
- **Single-player guard:** every query first checks whether the game is
  multiplayer (online, LAN, hotseat or PlayByCloud) and, if so, reads and
  changes nothing.
- **Standalone FireTuner client** (`tuner.py`, adapted from civ6-mcp, MIT).
- **Live rule tables:** amenity, housing and luxury values are read from the
  running game's rule set. `gamedata.py` holds REA-verified fallbacks
  (evidence in `docs/game-data-evidence.md`).
- **`vizier setup`:** turns on the tuner, installs the in-game panel mod and
  registers Claude Desktop. Asks before each change and backs up edited files.
- **`vizier doctor`:** read-only checks of Python, the tuner setting, the mod,
  the game connection, the tuner port's exposure, the Claude Desktop entry and
  the database.
- **Paths for macOS, Windows and Linux**, overridable with `VIZIER_APPOPTIONS`
  and `VIZIER_MODS_DIR`.
- **VizierAlerts mod:** an optional in-game panel showing the top 3 alerts.
- **Memory** in SQLite at `~/.vizier/vizier.sqlite3`. Data from the
  pre-rename `~/.chancellor/` location is carried over automatically.
- **CI:** tests on macOS, Windows and Linux with Python 3.12 and 3.13.

### Known limitations
- Verified live on macOS only; Windows and Linux are untested on real
  machines.
- Needs the FireTuner debug port, which disables achievements.
- Tile output doesn't report rivers yet.

[0.1.0]: https://github.com/lukasd181/the-chancellor/releases/tag/v0.1.0
