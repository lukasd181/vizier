"""SQLite cache: goals, commitments, alert history, turn summaries, memory.

One database for all games, keyed by (civ, seed) so a new game never inherits
another game's commitments. Default path ~/.vizier/vizier.sqlite3,
override with VIZIER_DB.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from vizier.models import Alert, Commitment, Goal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    game_key TEXT PRIMARY KEY,
    victory TEXT NOT NULL,
    style TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT '',
    help_level TEXT NOT NULL DEFAULT 'advisor',
    set_turn INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_key TEXT NOT NULL,
    text TEXT NOT NULL,
    created_turn INTEGER NOT NULL,
    due_turn INTEGER NOT NULL,
    check_kind TEXT NOT NULL DEFAULT 'manual',
    check_arg TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    done_turn INTEGER
);
CREATE TABLE IF NOT EXISTS alerts (
    game_key TEXT NOT NULL,
    turn INTEGER NOT NULL,
    alert_id TEXT NOT NULL,
    rule TEXT NOT NULL,
    severity INTEGER NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    data_json TEXT NOT NULL,
    shown INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_key, turn, alert_id)
);
CREATE TABLE IF NOT EXISTS dismissals (
    game_key TEXT NOT NULL,
    alert_id TEXT NOT NULL,
    rule TEXT NOT NULL,
    turn INTEGER NOT NULL,
    until_turn INTEGER NOT NULL,
    PRIMARY KEY (game_key, alert_id, turn)
);
CREATE TABLE IF NOT EXISTS turn_summaries (
    game_key TEXT NOT NULL,
    turn INTEGER NOT NULL,
    summary_json TEXT NOT NULL,
    PRIMARY KEY (game_key, turn)
);
CREATE TABLE IF NOT EXISTS camps (
    game_key TEXT NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    distance INTEGER NOT NULL,
    first_seen_turn INTEGER NOT NULL,
    last_seen_turn INTEGER NOT NULL,
    PRIMARY KEY (game_key, x, y)
);
"""


def default_db_path() -> Path:
    if "VIZIER_DB" in os.environ:
        return Path(os.environ["VIZIER_DB"])
    path = Path.home() / ".vizier" / "vizier.sqlite3"
    # The project was called "the-chancellor" before; carry its data over once.
    legacy = Path.home() / ".chancellor" / "chancellor.sqlite3"
    if not path.exists() and legacy.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, path)
    return path


def game_key(civ: str, seed: int) -> str:
    return f"{civ}:{seed}"


