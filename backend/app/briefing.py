from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from backend.app.config import settings
from backend.app.db import LifeDatabase
from backend.app.memory import MemoryService


BRIEFING_SYSTEM_PROMPT = """
You write concise morning briefings for a personal life logging app.

Use only the provided analytics features. Do not invent data.
Tone: direct, practical, calm, slightly candid. Avoid therapy language and hype.
Write like a familiar assistant, not a report generator. Vary sentence shape and avoid templated filler.
The features are aggregates over windows. Do not describe weekly totals or same-day grouped totals as a single session.
If a value looks odd because of duplicate or sparse logs, say the data looks noisy or thin.
If data_warnings is non-empty, use those warnings instead of treating suspicious values literally.
Use personal_memory to adapt the advice and style when relevant. Do not overfit to one weak memory item.
When the data is thin, say exactly what assumption you are making before giving advice.
Return a short briefing with:
- Today
- Push
- Chill
- Watch

Keep it under 120 words.
""".strip()


@dataclass(frozen=True)
class Briefing:
    date: date
    features: dict[str, Any]
    text: str
    method: str
    error: str | None = None


class BriefingClient(Protocol):
    async def write(self, features: dict[str, Any], target_date: date) -> str: ...


class OpenRouterBriefingClient:
    def __init__(
        self,
        api_key: str,
        model: str = settings.openrouter_model,
        fallback_models: tuple[str, ...] = settings.openrouter_fallback_models,
        base_url: str = settings.openrouter_base_url,
        timeout_seconds: float = settings.llm_timeout_seconds,
    ):
        self.api_key = api_key
        self.model = model
        self.fallback_models = fallback_models
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def write(self, features: dict[str, Any], target_date: date) -> str:
        errors: list[str] = []
        for model in (self.model, *self.fallback_models):
            try:
                return await self._write_with_model(model, features, target_date)
            except (asyncio.TimeoutError, httpx.HTTPError, ValueError) as error:
                errors.append(f"{model}: {_format_error(error)}")
        raise ValueError("; ".join(errors))

    async def _write_with_model(
        self, model: str, features: dict[str, Any], target_date: date
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "target_date": target_date.isoformat(),
                            "features": features,
                        },
                        sort_keys=True,
                    ),
                },
            ],
            "temperature": 0.25,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await asyncio.wait_for(
                client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://life-os.local",
                        "X-Title": "Life OS",
                    },
                    json=payload,
                ),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()

        return _decode_text(response.json())


