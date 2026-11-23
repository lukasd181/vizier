---
name: turn-check
description: Vizier start-of-turn digest for the player's live Civ 6 game — the top alerts this turn (rival victories, cities about to flip, unhappiness, idle gold, falling behind benchmarks) with 2-3 options each. Use when the player asks what to do this turn or invokes /turn-check.
---

# Turn check

Get the turn review, then give the player at most three short bullets: what
deserves attention this turn and why, given their goal. For each, offer 2-3
options with trade-offs and let them pick. Don't list things that are fine.
Only call an options tool (get_amenity_options, get_loyalty_options, …) if the
player asks, or if the critical alert is unclear without it.

## Getting the data

Prefer the MCP tool `mcp__chancellor__get_turn_review` if it's available.
Otherwise run the same tool through the CLI from the repository root:

```bash
.venv/bin/python -m chancellor.cli get_turn_review 2>/dev/null
```

Any other Vizier tool works the same way, e.g.
`.venv/bin/python -m chancellor.cli get_loyalty_options '{"city": "Nagoya"}'`
(`--list` shows them all).

If the output says "Can't reach the game", tell the player what's missing
(Civ 6 running with a game loaded, `EnableTuner 1` in AppOptions.txt, nothing
else holding the tuner connection) and offer the demo game:
`.venv/bin/python -m chancellor.cli --fixture tests/fixtures/midgame.json get_turn_review`.
Label demo results as demo, never as the player's game.

## Principles

Options, not orders. Hint before answering. Respect the player's goal, even a
roleplay or wonder game. Never mention anything the player couldn't see.