class Store:
    def __init__(self, path: str | Path | None = None):
        path = Path(path) if path is not None else default_db_path()
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(goals)")}
        if "pace" not in cols:
            self.db.execute("ALTER TABLE goals ADD COLUMN pace TEXT NOT NULL DEFAULT 'minimum'")

    def close(self) -> None:
        self.db.close()

    # -- goals -------------------------------------------------------------

    def set_goal(self, key: str, goal: Goal) -> None:
        self.db.execute(
            "INSERT INTO goals (game_key, victory, style, difficulty, help_level, set_turn, pace) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(game_key) DO UPDATE SET "
            "victory=excluded.victory, style=excluded.style, difficulty=excluded.difficulty, "
            "help_level=excluded.help_level, set_turn=excluded.set_turn, pace=excluded.pace",
            (key, goal.victory, goal.style, goal.difficulty, goal.help_level, goal.set_turn, goal.pace),
        )
        self.db.commit()

    def get_goal(self, key: str) -> Goal | None:
        row = self.db.execute("SELECT * FROM goals WHERE game_key = ?", (key,)).fetchone()
        if row is None:
            return None
        return Goal(
            victory=row["victory"],
            style=row["style"],
            difficulty=row["difficulty"],
            help_level=row["help_level"],
            set_turn=row["set_turn"],
            pace=row["pace"],
        )

    # -- commitments -------------------------------------------------------

    def add_commitment(
        self, key: str, text: str, created_turn: int, due_turn: int, check_kind: str, check_arg: str
    ) -> Commitment:
        cur = self.db.execute(
            "INSERT INTO commitments (game_key, text, created_turn, due_turn, check_kind, check_arg) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (key, text, created_turn, due_turn, check_kind, check_arg),
        )
        self.db.commit()
        return Commitment(
            id=cur.lastrowid or 0,
            text=text,
            created_turn=created_turn,
            due_turn=due_turn,
            check_kind=check_kind,
            check_arg=check_arg,
        )

    def list_commitments(self, key: str, include_closed: bool = True) -> list[Commitment]:
        q = "SELECT * FROM commitments WHERE game_key = ?"
        if not include_closed:
            q += " AND status IN ('open', 'overdue')"
        rows = self.db.execute(q + " ORDER BY due_turn, id", (key,)).fetchall()
        return [
            Commitment(
                id=r["id"],
                text=r["text"],
                created_turn=r["created_turn"],
                due_turn=r["due_turn"],
                check_kind=r["check_kind"],
                check_arg=r["check_arg"],
                status=r["status"],
                done_turn=r["done_turn"],
            )
            for r in rows
        ]

    def update_commitment(self, key: str, cid: int, status: str, done_turn: int | None) -> bool:
        cur = self.db.execute(
            "UPDATE commitments SET status = ?, done_turn = ? WHERE game_key = ? AND id = ?",
            (status, done_turn, key, cid),
        )
        self.db.commit()
        return cur.rowcount > 0

    # -- alerts ------------------------------------------------------------

    def record_alerts(self, key: str, turn: int, alerts: list[Alert], shown_ids: set[str]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO alerts (game_key, turn, alert_id, rule, severity, title, detail, data_json, shown) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    key,
                    turn,
                    a.id,
                    a.rule,
                    a.severity,
                    a.title,
                    a.detail,
                    json.dumps(a.data, default=str),
                    1 if a.id in shown_ids else 0,
                )
                for a in alerts
            ],
        )
        self.db.commit()

    def get_alert(self, key: str, alert_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM alerts WHERE game_key = ? AND alert_id = ? ORDER BY turn DESC LIMIT 1",
            (key, alert_id),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["data"] = json.loads(d.pop("data_json"))
        d["history"] = [
            r["turn"]
            for r in self.db.execute(
                "SELECT turn FROM alerts WHERE game_key = ? AND alert_id = ? ORDER BY turn",
                (key, alert_id),
            )
        ]
        return d

    def alert_history(self, key: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT turn, alert_id, rule, severity, title, shown FROM alerts "
                "WHERE game_key = ? ORDER BY turn, severity",
                (key,),
            )
        ]

    def dismiss(self, key: str, alert_id: str, turn: int, snooze_turns: int) -> None:
        rule = alert_id.split(":", 1)[0]
        self.db.execute(
            "INSERT OR REPLACE INTO dismissals (game_key, alert_id, rule, turn, until_turn) VALUES (?, ?, ?, ?, ?)",
            (key, alert_id, rule, turn, turn + snooze_turns),
        )
        self.db.commit()

    def snoozed_ids(self, key: str, turn: int) -> set[str]:
        return {
            r["alert_id"]
            for r in self.db.execute(
                "SELECT alert_id FROM dismissals WHERE game_key = ? AND until_turn >= ?", (key, turn)
            )
        }

    def dismiss_counts(self, key: str) -> dict[str, int]:
        return {
            r["rule"]: r["n"]
            for r in self.db.execute(
                "SELECT rule, COUNT(*) AS n FROM dismissals WHERE game_key = ? GROUP BY rule", (key,)
            )
        }

    def shown_counts(self, key: str) -> dict[str, int]:
        return {
            r["rule"]: r["n"]
            for r in self.db.execute(
                "SELECT rule, COUNT(*) AS n FROM alerts WHERE game_key = ? AND shown = 1 GROUP BY rule",
                (key,),
            )
        }

    # -- turn summaries ----------------------------------------------------

    def record_summary(self, key: str, turn: int, summary: dict[str, Any]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO turn_summaries (game_key, turn, summary_json) VALUES (?, ?, ?)",
            (key, turn, json.dumps(summary, default=str)),
        )
        self.db.commit()

    def summaries(self, key: str, since_turn: int = 0) -> list[tuple[int, dict[str, Any]]]:
        return [
            (r["turn"], json.loads(r["summary_json"]))
            for r in self.db.execute(
                "SELECT turn, summary_json FROM turn_summaries WHERE game_key = ? AND turn >= ? ORDER BY turn",
                (key, since_turn),
            )
        ]

    # -- remembered camps (fog memory) --------------------------------------

    def update_camps(
        self, key: str, turn: int, seen: list[tuple[int, int, int]], gone: list[tuple[int, int]]
    ) -> None:
        for x, y, dist in seen:
            self.db.execute(
                "INSERT INTO camps (game_key, x, y, distance, first_seen_turn, last_seen_turn) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(game_key, x, y) DO UPDATE SET "
                "distance=excluded.distance, last_seen_turn=excluded.last_seen_turn",
                (key, x, y, dist, turn, turn),
            )
        for x, y in gone:
            self.db.execute("DELETE FROM camps WHERE game_key = ? AND x = ? AND y = ?", (key, x, y))
        self.db.commit()

    def camps(self, key: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM camps WHERE game_key = ?", (key,))]
