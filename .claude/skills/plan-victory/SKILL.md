---
name: plan-victory
description: Vizier victory planning for the player's live Civ 6 game — whether their victory path is still winnable, how far ahead or behind benchmarks they are, and the next 10-20 turns of priorities saved as tracked commitments. Use when the player asks "am I on track", wants to plan a victory, or invokes /plan-victory.
---

# Plan victory

Get goal status and rivals. Tell the player whether the path is viable, how far
ahead or behind the benchmarks they are, and the 3 most important things for
the next 10-20 turns. Offer to save each as a commitment. If no goal is set,
ask which victory they're going for and save it with `set_goal` first. Don't
spoil surprises: no full-game plans.

## Getting the data

Prefer the MCP tools `mcp__chancellor__get_goal_status`, `mcp__chancellor__get_rivals`,
`mcp__chancellor__set_goal`, `mcp__chancellor__add_commitment`. Otherwise use the CLI
from the repository root:

```bash
.venv/bin/python -m chancellor.cli get_goal_status 2>/dev/null
.venv/bin/python -m chancellor.cli get_rivals 2>/dev/null
.venv/bin/python -m chancellor.cli set_goal '{"victory": "science", "help_level": "advisor"}' 2>/dev/null
.venv/bin/python -m chancellor.cli add_commitment '{"text": "Third city", "due_turn": 60, "check": "city_count:3"}' 2>/dev/null
```

If the output says "Can't reach the game", explain the setup (Civ 6 running,
`EnableTuner 1`, nothing else on the tuner) and offer the demo with
`--fixture tests/fixtures/midgame.json`, labelled as demo.
