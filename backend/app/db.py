from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.app._db_dedup import (
    duplicate_career,
    duplicate_daily_checkin,
    duplicate_exercise,
    duplicate_journal,
    duplicate_nutrition,
    duplicate_workout,
    enrich_from_history,
    has_wellbeing_signal,
)
from backend.app._db_deletion import (
    DELETABLE_LOG_KINDS,
    canonical_kind,
    delete_raw_message,
    delete_where,
    deletable_rows,
    fetch_deletable_row,
    kind_table,
)
from backend.app._db_schema import SCHEMA, run_migrations
from backend.app.config import DEFAULT_DB_PATH, settings
from backend.app.schemas import MessageIn, ParsedDailyLog

__all__ = ["DELETABLE_LOG_KINDS", "LifeDatabase"]


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
            connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            pass
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
            run_migrations(connection)

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
            enrich_from_history(connection, parsed, log_date)

            records: dict[str, list[dict[str, Any]]] = {
                "daily_checkins": [],
                "nutrition": [],
                "workout": [],
                "workout_exercises": [],
                "career": [],
                "journal": [],
            }

            if parsed.wellbeing and has_wellbeing_signal(parsed.wellbeing):
                item = parsed.wellbeing
                if not duplicate_daily_checkin(connection, log_date, item):
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
                if duplicate_nutrition(connection, log_date, item):
                    continue
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
                exercises_to_insert = [
                    exercise
                    for exercise in item.exercises
                    if not duplicate_exercise(connection, log_date, exercise)
                ]
                if item.exercises and not exercises_to_insert:
                    item = None
                elif not item.exercises and duplicate_workout(connection, log_date, item):
                    item = None

                if item:
                    workout_id = connection.execute(
                        """
                        INSERT INTO workout_logs
                        (raw_message_id, source_message_id, date, entry_date, workout_type, duration_min,
                         distance_km, pace,
                         intensity, notes, confidence, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            raw_id,
                            raw_id,
                            log_date,
                            log_date,
                            item.workout_type,
                            item.duration_min,
                            item.distance_km,
                            item.pace,
                            item.intensity,
                            item.notes,
                            item.confidence,
                            now,
                        ),
                    ).lastrowid
                    records["workout"].append({"id": workout_id, **item.model_dump()})

                    for exercise in exercises_to_insert:
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
                        records["workout_exercises"].append(
                            {"id": exercise_id, **exercise.model_dump()}
                        )

            for item in parsed.career:
                if duplicate_career(connection, log_date, item):
                    continue
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
                if not duplicate_journal(connection, log_date, item):
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

    def deletable_logs(self, limit: int = 25, kind: str | None = None) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 100))
        kinds = [canonical_kind(kind)] if kind else list(DELETABLE_LOG_KINDS)
        rows: list[dict[str, Any]] = []
        with self.connect() as connection:
            for log_kind in kinds:
                rows.extend(deletable_rows(connection, log_kind, bounded_limit))
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        return rows[:bounded_limit]

    def latest_deletable(
        self, kind: str | None = None, entry_date: str | None = None
    ) -> list[dict[str, Any]]:
        kinds = [canonical_kind(kind)] if kind else ["raw_messages"]
        rows: list[dict[str, Any]] = []
        with self.connect() as connection:
            for log_kind in kinds:
                rows.extend(deletable_rows(connection, log_kind, 25, entry_date=entry_date))
        rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
        return rows

    def delete_log(self, kind: str, record_id: int) -> dict[str, Any]:
        canon = canonical_kind(kind)
        if record_id < 1:
            raise ValueError("record_id must be positive")

        with self.connect() as connection:
            row = fetch_deletable_row(connection, canon, record_id)
            if not row:
                return {
                    "deleted": False,
                    "kind": canon,
                    "id": record_id,
                    "summary": None,
                    "counts": {},
                }

            counts: dict[str, int] = {}
            if canon == "raw_messages":
                counts = delete_raw_message(connection, record_id)
            elif canon == "workout":
                counts["workout_exercises"] = delete_where(
                    connection,
                    "DELETE FROM workout_exercises WHERE workout_id = ?",
                    (record_id,),
                )
                counts["workout"] = delete_where(
                    connection,
                    "DELETE FROM workout_logs WHERE id = ?",
                    (record_id,),
                )
            else:
                table = kind_table(canon)
                counts[canon] = delete_where(
                    connection,
                    f"DELETE FROM {table} WHERE id = ?",
                    (record_id,),
                )

            return {
                "deleted": True,
                "kind": canon,
                "id": record_id,
                "summary": row["summary"],
                "date": row.get("date"),
                "counts": counts,
            }


def _rows(connection: Any, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
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
