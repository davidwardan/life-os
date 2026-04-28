from __future__ import annotations

import sqlite3
from typing import Any

from backend.app.schemas import ParsedDailyLog


def has_wellbeing_signal(item: Any) -> bool:
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


def enrich_from_history(connection: Any, parsed: ParsedDailyLog, log_date: str) -> None:
    if not parsed.workout:
        return
    for exercise in parsed.workout.exercises:
        previous = _rows(
            connection,
            """
            SELECT e.sets, e.reps, e.load, e.duration_min
            FROM workout_exercises e
            JOIN workout_logs w ON w.id = e.workout_id
            WHERE LOWER(e.name) = LOWER(?) AND w.date < ?
            ORDER BY w.date DESC, e.created_at DESC
            LIMIT 1
            """,
            (exercise.name, log_date),
        )
        if not previous:
            continue
        row = previous[0]
        if exercise.sets is None:
            exercise.sets = row["sets"]
        if exercise.reps is None:
            exercise.reps = row["reps"]
        if exercise.load is None:
            exercise.load = row["load"]
        if exercise.duration_min is None:
            exercise.duration_min = row["duration_min"]


def duplicate_daily_checkin(connection: Any, log_date: str, item: Any) -> bool:
    return _exists(
        connection,
        """
        SELECT 1 FROM daily_checkins
        WHERE date = ?
          AND sleep_hours IS ?
          AND sleep_quality IS ?
          AND energy IS ?
          AND stress IS ?
          AND mood IS ?
          AND COALESCE(notes, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (
            log_date,
            item.sleep_hours,
            item.sleep_quality,
            item.energy,
            item.stress,
            item.mood,
            item.notes,
        ),
    )


def duplicate_nutrition(connection: Any, log_date: str, item: Any) -> bool:
    return _exists(
        connection,
        """
        SELECT 1 FROM nutrition_logs
        WHERE date = ?
          AND COALESCE(meal_type, '') = COALESCE(?, '')
          AND LOWER(COALESCE(description, meal_name, '')) = LOWER(?)
        LIMIT 1
        """,
        (log_date, item.meal_type, item.description),
    )


def duplicate_workout(connection: Any, log_date: str, item: Any) -> bool:
    return _exists(
        connection,
        """
        SELECT 1 FROM workout_logs
        WHERE date = ?
          AND COALESCE(workout_type, '') = COALESCE(?, '')
          AND duration_min IS ?
          AND distance_km IS ?
          AND pace IS ?
          AND intensity IS ?
        LIMIT 1
        """,
        (
            log_date,
            item.workout_type,
            item.duration_min,
            item.distance_km,
            item.pace,
            item.intensity,
        ),
    )


def duplicate_exercise(connection: Any, log_date: str, exercise: Any) -> bool:
    return _exists(
        connection,
        """
        SELECT 1
        FROM workout_exercises e
        JOIN workout_logs w ON w.id = e.workout_id
        WHERE w.date = ?
          AND LOWER(e.name) = LOWER(?)
          AND e.sets IS ?
          AND e.reps IS ?
          AND COALESCE(e.load, '') = COALESCE(?, '')
          AND e.duration_min IS ?
        LIMIT 1
        """,
        (
            log_date,
            exercise.name,
            exercise.sets,
            exercise.reps,
            exercise.load,
            exercise.duration_min,
        ),
    )


def duplicate_career(connection: Any, log_date: str, item: Any) -> bool:
    return _exists(
        connection,
        """
        SELECT 1 FROM career_logs
        WHERE date = ?
          AND COALESCE(project, '') = COALESCE(?, '')
          AND duration_hours IS ?
          AND COALESCE(progress_note, '') = COALESCE(?, '')
        LIMIT 1
        """,
        (log_date, item.project, item.duration_hours, item.progress_note),
    )


def duplicate_journal(connection: Any, log_date: str, item: Any) -> bool:
    return _exists(
        connection,
        """
        SELECT 1 FROM journal_entries
        WHERE date = ? AND text = ?
        LIMIT 1
        """,
        (log_date, item.text),
    )


def _exists(connection: Any, query: str, params: tuple[Any, ...]) -> bool:
    return bool(_rows(connection, query, params))


def _rows(connection: Any, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor = connection.execute(query, params)
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], sqlite3.Row):
        return [dict(row) for row in rows]
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]
