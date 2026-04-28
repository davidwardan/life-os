from __future__ import annotations

import sqlite3
from typing import Any

DELETABLE_LOG_KINDS = {
    "raw_messages",
    "daily_checkins",
    "nutrition",
    "workout",
    "workout_exercises",
    "career",
    "journal",
    "memory",
}


def canonical_kind(kind: str | None) -> str:
    normalized = (kind or "raw_messages").strip().lower().replace("-", "_")
    aliases = {
        "raw": "raw_messages",
        "raw_message": "raw_messages",
        "raw_messages": "raw_messages",
        "log": "raw_messages",
        "logs": "raw_messages",
        "message": "raw_messages",
        "messages": "raw_messages",
        "daily": "daily_checkins",
        "daily_checkin": "daily_checkins",
        "daily_checkins": "daily_checkins",
        "checkin": "daily_checkins",
        "checkins": "daily_checkins",
        "wellbeing": "daily_checkins",
        "wellbeing_log": "daily_checkins",
        "nutrition": "nutrition",
        "nutrition_log": "nutrition",
        "nutrition_logs": "nutrition",
        "meal": "nutrition",
        "meals": "nutrition",
        "food": "nutrition",
        "workout": "workout",
        "workouts": "workout",
        "workout_log": "workout",
        "workout_logs": "workout",
        "exercise": "workout_exercises",
        "exercises": "workout_exercises",
        "workout_exercise": "workout_exercises",
        "workout_exercises": "workout_exercises",
        "career": "career",
        "career_log": "career",
        "career_logs": "career",
        "work": "career",
        "journal": "journal",
        "journal_entry": "journal",
        "journal_entries": "journal",
        "memory": "memory",
        "memories": "memory",
        "memory_item": "memory",
        "memory_items": "memory",
    }
    canonical = aliases.get(normalized)
    if canonical not in DELETABLE_LOG_KINDS:
        raise ValueError(f"Unsupported log kind: {kind}")
    return canonical


def kind_table(kind: str) -> str:
    return {
        "raw_messages": "raw_messages",
        "daily_checkins": "daily_checkins",
        "nutrition": "nutrition_logs",
        "workout": "workout_logs",
        "workout_exercises": "workout_exercises",
        "career": "career_logs",
        "journal": "journal_entries",
        "memory": "memory_items",
    }[kind]


