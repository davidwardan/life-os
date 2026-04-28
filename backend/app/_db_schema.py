from __future__ import annotations

import sqlite3
from typing import Any

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
    distance_km REAL,
    pace REAL,
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

CREATE TABLE IF NOT EXISTS telegram_updates (
    update_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
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
        "distance_km": "REAL",
        "pace": "REAL",
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
    "telegram_updates": {
        "update_id": "INTEGER",
        "status": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    },
}


def run_migrations(connection: sqlite3.Connection) -> None:
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


def _table_columns(connection: Any, table: str) -> set[str]:
    cursor = connection.execute(f"PRAGMA table_info({table})")
    rows = cursor.fetchall()
    if not rows:
        return set()
    if isinstance(rows[0], sqlite3.Row):
        return {row["name"] for row in rows}
    columns = [column[0] for column in cursor.description]
    return {dict(zip(columns, row))["name"] for row in rows}
