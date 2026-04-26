from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from backend.app.db import LifeDatabase


_DELETE_PREFIX = re.compile(r"^\s*(?:/delete|delete|remove)\b", re.IGNORECASE)
_DELETE_ID = re.compile(
    r"^\s*(?:/delete|delete|remove)\s+"
    r"(?:(?P<kind>[a-zA-Z_ -]+?)\s+)?#?(?P<id>\d+)\s*$",
    re.IGNORECASE,
)
_DELETE_LAST = re.compile(
    r"^\s*(?:/delete|delete|remove)\s+"
    r"(?:my\s+)?(?:latest|last|most\s+recent)"
    r"(?:\s+(?P<kind>[a-zA-Z_ -]+))?\s*$",
    re.IGNORECASE,
)
_DELETE_TODAY = re.compile(
    r"^\s*(?:/delete|delete|remove)\s+"
    r"(?:(?:today'?s|todays|today)\s+(?P<kind_a>[a-zA-Z_ -]+)|"
    r"(?P<kind_b>[a-zA-Z_ -]+)\s+(?:today|today'?s|todays))\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DeleteResult:
    ok: bool
    status: str
    confirmation: str
    deleted: dict[str, Any] | None = None


def is_delete_request(text: str) -> bool:
    return bool(_DELETE_PREFIX.match(text))


def handle_delete_request(db: LifeDatabase, text: str, entry_date: date | None = None) -> DeleteResult:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in {"/delete", "delete", "delete logs", "delete log", "remove logs", "show delete options"}:
        return DeleteResult(
            ok=True,
            status="delete_options_sent",
            confirmation=_format_candidates(db.deletable_logs(limit=10)),
        )

    match = _DELETE_ID.match(stripped)
    if match:
        kind = _clean_kind(match.group("kind")) or "raw_messages"
        record_id = int(match.group("id"))
        try:
            deleted = db.delete_log(kind, record_id)
        except ValueError as error:
            return DeleteResult(ok=True, status="delete_ambiguous", confirmation=str(error))
        return _delete_result(deleted)

    match = _DELETE_LAST.match(stripped)
    if match:
        kind = _clean_kind(match.group("kind")) or "raw_messages"
        try:
            candidates = db.latest_deletable(kind=kind)
        except ValueError as error:
            return DeleteResult(ok=True, status="delete_ambiguous", confirmation=str(error))
        if not candidates:
            return DeleteResult(
                ok=True,
                status="delete_not_found",
                confirmation=f"I could not find any {kind.replace('_', ' ')} logs to delete.",
            )
        deleted = db.delete_log(candidates[0]["kind"], candidates[0]["id"])
        return _delete_result(deleted)

    match = _DELETE_TODAY.match(stripped)
    if match:
        kind = _clean_kind(match.group("kind_a") or match.group("kind_b")) or "raw_messages"
        if entry_date is None:
            return DeleteResult(
                ok=True,
                status="delete_ambiguous",
                confirmation="I need a Telegram message date to delete today's log. Try deleting by ID instead.",
            )
        try:
            candidates = db.latest_deletable(kind=kind, entry_date=entry_date.isoformat())
        except ValueError as error:
            return DeleteResult(ok=True, status="delete_ambiguous", confirmation=str(error))
        if not candidates:
            return DeleteResult(
                ok=True,
                status="delete_not_found",
                confirmation=f"I could not find a {kind.replace('_', ' ')} log for today.",
            )
        if len(candidates) > 1:
            return DeleteResult(
                ok=True,
                status="delete_ambiguous",
                confirmation=(
                    "I found more than one match for today. Delete one by ID:\n"
                    + _format_candidates(candidates)
                ),
            )
        deleted = db.delete_log(candidates[0]["kind"], candidates[0]["id"])
        return _delete_result(deleted)

    return DeleteResult(
        ok=True,
        status="delete_ambiguous",
        confirmation=(
            "I can delete by ID or by latest item.\n"
            "Examples: delete workout #12, delete last meal, delete today's journal.\n\n"
            + _format_candidates(db.deletable_logs(limit=8))
        ),
    )


def _delete_result(deleted: dict[str, Any]) -> DeleteResult:
    if not deleted["deleted"]:
        return DeleteResult(
            ok=True,
            status="delete_not_found",
            confirmation=f"I could not find {deleted['kind'].replace('_', ' ')} #{deleted['id']}.",
            deleted=deleted,
        )
    summary = deleted.get("summary") or f"{deleted['kind']} #{deleted['id']}"
    return DeleteResult(
        ok=True,
        status="deleted",
        confirmation=f"Deleted {deleted['kind'].replace('_', ' ')} #{deleted['id']}: {summary}",
        deleted=deleted,
    )


def _format_candidates(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "No logs found."
    lines = ["Recent deletable logs:"]
    for item in candidates[:10]:
        date_text = f" [{item['date']}]" if item.get("date") else ""
        lines.append(
            f"- {item['kind'].replace('_', ' ')} #{item['id']}{date_text}: {item['summary']}"
        )
    lines.append("Use: delete <kind> #<id>")
    return "\n".join(lines)


def _clean_kind(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    cleaned = re.sub(r"\b(my|the|a|an)\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.replace(" ", "_") if cleaned else None
