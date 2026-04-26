from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.app.config import DEFAULT_DB_PATH
from backend.app.config import settings
from backend.app.schemas import MessageIn, ParsedDailyLog


SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT,
    source TEXT NOT NULL,
    text TEXT,
    created_at TEXT,
    received_at TEXT,
    user_text TEXT,
    processed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    entry_date TEXT,
    sleep_hours REAL,
    sleep_quality INTEGER,
    energy INTEGER,
    stress INTEGER,
    mood INTEGER,
    notes TEXT,
    confidence REAL,
    source_message_id INTEGER,
    raw_message_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS nutrition_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER,
    source_message_id INTEGER,
    date TEXT,
    entry_date TEXT,
    meal_type TEXT,
    meal_name TEXT,
    description TEXT,
    calories REAL,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    confidence REAL,
    estimated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS workout_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER,
    source_message_id INTEGER,
    date TEXT,
    entry_date TEXT,
    workout_type TEXT,
    duration_min REAL,
    intensity INTEGER,
    notes TEXT,
    confidence REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS workout_exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    sets INTEGER,
    reps INTEGER,
    load TEXT,
    duration_min REAL,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workout_id) REFERENCES workout_logs(id)
);

CREATE TABLE IF NOT EXISTS wellbeing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER,
    entry_date TEXT,
    mood INTEGER,
    energy INTEGER,
    stress INTEGER,
    sleep_hours REAL,
    sleep_quality INTEGER,
    confidence REAL,
    created_at TEXT NOT NULL,
    source_message_id INTEGER,
    date TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS career_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER,
    source_message_id INTEGER,
    date TEXT,
    entry_date TEXT,
    project TEXT,
    activity TEXT,
    duration_hours REAL,
    progress_note TEXT,
    blockers TEXT,
    confidence REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_message_id INTEGER,
    source_message_id INTEGER,
    date TEXT,
    entry_date TEXT,
    text TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    sentiment REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_message_id) REFERENCES raw_messages(id)
);

