from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backend.app.db import LifeDatabase
from backend.app.schemas import ParsedDailyLog


MEMORY_CATEGORIES = (
    "briefing_style",
    "preference",
    "aversion",
    "strategy",
    "anti_strategy",
    "personality",
    "goal",
    "reminder",
)


@dataclass(frozen=True)
class MemoryCandidate:
    category: str
    subject: str
    value: str
    evidence: str
    confidence: float = 0.72
    importance: int = 3


def is_memory_request(text: str) -> bool:
    lower = " ".join(text.lower().strip().split())
    return lower.startswith(("remember ", "remember that ", "note that ", "for future briefings "))


class MemoryService:
    def __init__(self, db: LifeDatabase):
        self.db = db

    def learn_from_message(
        self,
        text: str,
        parsed: ParsedDailyLog | None = None,
        source_message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        candidates = extract_memory_candidates(text, parsed)
        saved = []
        for candidate in candidates[:8]:
            saved.append(self.upsert(candidate, source_message_id))
        return saved

    def upsert(
        self, candidate: MemoryCandidate, source_message_id: int | None = None
    ) -> dict[str, Any]:
        now = _now()
        with self.db.connect() as connection:
            existing = _rows(
                connection,
                """
                SELECT *
                FROM memory_items
                WHERE category = ? AND subject = ? AND value = ?
                LIMIT 1
                """,
                (candidate.category, candidate.subject, candidate.value),
            )
            if existing:
                row = existing[0]
                connection.execute(
                    """
                    UPDATE memory_items
                    SET evidence = ?,
                        source_message_id = COALESCE(?, source_message_id),
                        confidence = MAX(confidence, ?),
                        importance = MAX(importance, ?),
                        times_seen = times_seen + 1,
                        active = 1,
                        updated_at = ?,
                        last_seen_at = ?
                    WHERE id = ?
                    """,
                    (
                        candidate.evidence,
                        source_message_id,
                        candidate.confidence,
                        candidate.importance,
                        now,
                        now,
                        row["id"],
                    ),
                )
                return {
                    **row,
                    "times_seen": row["times_seen"] + 1,
                    "updated_at": now,
                    "last_seen_at": now,
                }

            row_id = connection.execute(
                """
                INSERT INTO memory_items
                (category, subject, value, evidence, source_message_id, confidence, importance,
                 times_seen, active, created_at, updated_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?)
                """,
                (
                    candidate.category,
                    candidate.subject,
                    candidate.value,
                    candidate.evidence,
                    source_message_id,
                    candidate.confidence,
                    candidate.importance,
                    now,
                    now,
                    now,
                ),
            ).lastrowid
            return {
                "id": row_id,
                "category": candidate.category,
                "subject": candidate.subject,
                "value": candidate.value,
                "evidence": candidate.evidence,
                "source_message_id": source_message_id,
                "confidence": candidate.confidence,
                "importance": candidate.importance,
                "times_seen": 1,
                "active": 1,
                "created_at": now,
                "updated_at": now,
                "last_seen_at": now,
            }

    def list_items(
        self,
        category: str | None = None,
        query: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 100))
        params: list[Any] = []
        where = ["active = 1"]
        if category:
            where.append("category = ?")
            params.append(category)

        rows = self._rows(
            f"""
            SELECT *
            FROM memory_items
            WHERE {" AND ".join(where)}
            ORDER BY importance DESC, times_seen DESC, last_seen_at DESC
            LIMIT ?
            """,
            (*params, bounded_limit * 3 if query else bounded_limit),
        )
        if not query:
            return rows

        scored = [(_memory_score(row, query), row) for row in rows]
        return [
            row
            for score, row in sorted(scored, key=lambda item: item[0], reverse=True)
            if score > 0
        ][:bounded_limit]

    def briefing_context(self) -> dict[str, list[dict[str, Any]]]:
        rows = self.list_items(limit=60)
        context: dict[str, list[dict[str, Any]]] = {category: [] for category in MEMORY_CATEGORIES}
        for row in rows:
            if row["category"] in context and len(context[row["category"]]) < 6:
                context[row["category"]].append(_public_memory(row))
        return {category: items for category, items in context.items() if items}

    def backfill_from_raw_messages(self, limit: int = 200) -> dict[str, int]:
        rows = self._rows(
            """
            SELECT id, COALESCE(user_text, text) AS text
            FROM raw_messages
            WHERE COALESCE(user_text, text) IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 1000)),),
        )
        learned = 0
        for row in rows:
            learned += len(self.learn_from_message(row["text"], source_message_id=row["id"]))
        return {"messages_scanned": len(rows), "memory_items_touched": learned}

    def _rows(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            return _rows(connection, query, params)


def extract_memory_candidates(
    text: str, parsed: ParsedDailyLog | None = None
) -> list[MemoryCandidate]:
    del parsed
    candidates: list[MemoryCandidate] = []
    for sentence in _sentences(text):
        candidates.extend(_extract_from_sentence(sentence))
    return _dedupe(candidates)


def _extract_from_sentence(sentence: str) -> list[MemoryCandidate]:
    clean = _clean_sentence(sentence)
    lower = clean.lower()
    results: list[MemoryCandidate] = []

    briefing_value = _match_first(
        clean,
        (
            r"(?:i want|make|keep)?\s*(?:my\s*)?briefings?\s+(?:to be|should be|more|as)?\s*(.+)",
            r"(?:talk to me|write to me|respond)\s+(?:like|as|with)\s+(.+)",
            r"for future briefings[,:\s]+(.+)",
        ),
    )
    if briefing_value:
        results.append(
            MemoryCandidate(
                category="briefing_style",
                subject="briefing",
                value=_normalize_value(briefing_value),
                evidence=clean,
                confidence=0.82,
                importance=5,
            )
        )

    preference = _match_first(
        clean,
        (
            r"\bi(?: really)? (?:like|love|enjoy|prefer|appreciate|am a fan of)\s+(.+)",
            r"\bwhat i like is\s+(.+)",
        ),
    )
    if preference:
        results.append(
            MemoryCandidate(
                category="preference",
                subject=_subject_for(preference, lower),
                value=_normalize_value(preference),
                evidence=clean,
                confidence=0.78,
                importance=4,
            )
        )

    aversion = _match_first(
        clean,
        (
            r"\bi\s+(?:do not|don't|dont|really don't|really dont)\s+(?:like|want)\s+(.+)",
            r"\bi\s+(?:hate|dislike|can't stand|cannot stand)\s+(.+)",
        ),
    )
    if aversion:
        results.append(
            MemoryCandidate(
                category="aversion",
                subject=_subject_for(aversion, lower),
                value=_normalize_value(aversion),
                evidence=clean,
                confidence=0.78,
                importance=4,
            )
        )

    strategy = _match_first(
        clean,
        (
            r"\b(.+?)\s+(?:works for me|helps me|is effective for me)\b",
            r"\bwhat works for me is\s+(.+)",
            r"\bi respond well to\s+(.+)",
        ),
    )
    if strategy:
        results.append(
            MemoryCandidate(
                category="strategy",
                subject=_subject_for(strategy, lower),
                value=_normalize_value(strategy),
                evidence=clean,
                confidence=0.8,
                importance=5,
            )
        )

    anti_strategy = _match_first(
        clean,
        (
            r"\b(.+?)\s+(?:does not work for me|doesn't work for me|doesnt work for me|do not work for me|don't work for me|dont work for me|does not help|doesn't help|doesnt help)\b",
            r"\bwhat doesn't work for me is\s+(.+)",
        ),
    )
    if anti_strategy:
        results.append(
            MemoryCandidate(
                category="anti_strategy",
                subject=_subject_for(anti_strategy, lower),
                value=_normalize_value(anti_strategy),
                evidence=clean,
                confidence=0.8,
                importance=5,
            )
        )

    personality = _match_first(
        clean,
        (
            r"\bi am the kind of person who\s+(.+)",
            r"\bi'm the kind of person who\s+(.+)",
            r"\bi tend to\s+(.+)",
        ),
    )
    if personality:
        results.append(
            MemoryCandidate(
                category="personality",
                subject="self",
                value=_normalize_value(personality),
                evidence=clean,
                confidence=0.68,
                importance=3,
            )
        )

    goal = _match_first(
        clean,
        (
            r"\bmy goal is to\s+(.+)",
            r"\bi want to get better at\s+(.+)",
            r"\bi need to improve\s+(.+)",
        ),
    )
    if goal:
        results.append(
            MemoryCandidate(
                category="goal",
                subject=_subject_for(goal, lower),
                value=_normalize_value(goal),
                evidence=clean,
                confidence=0.72,
                importance=4,
            )
        )

    reminder = _match_first(clean, (r"\bremind me to\s+(.+)",))
    if reminder:
        results.append(
            MemoryCandidate(
                category="reminder",
                subject=_subject_for(reminder, lower),
                value=_normalize_value(reminder),
                evidence=clean,
                confidence=0.76,
                importance=4,
            )
        )

    return [candidate for candidate in results if candidate.value]


def _sentences(text: str) -> list[str]:
    normalized = re.sub(r"^\s*(remember|remember that|note that)\s+", "", text.strip(), flags=re.I)
    return [part.strip() for part in re.split(r"(?:[.!?]\s+|\n+)", normalized) if part.strip()]


def _match_first(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return match.group(1).strip(" .,:;-")
    return None


def _clean_sentence(sentence: str) -> str:
    return " ".join(sentence.strip().split()).strip(" .")


def _normalize_value(value: str) -> str:
    value = re.split(r"\b(?:because|but only if|unless)\b", value, maxsplit=1, flags=re.I)[0]
    value = re.sub(r"^(that|to|be)\s+", "", value.strip(), flags=re.I)
    return value.strip(" .,:;-").lower()


def _subject_for(value: str, lower_sentence: str) -> str:
    lower_value = value.lower()
    if "brief" in lower_sentence or "briefing" in lower_value:
        return "briefing"
    if any(word in lower_value for word in ("train", "workout", "lift", "gym", "run")):
        return "training"
    if any(word in lower_value for word in ("food", "meal", "protein", "calorie", "nutrition")):
        return "nutrition"
    if any(word in lower_value for word in ("work", "career", "paper", "research", "project")):
        return "career"
    if any(word in lower_value for word in ("sleep", "recover", "stress", "energy")):
        return "wellbeing"
    if any(word in lower_value for word in ("design", "minimal", "swiss", "visual", "plot")):
        return "design"
    return "general"


def _dedupe(candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
    seen = set()
    result = []
    for candidate in candidates:
        key = (candidate.category, candidate.subject, candidate.value)
        if key not in seen and len(candidate.value) >= 3:
            seen.add(key)
            result.append(candidate)
    return result


def _memory_score(row: dict[str, Any], query: str) -> int:
    terms = {term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2}
    haystack = " ".join(
        str(row.get(key) or "") for key in ("category", "subject", "value", "evidence")
    ).lower()
    return sum(1 for term in terms if term in haystack)


def _public_memory(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": row["category"],
        "subject": row["subject"],
        "value": row["value"],
        "confidence": row["confidence"],
        "importance": row["importance"],
        "times_seen": row["times_seen"],
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
