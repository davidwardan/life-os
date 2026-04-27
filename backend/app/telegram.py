from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from backend.app.briefing import BriefingService
from backend.app.config import settings
from backend.app.db import LifeDatabase
from backend.app.llm_extraction import ExtractionService
from backend.app.memory import MemoryService
from backend.app.plotting import PlotService
from backend.app.workflow import AgentWorkflow


class TelegramClient(Protocol):
    async def send_message(self, chat_id: int, text: str) -> None:
        ...

    async def send_photo(self, chat_id: int, photo_path: str, caption: str) -> None:
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

    async def send_photo(self, chat_id: int, photo_path: str, caption: str) -> None:
        async with httpx.AsyncClient(timeout=20) as client:
            with open(photo_path, "rb") as photo:
                response = await client.post(
                    f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption},
                    files={"photo": photo},
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
    plot_path: str | None = None
    plot_paths: tuple[str, ...] = ()
    briefing_method: str | None = None
    briefing_error: str | None = None
    deleted_log: dict[str, Any] | None = None


class TelegramService:
    def __init__(
        self,
        db: LifeDatabase,
        extractor: ExtractionService,
        plotter: PlotService | None = None,
        briefing_service: BriefingService | None = None,
        memory_service: MemoryService | None = None,
        workflow: AgentWorkflow | None = None,
        client: TelegramClient | None = None,
        allowed_user_ids: frozenset[int] = settings.telegram_allowed_user_ids,
        send_confirmations: bool = settings.telegram_send_confirmations,
    ):
        self.db = db
        self.extractor = extractor
        self.plotter = plotter or PlotService(db)
        self.memory_service = memory_service or MemoryService(db)
        self.briefing_service = briefing_service or BriefingService(db, memory_service=self.memory_service)
        self.workflow = workflow or AgentWorkflow(
            db=db,
            extractor=extractor,
            plotter=self.plotter,
            memory_service=self.memory_service,
            briefing_service=self.briefing_service,
        )
        self.client = client
        self.allowed_user_ids = allowed_user_ids
        self.send_confirmations = send_confirmations

    async def handle_update(self, update: dict[str, Any]) -> TelegramResult:
        update_id = update.get("update_id")
        if isinstance(update_id, int) and not self._reserve_update(update_id):
            return TelegramResult(ok=True, status="ignored_duplicate_update")

        result_status = "processing"
        try:
            result = await self._handle_reserved_update(update)
            result_status = result.status
            return result
        finally:
            if isinstance(update_id, int):
                self._finish_update(update_id, result_status)

    async def _handle_reserved_update(self, update: dict[str, Any]) -> TelegramResult:
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

        entry_date = _telegram_entry_date(message.get("date"))
        result = await self.workflow.process_text(text, source="telegram", entry_date=entry_date)
        if self.client and self.send_confirmations:
            for plot in result.plot_results:
                await self.client.send_photo(
                    chat_id,
                    str(plot.path),
                    f"{plot.title} ({plot.detail})",
                )
            if result.confirmation and (not result.plot_results or len(result.plot_results) > 1):
                await self.client.send_message(chat_id, result.confirmation)

        return TelegramResult(
            ok=result.ok,
            status=result.status,
            raw_message_id=result.raw_message_id,
            confirmation=result.confirmation,
            extraction_method=result.extraction_method,
            extraction_error=result.extraction_error,
            plot_path=str(result.plot_results[0].path) if result.plot_results else None,
            plot_paths=tuple(str(plot.path) for plot in result.plot_results),
            briefing_method=result.briefing.method if result.briefing else None,
            briefing_error=result.briefing.error if result.briefing else None,
            deleted_log=result.deletion.deleted if result.deletion else None,
        )

    def _reserve_update(self, update_id: int) -> bool:
        now = _now()
        try:
            with self.db.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO telegram_updates (update_id, status, created_at, updated_at)
                    VALUES (?, 'processing', ?, ?)
                    """,
                    (update_id, now, now),
                )
            return True
        except Exception as error:
            if _is_unique_error(error):
                return False
            raise

    def _finish_update(self, update_id: int, status: str) -> None:
        now = _now()
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE telegram_updates
                SET status = ?, updated_at = ?
                WHERE update_id = ?
                """,
                (status, now, update_id),
            )


def make_telegram_service(db: LifeDatabase, extractor: ExtractionService) -> TelegramService:
    client = TelegramBotClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
    return TelegramService(
        db=db,
        extractor=extractor,
        plotter=PlotService(db),
        memory_service=MemoryService(db),
        client=client,
    )


def verify_telegram_secret(header_value: str | None) -> bool:
    if not settings.telegram_webhook_secret:
        return True
    return header_value == settings.telegram_webhook_secret


def _telegram_entry_date(timestamp: Any):
    if not isinstance(timestamp, int):
        return None
    return datetime.fromtimestamp(timestamp, ZoneInfo(settings.timezone)).date()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_error(error: Exception) -> bool:
    message = str(error).lower()
    return isinstance(error, sqlite3.IntegrityError) or "unique" in message or "constraint" in message
