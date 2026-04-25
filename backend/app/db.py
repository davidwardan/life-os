from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.app.config import DEFAULT_DB_PATH
from backend.app.schemas import MessageIn, ParsedDailyLog


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT NOT NULL,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nutrition_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    meal_name TEXT NOT NULL,
    calories REAL,
    protein_g REAL,
    confidence REAL NOT NULL,
    estimated INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS workout_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    workout_type TEXT,
    duration_min REAL,
    intensity INTEGER,
    notes TEXT,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS wellbeing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    mood INTEGER,
    energy INTEGER,
    stress INTEGER,
    sleep_hours REAL,
    sleep_quality INTEGER,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS career_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    project TEXT,
    activity TEXT,
    duration_hours REAL,
    progress_note TEXT,
    blockers TEXT,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    text TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    sentiment REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(raw_message_id) REFERENCES raw_messages(id)
);
"""


class LifeDatabase:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def save_message(self, message: MessageIn, parsed: ParsedDailyLog) -> dict[str, Any]:
        now = _now()
        with self.connect() as connection:
            raw_id = connection.execute(
                """
                INSERT INTO raw_messages (entry_date, source, text, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (parsed.entry_date.isoformat(), message.source, message.text, now),
            ).lastrowid

            records = {
                "nutrition": [],
                "workout": [],
                "wellbeing": [],
                "career": [],
                "journal": [],
            }

            for item in parsed.nutrition:
                row_id = connection.execute(
                    """
                    INSERT INTO nutrition_logs
                    (raw_message_id, entry_date, meal_name, calories, protein_g, confidence, estimated, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_id,
                        parsed.entry_date.isoformat(),
                        item.meal_name,
                        item.calories,
                        item.protein_g,
                        item.confidence,
                        int(item.estimated),
                        now,
                    ),
                ).lastrowid
                records["nutrition"].append({"id": row_id, **item.model_dump()})

            if parsed.workout:
                item = parsed.workout
                row_id = connection.execute(
                    """
                    INSERT INTO workout_logs
                    (raw_message_id, entry_date, workout_type, duration_min, intensity, notes, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_id,
                        parsed.entry_date.isoformat(),
                        item.workout_type,
                        item.duration_min,
                        item.intensity,
                        item.notes,
                        item.confidence,
                        now,
                    ),
                ).lastrowid
                records["workout"].append({"id": row_id, **item.model_dump()})

            if parsed.wellbeing:
                item = parsed.wellbeing
                row_id = connection.execute(
                    """
                    INSERT INTO wellbeing_logs
                    (raw_message_id, entry_date, mood, energy, stress, sleep_hours, sleep_quality, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_id,
                        parsed.entry_date.isoformat(),
                        item.mood,
                        item.energy,
                        item.stress,
                        item.sleep_hours,
                        item.sleep_quality,
                        item.confidence,
                        now,
                    ),
                ).lastrowid
                records["wellbeing"].append({"id": row_id, **item.model_dump()})

            for item in parsed.career:
                row_id = connection.execute(
                    """
                    INSERT INTO career_logs
                    (raw_message_id, entry_date, project, activity, duration_hours, progress_note, blockers, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_id,
                        parsed.entry_date.isoformat(),
                        item.project,
                        item.activity,
                        item.duration_hours,
                        item.progress_note,
                        item.blockers,
                        item.confidence,
                        now,
                    ),
                ).lastrowid
                records["career"].append({"id": row_id, **item.model_dump()})

            if parsed.journal_text:
                row_id = connection.execute(
                    """
                    INSERT INTO journal_entries
                    (raw_message_id, entry_date, text, tags_json, sentiment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (raw_id, parsed.entry_date.isoformat(), parsed.journal_text, json.dumps([]), None, now),
                ).lastrowid
                records["journal"].append({"id": row_id, "text": parsed.journal_text})

        return {"raw_message_id": raw_id, "records": records}

    def recent_logs(self, limit: int = 25) -> dict[str, list[dict[str, Any]]]:
        with self.connect() as connection:
            return {
                "raw_messages": _rows(
                    connection,
                    "SELECT * FROM raw_messages ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ),
                "nutrition": _rows(
                    connection,
                    "SELECT * FROM nutrition_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ),
                "workout": _rows(
                    connection,
                    "SELECT * FROM workout_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ),
                "wellbeing": _rows(
                    connection,
                    "SELECT * FROM wellbeing_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ),
                "career": _rows(
                    connection,
                    "SELECT * FROM career_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ),
                "journal": _rows(
                    connection,
                    "SELECT * FROM journal_entries ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ),
            }


def _rows(connection: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

