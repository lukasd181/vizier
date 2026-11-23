---
name: war-check
description: Vizier military check for the player's live Civ 6 game — "am I safe from Korea?", "should I attack now?" — comparing visible military strength, threats near borders and civilians at risk, with defend/deter/attack options. Use when the player asks about war or safety, or invokes /war-check.
---

# War check

Compare visible strength with the rivals the player has met, note threats near
their cities and civilians at risk, and give 2-3 options — defend, deter, or
attack — with the risks of each. Use only visible information.

## Getting the data

Prefer `mcp__chancellor__get_rivals`, `mcp__chancellor__get_turn_review` and
`mcp__chancellor__get_tiles` (scope "area" around a border city). Otherwise use
the CLI from the repository root:

```bash
.venv/bin/python -m chancellor.cli get_rivals 2>/dev/null
.venv/bin/python -m chancellor.cli get_turn_review '{"push_to_game": false}' 2>/dev/null
.venv/bin/python -m chancellor.cli get_tiles '{"scope": "area", "x": 10, "y": 10, "radius": 4}' 2>/dev/null
```

If the output says "Can't reach the game", explain the setup and offer the demo
with `--fixture tests/fixtures/midgame.json`, labelled as demo.