CREATE TABLE IF NOT EXISTS memory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    subject TEXT NOT NULL,
    value TEXT NOT NULL,
    evidence TEXT,
    source_message_id INTEGER,
    confidence REAL NOT NULL DEFAULT 0.7,
    importance INTEGER NOT NULL DEFAULT 3,
    times_seen INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    FOREIGN KEY(source_message_id) REFERENCES raw_messages(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_items_unique
ON memory_items(category, subject, value);

CREATE INDEX IF NOT EXISTS idx_memory_items_active_category
ON memory_items(active, category);
"""


MIGRATIONS: dict[str, dict[str, str]] = {
    "raw_messages": {
        "entry_date": "TEXT",
        "text": "TEXT",
        "created_at": "TEXT",
        "received_at": "TEXT",
        "user_text": "TEXT",
        "processed": "INTEGER NOT NULL DEFAULT 0",
    },
    "nutrition_logs": {
        "raw_message_id": "INTEGER",
        "source_message_id": "INTEGER",
        "date": "TEXT",
        "entry_date": "TEXT",
        "meal_type": "TEXT",
        "meal_name": "TEXT",
        "description": "TEXT",
        "carbs_g": "REAL",
        "fat_g": "REAL",
    },
    "workout_logs": {
        "raw_message_id": "INTEGER",
        "source_message_id": "INTEGER",
        "date": "TEXT",
        "entry_date": "TEXT",
        "confidence": "REAL",
    },
    "wellbeing_logs": {
        "source_message_id": "INTEGER",
        "date": "TEXT",
        "notes": "TEXT",
    },
    "career_logs": {
        "raw_message_id": "INTEGER",
        "source_message_id": "INTEGER",
        "date": "TEXT",
        "entry_date": "TEXT",
        "confidence": "REAL",
    },
    "journal_entries": {
        "raw_message_id": "INTEGER",
        "source_message_id": "INTEGER",
        "date": "TEXT",
        "entry_date": "TEXT",
    },
    "memory_items": {
        "category": "TEXT",
        "subject": "TEXT",
        "value": "TEXT",
        "evidence": "TEXT",
        "source_message_id": "INTEGER",
        "confidence": "REAL NOT NULL DEFAULT 0.7",
        "importance": "INTEGER NOT NULL DEFAULT 3",
        "times_seen": "INTEGER NOT NULL DEFAULT 1",
        "active": "INTEGER NOT NULL DEFAULT 1",
        "created_at": "TEXT",
        "updated_at": "TEXT",
        "last_seen_at": "TEXT",
    },
}


class LifeDatabase:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self.path = settings.turso_replica_path if _use_turso() else path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        connection = _connect(self.path)
        if hasattr(connection, "row_factory"):
            connection.row_factory = sqlite3.Row
        try:
            if hasattr(connection, "sync"):
                connection.sync()
            yield connection
            connection.commit()
            if hasattr(connection, "sync"):
                connection.sync()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            _run_migrations(connection)

    def save_message(self, message: MessageIn, parsed: ParsedDailyLog) -> dict[str, Any]:
        now = _now()
        log_date = parsed.date.isoformat()
        with self.connect() as connection:
            raw_id = connection.execute(
                """
                INSERT INTO raw_messages
                (entry_date, source, text, created_at, received_at, user_text, processed)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (log_date, message.source, message.text, now, now, message.text),
            ).lastrowid

            records: dict[str, list[dict[str, Any]]] = {
                "daily_checkins": [],
                "nutrition": [],
                "workout": [],
                "workout_exercises": [],
                "career": [],
                "journal": [],
            }

            if parsed.wellbeing and _has_wellbeing_signal(parsed.wellbeing):
                item = parsed.wellbeing
                row_id = connection.execute(
                    """
                    INSERT INTO daily_checkins
                    (date, entry_date, sleep_hours, sleep_quality, energy, stress, mood, notes,
                     confidence, source_message_id, raw_message_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        log_date,
                        log_date,
                        item.sleep_hours,
                        item.sleep_quality,
                        item.energy,
                        item.stress,
                        item.mood,
                        item.notes,
                        item.confidence,
                        raw_id,
                        raw_id,
                        now,
                    ),
                ).lastrowid
                records["daily_checkins"].append({"id": row_id, **item.model_dump()})

            for item in parsed.nutrition:
                row_id = connection.execute(
                    """
                    INSERT INTO nutrition_logs
                    (raw_message_id, source_message_id, date, entry_date, meal_type, meal_name,
                     description, calories, protein_g, carbs_g, fat_g, confidence, estimated, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_id,
                        raw_id,
                        log_date,
                        log_date,
                        item.meal_type,
                        item.description,
                        item.description,
                        item.calories,
                        item.protein_g,
                        item.carbs_g,
                        item.fat_g,
                        item.confidence,
                        int(item.estimated),
                        now,
                    ),
                ).lastrowid
                records["nutrition"].append({"id": row_id, **item.model_dump()})

            if parsed.workout:
                item = parsed.workout
                workout_id = connection.execute(
                    """
                    INSERT INTO workout_logs
                    (raw_message_id, source_message_id, date, entry_date, workout_type, duration_min,
                     intensity, notes, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_id,
                        raw_id,
                        log_date,
                        log_date,
                        item.workout_type,
                        item.duration_min,
                        item.intensity,
                        item.notes,
                        item.confidence,
                        now,
                    ),
                ).lastrowid
                records["workout"].append({"id": workout_id, **item.model_dump()})

                for exercise in item.exercises:
                    exercise_id = connection.execute(
                        """
                        INSERT INTO workout_exercises
                        (workout_id, name, sets, reps, load, duration_min, notes, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            workout_id,
                            exercise.name,
                            exercise.sets,
                            exercise.reps,
                            exercise.load,
                            exercise.duration_min,
                            exercise.notes,
                            now,
                        ),
                    ).lastrowid
                    records["workout_exercises"].append({"id": exercise_id, **exercise.model_dump()})

            for item in parsed.career:
                row_id = connection.execute(
                    """
                    INSERT INTO career_logs
                    (raw_message_id, source_message_id, date, entry_date, project, activity,
                     duration_hours, progress_note, blockers, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_id,
                        raw_id,
                        log_date,
                        log_date,
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

            if parsed.journal:
                item = parsed.journal
                row_id = connection.execute(
                    """
                    INSERT INTO journal_entries
                    (raw_message_id, source_message_id, date, entry_date, text, tags_json, sentiment, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        raw_id,
                        raw_id,
                        log_date,
                        log_date,
                        item.text,
                        json.dumps(item.tags),
                        item.sentiment,
                        now,
                    ),
                ).lastrowid
                records["journal"].append({"id": row_id, **item.model_dump()})

            connection.execute("UPDATE raw_messages SET processed = 1 WHERE id = ?", (raw_id,))

        return {"raw_message_id": raw_id, "records": records}

    def recent_logs(self, limit: int = 25) -> dict[str, list[dict[str, Any]]]:
        with self.connect() as connection:
            return {
                "raw_messages": _rows(
                    connection,
                    """
                    SELECT id, source, COALESCE(received_at, created_at) AS received_at,
                           COALESCE(user_text, text) AS user_text, processed, entry_date
                    FROM raw_messages
                    ORDER BY COALESCE(received_at, created_at) DESC
                    LIMIT ?
                    """,
                    (limit,),
                ),
                "daily_checkins": _rows(
                    connection,
                    "SELECT * FROM daily_checkins ORDER BY created_at DESC LIMIT ?",
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
                "workout_exercises": _rows(
                    connection,
                    "SELECT * FROM workout_exercises ORDER BY created_at DESC LIMIT ?",
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


def _run_migrations(connection: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = _table_columns(connection, table)
        for column, column_type in columns.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    connection.execute(
        """
        UPDATE raw_messages
        SET received_at = COALESCE(received_at, created_at),
            user_text = COALESCE(user_text, text),
            processed = COALESCE(processed, 1)
        """
    )
    connection.execute(
        """
        UPDATE nutrition_logs
        SET date = COALESCE(date, entry_date),
            source_message_id = COALESCE(source_message_id, raw_message_id),
            description = COALESCE(description, meal_name)
        """
    )
    connection.execute(
        """
        UPDATE workout_logs
        SET date = COALESCE(date, entry_date),
            source_message_id = COALESCE(source_message_id, raw_message_id)
        """
    )
    connection.execute(
        """
        UPDATE career_logs
        SET date = COALESCE(date, entry_date),
            source_message_id = COALESCE(source_message_id, raw_message_id)
        """
    )
    connection.execute(
        """
        UPDATE journal_entries
        SET date = COALESCE(date, entry_date),
            source_message_id = COALESCE(source_message_id, raw_message_id)
        """
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in _query_rows(connection, f"PRAGMA table_info({table})", ())}


def _has_wellbeing_signal(item) -> bool:
    return any(
        value is not None
        for value in (
            item.sleep_hours,
            item.sleep_quality,
            item.energy,
            item.stress,
            item.mood,
            item.notes,
        )
    )


def _rows(connection: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return _query_rows(connection, query, params)


def _query_rows(connection: Any, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor = connection.execute(query, params)
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], sqlite3.Row):
        return [dict(row) for row in rows]

    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _use_turso() -> bool:
    return bool(settings.turso_database_url and settings.turso_auth_token)


def _connect(path: Path) -> Any:
    if not _use_turso():
        return sqlite3.connect(path)

    try:
        import libsql
    except ImportError as exc:
        raise RuntimeError(
            "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set, but the libsql package is not "
            "installed. Run `pip install -e .` after installing dependencies."
        ) from exc

    kwargs: dict[str, Any] = {
        "sync_url": settings.turso_database_url,
        "auth_token": settings.turso_auth_token,
    }
    if settings.turso_sync_interval_seconds:
        kwargs["sync_interval"] = settings.turso_sync_interval_seconds
    return libsql.connect(str(path), **kwargs)