class BriefingService:
    def __init__(
        self,
        db: LifeDatabase,
        client: BriefingClient | None = None,
        memory_service: MemoryService | None = None,
    ):
        self.db = db
        self.client = client
        self.memory_service = memory_service or MemoryService(db)

    async def generate(self, target_date: date | None = None) -> Briefing:
        briefing_date = target_date or _today()
        features = self.features(briefing_date)
        deterministic = _deterministic_briefing(briefing_date, features)

        client = self.client or _configured_briefing_client()
        if client is None:
            return Briefing(
                date=briefing_date, features=features, text=deterministic, method="deterministic"
            )

        try:
            text = await client.write(features, briefing_date)
            return Briefing(date=briefing_date, features=features, text=text, method="llm")
        except (asyncio.TimeoutError, httpx.HTTPError, ValueError) as error:
            return Briefing(
                date=briefing_date,
                features=features,
                text=deterministic,
                method="deterministic",
                error=f"LLM briefing failed: {_format_error(error)}",
            )

    def features(self, target_date: date) -> dict[str, Any]:
        return {
            "date": target_date.isoformat(),
            "wellbeing": self._wellbeing(target_date),
            "training": self._training(target_date),
            "nutrition": self._nutrition(target_date),
            "career": self._career(target_date),
            "journal": self._journal(target_date),
            "data_completeness": self._data_completeness(target_date),
            "personal_memory": self.memory_service.briefing_context(),
            "data_warnings": self._data_warnings(target_date),
        }

    def _wellbeing(self, target_date: date) -> dict[str, Any]:
        rows = self._rows(
            """
            SELECT date, sleep_hours, energy, stress, mood, notes
            FROM daily_checkins
            WHERE date BETWEEN ? AND ?
            ORDER BY date
            """,
            (_start(target_date, 7), target_date.isoformat()),
        )
        return {
            "days_logged": len(rows),
            "sleep_7d_avg": _avg(row["sleep_hours"] for row in rows),
            "energy_7d_avg": _avg(row["energy"] for row in rows),
            "stress_7d_avg": _avg(row["stress"] for row in rows),
            "mood_7d_avg": _avg(row["mood"] for row in rows),
            "yesterday": _row_for_date(rows, target_date - timedelta(days=1)),
            "recent_notes": [row["notes"] for row in rows[-3:] if row.get("notes")],
        }

    def _training(self, target_date: date) -> dict[str, Any]:
        rows = self._rows(
            """
            SELECT date, COUNT(*) AS sessions, SUM(duration_min) AS duration_min, AVG(intensity) AS intensity
            FROM workout_logs
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (_start(target_date, 7), target_date.isoformat()),
        )
        exercises = self._rows(
            """
            SELECT e.name AS name, COUNT(*) AS mentions
            FROM workout_exercises e
            JOIN workout_logs w ON w.id = e.workout_id
            WHERE w.date BETWEEN ? AND ?
            GROUP BY LOWER(e.name)
            ORDER BY mentions DESC, e.name
            LIMIT 5
            """,
            (_start(target_date, 7), target_date.isoformat()),
        )
        return {
            "training_days_7d": len(rows),
            "sessions_7d": sum(row["sessions"] or 0 for row in rows),
            "duration_min_7d": _sum(row["duration_min"] for row in rows),
            "intensity_7d_avg": _avg(row["intensity"] for row in rows),
            "last_training_day": rows[-1] if rows else None,
            "top_exercises_7d": exercises,
        }

    def _nutrition(self, target_date: date) -> dict[str, Any]:
        rows = self._rows(
            """
            SELECT date,
                   SUM(calories) AS calories,
                   SUM(protein_g) AS protein_g,
                   COUNT(*) AS meals
            FROM nutrition_logs
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            ORDER BY date
            """,
            (_start(target_date, 7), target_date.isoformat()),
        )
        return {
            "days_logged": len(rows),
            "meals_7d": sum(row["meals"] or 0 for row in rows),
            "calories_7d_avg": _avg(row["calories"] for row in rows),
            "protein_7d_avg": _avg(row["protein_g"] for row in rows),
            "yesterday": _row_for_date(rows, target_date - timedelta(days=1)),
        }

    def _career(self, target_date: date) -> dict[str, Any]:
        rows = self._rows(
            """
            SELECT date, project, activity, duration_hours, progress_note, blockers
            FROM career_logs
            WHERE date BETWEEN ? AND ?
            ORDER BY date
            """,
            (_start(target_date, 7), target_date.isoformat()),
        )
        projects = self._rows(
            """
            SELECT COALESCE(NULLIF(project, ''), 'unspecified') AS project,
                   SUM(duration_hours) AS duration_hours
            FROM career_logs
            WHERE date BETWEEN ? AND ? AND duration_hours IS NOT NULL
            GROUP BY COALESCE(NULLIF(project, ''), 'unspecified')
            ORDER BY duration_hours DESC
            LIMIT 5
            """,
            (_start(target_date, 7), target_date.isoformat()),
        )
        return {
            "entries_7d": len(rows),
            "deep_work_hours_7d": _sum(row["duration_hours"] for row in rows),
            "top_projects_7d": projects,
            "recent_progress": [
                row["progress_note"] for row in rows[-4:] if row.get("progress_note")
            ],
            "recent_blockers": [row["blockers"] for row in rows[-4:] if row.get("blockers")],
        }

    def _journal(self, target_date: date) -> dict[str, Any]:
        rows = self._rows(
            """
            SELECT date, text, tags_json, sentiment
            FROM journal_entries
            WHERE date BETWEEN ? AND ?
            ORDER BY date
            """,
            (_start(target_date, 7), target_date.isoformat()),
        )
        tags: dict[str, int] = {}
        for row in rows:
            for tag in _decode_tags(row.get("tags_json")):
                tags[tag] = tags.get(tag, 0) + 1
        return {
            "entries_7d": len(rows),
            "sentiment_7d_avg": _avg(row["sentiment"] for row in rows),
            "top_tags_7d": sorted(tags.items(), key=lambda item: (-item[1], item[0]))[:5],
            "recent_reflections": [row["text"] for row in rows[-3:]],
        }

    def _data_completeness(self, target_date: date) -> dict[str, Any]:
        categories = {
            "wellbeing_days": "daily_checkins",
            "nutrition_days": "nutrition_logs",
            "training_days": "workout_logs",
            "career_days": "career_logs",
            "journal_days": "journal_entries",
        }
        result = {}
        for key, table in categories.items():
            rows = self._rows(
                f"""
                SELECT COUNT(DISTINCT date) AS days
                FROM {table}
                WHERE date BETWEEN ? AND ?
                """,
                (_start(target_date, 7), target_date.isoformat()),
            )
            result[key] = rows[0]["days"] if rows else 0
        return result

    def _data_warnings(self, target_date: date) -> list[str]:
        warnings = []
        noisy_training = self._rows(
            """
            SELECT date, COUNT(*) AS sessions, SUM(duration_min) AS duration_min
            FROM workout_logs
            WHERE date BETWEEN ? AND ?
            GROUP BY date
            HAVING COUNT(*) > 3 OR SUM(duration_min) > 240
            ORDER BY date
            """,
            (_start(target_date, 7), target_date.isoformat()),
        )
        for row in noisy_training:
            warnings.append(
                "Training logs look noisy on "
                f"{row['date']}: {row['sessions']} workout rows and {row['duration_min']} total minutes. "
                "Treat this as duplicated or aggregate data, not one literal session."
            )
        return warnings

    def _rows(self, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()
            if not rows:
                return []
            if isinstance(rows[0], sqlite3.Row):
                return [dict(row) for row in rows]

            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in rows]


def is_briefing_request(text: str) -> bool:
    lower = " ".join(text.lower().strip().split())
    if lower in {
        "/brief",
        "/briefing",
        "brief",
        "briefing",
        "morning brief",
        "morning briefing",
        "today's brief",
        "todays brief",
        "daily brief",
    }:
        return True
    request_markers = (
        "morning brief",
        "morning briefing",
        "daily brief",
        "today's brief",
        "todays brief",
    )
    command_markers = ("send", "provide", "give", "show", "make", "generate")
    return any(marker in lower for marker in request_markers) and (
        lower.startswith(command_markers)
        or any(f" {marker}" in lower for marker in command_markers)
    )


def _deterministic_briefing(target_date: date, features: dict[str, Any]) -> str:
    wellbeing = features["wellbeing"]
    training = features["training"]
    nutrition = features["nutrition"]
    career = features["career"]
    completeness = features["data_completeness"]
    memory = features.get("personal_memory", {})

    sleep = wellbeing["sleep_7d_avg"]
    energy = wellbeing["energy_7d_avg"]
    stress = wellbeing["stress_7d_avg"]
    training_days = training["training_days_7d"]
    deep_work = career["deep_work_hours_7d"]
    protein = nutrition["protein_7d_avg"]

    today = _today_line(sleep, energy, stress, training_days)
    push = _push_line(energy, stress, deep_work, career["top_projects_7d"], memory)
    chill = _chill_line(sleep, stress, training_days, memory)
    watch = _watch_line(protein, completeness, memory)

    return "\n".join(
        [
            f"Morning brief for {target_date:%b %-d}",
            f"Today: {today}",
            f"Push: {push}",
            f"Chill: {chill}",
            f"Watch: {watch}",
        ]
    )


def _today_line(
    sleep: float | None, energy: float | None, stress: float | None, training_days: int
) -> str:
    if energy is None and stress is None and sleep is None:
        return "Not enough wellbeing data yet. Log sleep, energy, and stress today."
    if stress is not None and stress >= 7:
        return "Treat today as controlled output, not max output."
    if energy is not None and energy >= 7 and training_days <= 4:
        return "You have room to push, especially on focused work or training."
    if sleep is not None and sleep < 6.5:
        return "Keep the plan simple because sleep is running low."
    return "Use a steady moderate day and protect one meaningful focus block."


def _push_line(
    energy: float | None,
    stress: float | None,
    deep_work: float | None,
    projects: list[dict[str, Any]],
    memory: dict[str, list[dict[str, Any]]],
) -> str:
    project = projects[0]["project"] if projects else "your highest-value project"
    strategy = _memory_value(memory, "strategy")
    if deep_work is None or deep_work < 5:
        return f"Prioritize 60-90 minutes on {project}; career hours are light this week."
    if strategy:
        return f"Use what tends to work for you: {strategy}. Apply it to {project}."
    if energy is not None and energy >= 7 and (stress is None or stress <= 6):
        return f"Take a bigger swing on {project}; the recent trend supports it."
    return f"Move {project} forward with one clean, bounded work block."


def _chill_line(
    sleep: float | None,
    stress: float | None,
    training_days: int,
    memory: dict[str, list[dict[str, Any]]],
) -> str:
    anti_strategy = _memory_value(memory, "anti_strategy")
    aversion = _memory_value(memory, "aversion")
    if training_days >= 5:
        return "Avoid stacking another hard session unless recovery feels clearly good."
    if stress is not None and stress >= 7:
        return "Keep meetings, admin, and training intensity contained."
    if sleep is not None and sleep < 6.5:
        return "Cut optional friction and do the basics well."
    if anti_strategy:
        return f"Do not lean on what you said does not help: {anti_strategy}."
    if aversion:
        return f"Avoid adding friction around {aversion}."
    return "No need for a full deload; just do not turn every task into a test."


def _watch_line(
    protein: float | None,
    completeness: dict[str, Any],
    memory: dict[str, list[dict[str, Any]]],
) -> str:
    weak_logs = [name.removesuffix("_days") for name, count in completeness.items() if count < 3]
    reminder = _memory_value(memory, "reminder")
    goal = _memory_value(memory, "goal")
    if protein is None:
        return "Protein data is too sparse for advice; log portions if nutrition matters today."
    if protein < 100:
        return "Protein is trending low; make the first two meals easier to quantify."
    if reminder:
        return f"Remember: {reminder}."
    if goal:
        return f"Keep the broader goal visible: {goal}."
    if weak_logs:
        return f"Data is thin for {', '.join(weak_logs[:2])}; one quick log tonight will help tomorrow."
    return "The data is usable. Keep logging short but specific."


def _memory_value(memory: dict[str, list[dict[str, Any]]], category: str) -> str | None:
    items = memory.get(category) or []
    if not items:
        return None
    return str(items[0]["value"])


def _configured_briefing_client() -> OpenRouterBriefingClient | None:
    if not settings.openrouter_api_key:
        return None
    return OpenRouterBriefingClient(api_key=settings.openrouter_api_key)


def _decode_text(payload: dict[str, Any]) -> str:
    for choice in payload.get("choices", []):
        content = choice.get("message", {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    raise ValueError("Could not find briefing text in LLM response")


def _format_error(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return f"OpenRouter request exceeded {settings.llm_timeout_seconds:g}s timeout"
    message = str(error).strip()
    return message or error.__class__.__name__


def _avg(values) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 2)


def _sum(values) -> float:
    return round(sum(float(value) for value in values if value is not None), 2)


def _row_for_date(rows: list[dict[str, Any]], target_date: date) -> dict[str, Any] | None:
    iso_date = target_date.isoformat()
    for row in rows:
        if row.get("date") == iso_date:
            return row
    return None


def _decode_tags(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        tags = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [tag for tag in tags if isinstance(tag, str)]


def _start(target_date: date, days: int) -> str:
    return (target_date - timedelta(days=days - 1)).isoformat()


def _today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()
