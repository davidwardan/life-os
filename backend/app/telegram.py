from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from backend.app.config import settings
from backend.app.db import LifeDatabase
from backend.app.extraction import is_non_logging_reply
from backend.app.llm_extraction import ExtractionService
from backend.app.schemas import MessageIn


class TelegramClient(Protocol):
    async def send_message(self, chat_id: int, text: str) -> None:
        ...


class TelegramBotClient:
    def __init__(self, token: str):
        self.token = token

    async def send_message(self, chat_id: int, text: str) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()


@dataclass(frozen=True)
class TelegramResult:
    ok: bool
    status: str
    raw_message_id: int | None = None
    confirmation: str | None = None
    extraction_method: str | None = None
    extraction_error: str | None = None


class TelegramService:
    def __init__(
        self,
        db: LifeDatabase,
        extractor: ExtractionService,
        client: TelegramClient | None = None,
        allowed_user_ids: frozenset[int] = settings.telegram_allowed_user_ids,
        send_confirmations: bool = settings.telegram_send_confirmations,
    ):
        self.db = db
        self.extractor = extractor
        self.client = client
        self.allowed_user_ids = allowed_user_ids
        self.send_confirmations = send_confirmations

    async def handle_update(self, update: dict[str, Any]) -> TelegramResult:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return TelegramResult(ok=True, status="ignored_non_message_update")

        user = message.get("from") or {}
        user_id = user.get("id")
        if not isinstance(user_id, int):
            return TelegramResult(ok=False, status="missing_user_id")

        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            return TelegramResult(ok=False, status="unauthorized_user")

        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            return TelegramResult(ok=True, status="ignored_non_text_message")

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return TelegramResult(ok=False, status="missing_chat_id")

        if is_non_logging_reply(text):
            confirmation = "No problem. I will leave that log as-is."
            if self.client and self.send_confirmations:
                await self.client.send_message(chat_id, confirmation)
            return TelegramResult(ok=True, status="ignored_non_logging_reply", confirmation=confirmation)

        entry_date = _telegram_entry_date(message.get("date"))
        parsed, method, error = await self.extractor.extract(text, entry_date)
        saved = self.db.save_message(MessageIn(text=text, entry_date=entry_date, source="telegram"), parsed)
        confirmation = _confirmation(saved["raw_message_id"], parsed, method, error)

        if self.client and self.send_confirmations:
            await self.client.send_message(chat_id, confirmation)

        return TelegramResult(
            ok=True,
            status="logged",
            raw_message_id=saved["raw_message_id"],
            confirmation=confirmation,
            extraction_method=method,
            extraction_error=error,
        )


def make_telegram_service(db: LifeDatabase, extractor: ExtractionService) -> TelegramService:
    client = TelegramBotClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
    return TelegramService(db=db, extractor=extractor, client=client)


def verify_telegram_secret(header_value: str | None) -> bool:
    if not settings.telegram_webhook_secret:
        return True
    return header_value == settings.telegram_webhook_secret


def _telegram_entry_date(timestamp: Any):
    if not isinstance(timestamp, int):
        return None
    return datetime.fromtimestamp(timestamp, ZoneInfo(settings.timezone)).date()


def _confirmation(raw_message_id: int, parsed, method: str, error: str | None) -> str:
    lines = [f"Logged #{raw_message_id} for {parsed.date:%b %-d} via {method}."]
    if parsed.wellbeing:
        wellbeing = []
        if parsed.wellbeing.sleep_hours is not None:
            wellbeing.append(f"sleep {parsed.wellbeing.sleep_hours:g}h")
        if parsed.wellbeing.energy is not None:
            wellbeing.append(f"energy {parsed.wellbeing.energy}/10")
        if parsed.wellbeing.stress is not None:
            wellbeing.append(f"stress {parsed.wellbeing.stress}/10")
        if parsed.wellbeing.mood is not None:
            wellbeing.append(f"mood {parsed.wellbeing.mood}/10")
        if wellbeing:
            lines.append("Wellbeing: " + ", ".join(wellbeing))
        if parsed.wellbeing.notes:
            lines.append(f"Note: {parsed.wellbeing.notes}")

    if parsed.nutrition:
        lines.append("Nutrition:")
        for item in parsed.nutrition[:4]:
            meal = f"{item.meal_type}: " if item.meal_type else ""
            macro_bits = []
            if item.calories is not None:
                macro_bits.append(f"{item.calories:g} cal")
            if item.protein_g is not None:
                marker = "~" if item.estimated else ""
                macro_bits.append(f"{marker}{item.protein_g:g}g protein")
            suffix = f" ({', '.join(macro_bits)})" if macro_bits else ""
            lines.append(f"- {meal}{item.description}{suffix}")

    if parsed.workout:
        workout = parsed.workout.workout_type or "workout"
        duration = f", {parsed.workout.duration_min:g} min" if parsed.workout.duration_min else ""
        lines.append(f"Workout: {workout}{duration}")
        for exercise in parsed.workout.exercises[:5]:
            if exercise.sets and exercise.reps:
                load = f" at {exercise.load}" if exercise.load else ""
                lines.append(f"- {exercise.name}: {exercise.sets}x{exercise.reps}{load}")
            elif exercise.duration_min:
                lines.append(f"- {exercise.name}: {exercise.duration_min:g} min")

    if parsed.career:
        lines.append("Career:")
        for item in parsed.career[:3]:
            duration = f"{item.duration_hours:g}h " if item.duration_hours is not None else ""
            project = item.project or "work"
            progress = f" - {item.progress_note}" if item.progress_note else ""
            lines.append(f"- {duration}on {project}{progress}")

    if parsed.journal:
        tag_text = f" [{', '.join(parsed.journal.tags)}]" if parsed.journal.tags else ""
        lines.append(f"Journal: saved{tag_text}")

    if parsed.clarification_questions:
        label = "Question" if len(parsed.clarification_questions) == 1 else "Questions"
        lines.append(label + ":")
        for question in parsed.clarification_questions[:2]:
            lines.append(f"- {question}")
    if error:
        lines.append(f"Fallback note: {error}")
    return "\n".join(lines)
