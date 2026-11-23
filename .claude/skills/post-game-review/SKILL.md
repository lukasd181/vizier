---
name: post-game-review
description: Vizier post-game review of a Civ 6 game — the turning points, warnings that fired and weren't acted on, where the player fell behind benchmarks, and one thing to practise next game. Use when the player asks why they won or lost, or invokes /post-game-review.
---

# Post-game review

Get the game review and find the story: the 2-3 turning points, warnings that
fired and weren't acted on, and where the player fell behind the benchmarks.
End with one focused thing to practise next game. The review is built from
turn reviews recorded during the game, so it's thin if few were run.

## Getting the data

Prefer `mcp__chancellor__get_game_review`. Otherwise, from the repository root:

```bash
.venv/bin/python -m chancellor.cli get_game_review 2>/dev/null
```
