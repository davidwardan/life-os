"""Shared low-level database helpers."""

from __future__ import annotations

import sqlite3
from typing import Any


def rows_as_dicts(
    connection: Any, query: str, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    """Run a read query and return rows as plain dicts.

    Works with both sqlite3 connections (Row factory) and libsql
    connections, which return bare tuples.
    """
    cursor = connection.execute(query, params)
    rows = cursor.fetchall()
    if not rows:
        return []
    if isinstance(rows[0], sqlite3.Row):
        return [dict(row) for row in rows]
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]