def deletable_rows(
    connection: Any,
    kind: str,
    limit: int,
    entry_date: str | None = None,
) -> list[dict[str, Any]]:
    date_filter = "AND date = ?" if entry_date else ""
    params: tuple[Any, ...]
    if kind == "raw_messages":
        raw_filter = "WHERE entry_date = ?" if entry_date else ""
        params = (entry_date, limit) if entry_date else (limit,)
        rows = _rows(
            connection,
            f"""
            SELECT id,
                   'raw_messages' AS kind,
                   entry_date AS date,
                   COALESCE(received_at, created_at) AS created_at,
                   COALESCE(user_text, text, '') AS summary
            FROM raw_messages
            {raw_filter}
            ORDER BY COALESCE(received_at, created_at) DESC
            LIMIT ?
            """,
            params,
        )
    elif kind == "daily_checkins":
        params = (entry_date, limit) if entry_date else (limit,)
        rows = _rows(
            connection,
            f"""
            SELECT id,
                   'daily_checkins' AS kind,
                   date,
                   created_at,
                   TRIM(
                       COALESCE('energy ' || energy || ' ', '') ||
                       COALESCE('stress ' || stress || ' ', '') ||
                       COALESCE('mood ' || mood || ' ', '') ||
                       COALESCE(notes, '')
                   ) AS summary
            FROM daily_checkins
            WHERE 1 = 1 {date_filter}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )
    elif kind == "nutrition":
        params = (entry_date, limit) if entry_date else (limit,)
        rows = _rows(
            connection,
            f"""
            SELECT id,
                   'nutrition' AS kind,
                   date,
                   created_at,
                   TRIM(COALESCE(meal_type || ': ', '') || COALESCE(description, meal_name, 'meal')) AS summary
            FROM nutrition_logs
            WHERE 1 = 1 {date_filter}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )
    elif kind == "workout":
        params = (entry_date, limit) if entry_date else (limit,)
        rows = _rows(
            connection,
            f"""
            SELECT id,
                   'workout' AS kind,
                   date,
                   created_at,
                   TRIM(COALESCE(workout_type, 'workout') || COALESCE(' - ' || notes, '')) AS summary
            FROM workout_logs
            WHERE 1 = 1 {date_filter}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )
    elif kind == "workout_exercises":
        exercise_filter = "AND w.date = ?" if entry_date else ""
        params = (entry_date, limit) if entry_date else (limit,)
        rows = _rows(
            connection,
            f"""
            SELECT e.id,
                   'workout_exercises' AS kind,
                   w.date,
                   e.created_at,
                   TRIM(
                       e.name ||
                       COALESCE(' ' || e.sets || 'x' || e.reps, '') ||
                       COALESCE(' at ' || e.load, '')
                   ) AS summary
            FROM workout_exercises e
            JOIN workout_logs w ON w.id = e.workout_id
            WHERE 1 = 1 {exercise_filter}
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            params,
        )
    elif kind == "career":
        params = (entry_date, limit) if entry_date else (limit,)
        rows = _rows(
            connection,
            f"""
            SELECT id,
                   'career' AS kind,
                   date,
                   created_at,
                   TRIM(
                       COALESCE(duration_hours || 'h ', '') ||
                       COALESCE(project, 'career') ||
                       COALESCE(' - ' || progress_note, '')
                   ) AS summary
            FROM career_logs
            WHERE 1 = 1 {date_filter}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )
    elif kind == "journal":
        params = (entry_date, limit) if entry_date else (limit,)
        rows = _rows(
            connection,
            f"""
            SELECT id,
                   'journal' AS kind,
                   date,
                   created_at,
                   text AS summary
            FROM journal_entries
            WHERE 1 = 1 {date_filter}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )
    elif kind == "memory":
        memory_filter = "WHERE DATE(created_at) = ?" if entry_date else ""
        params = (entry_date, limit) if entry_date else (limit,)
        rows = _rows(
            connection,
            f"""
            SELECT id,
                   'memory' AS kind,
                   DATE(created_at) AS date,
                   created_at,
                   TRIM(category || ': ' || value) AS summary
            FROM memory_items
            {memory_filter}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        )
    else:
        raise ValueError(f"Unsupported log kind: {kind}")

    for row in rows:
        row["summary"] = _truncate(row.get("summary") or row["kind"])
    return rows


def fetch_deletable_row(connection: Any, kind: str, record_id: int) -> dict[str, Any] | None:
    candidates = deletable_rows(connection, kind, 100)
    for row in candidates:
        if row["id"] == record_id:
            return row
    table = kind_table(kind)
    exists = _rows(connection, f"SELECT id FROM {table} WHERE id = ? LIMIT 1", (record_id,))
    if not exists:
        return None
    return {"kind": kind, "id": record_id, "summary": f"{kind} #{record_id}"}


def delete_raw_message(connection: Any, raw_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    workout_ids = [
        row["id"]
        for row in _rows(
            connection,
            """
            SELECT id FROM workout_logs
            WHERE source_message_id = ? OR raw_message_id = ?
            """,
            (raw_id, raw_id),
        )
    ]
    for workout_id in workout_ids:
        counts["workout_exercises"] = counts.get("workout_exercises", 0) + delete_where(
            connection,
            "DELETE FROM workout_exercises WHERE workout_id = ?",
            (workout_id,),
        )

    for kind in ("daily_checkins", "nutrition", "workout", "career", "journal"):
        table = kind_table(kind)
        counts[kind] = delete_where(
            connection,
            f"DELETE FROM {table} WHERE source_message_id = ? OR raw_message_id = ?",
            (raw_id, raw_id),
        )
    counts["wellbeing_logs"] = delete_where(
        connection,
        "DELETE FROM wellbeing_logs WHERE source_message_id = ? OR raw_message_id = ?",
        (raw_id, raw_id),
    )
    counts["memory"] = delete_where(
        connection,
        "DELETE FROM memory_items WHERE source_message_id = ?",
        (raw_id,),
    )
    counts["raw_messages"] = delete_where(
        connection,
        "DELETE FROM raw_messages WHERE id = ?",
        (raw_id,),
    )
    return counts


def delete_where(connection: Any, query: str, params: tuple[Any, ...]) -> int:
    cursor = connection.execute(query, params)
    rowcount = getattr(cursor, "rowcount", None)
    return int(rowcount) if isinstance(rowcount, int) and rowcount >= 0 else 0


def _truncate(value: str, limit: int = 96) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _rows(connection: Any, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor = connection.execute(query, params)
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], sqlite3.Row):
        return [dict(row) for row in rows]
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]
