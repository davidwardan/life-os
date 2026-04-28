from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import sqlite3
import tempfile
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

logger = logging.getLogger(__name__)


class TelegramClient(Protocol):
    async def send_message(self, chat_id: int, text: str) -> None: ...

    async def send_photo(self, chat_id: int, photo_path: str, caption: str) -> None: ...

    async def get_file(self, file_id: str) -> dict[str, Any]: ...

    async def download_file(self, file_path: str) -> bytes: ...


class VoiceTranscriber(Protocol):
    async def transcribe(self, *, audio: bytes, filename: str, mime_type: str) -> str: ...


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
                    data={
                        "chat_id": chat_id,
                        "caption": caption,
                    },
                    files={"photo": photo},
                )
            response.raise_for_status()

    async def get_file(self, file_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{self.token}/getFile",
                json={"file_id": file_id},
            )
            response.raise_for_status()
            payload = response.json()
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("Telegram getFile response did not include a result")
        return result

    async def download_file(self, file_path: str) -> bytes:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            )
            response.raise_for_status()
            return response.content


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
    transcript: str | None = None


class OpenAICompatibleVoiceTranscriber:
    def __init__(
        self,
        api_key: str,
        model: str = settings.voice_transcription_model,
        base_url: str = settings.voice_transcription_base_url,
        timeout_seconds: float = settings.llm_timeout_seconds,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def transcribe(self, *, audio: bytes, filename: str, mime_type: str) -> str:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data={"model": self.model},
                files={"file": (filename, audio, mime_type)},
            )
            response.raise_for_status()
            payload = response.json()

        text = payload.get("text")
        if not isinstance(text, str):
            raise ValueError("Transcription response did not include text")
        return text.strip()


class FasterWhisperVoiceTranscriber:
    def __init__(
        self,
        model: str = settings.voice_transcription_model,
        device: str = settings.voice_transcription_device,
        compute_type: str = settings.voice_transcription_compute_type,
    ):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model: Any | None = None

    async def transcribe(self, *, audio: bytes, filename: str, mime_type: str) -> str:
        return await asyncio.to_thread(self._transcribe_sync, audio, filename, mime_type)

    def _transcribe_sync(self, audio: bytes, filename: str, _mime_type: str) -> str:
        suffix = _voice_suffix(filename)
        with tempfile.NamedTemporaryFile(suffix=suffix) as audio_file:
            audio_file.write(audio)
            audio_file.flush()
            segments, _info = self._load_model().transcribe(
                audio_file.name,
                vad_filter=True,
            )
            return " ".join(segment.text.strip() for segment in segments).strip()

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise RuntimeError(
                    "faster-whisper is not installed. Install project dependencies first."
                ) from error
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model


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
        voice_transcriber: VoiceTranscriber | None = None,
        allowed_user_ids: frozenset[int] = settings.telegram_allowed_user_ids,
        send_confirmations: bool = settings.telegram_send_confirmations,
        voice_notes_enabled: bool = settings.telegram_voice_notes_enabled,
        voice_max_bytes: int = settings.telegram_voice_max_bytes,
    ):
        self.db = db
        self.extractor = extractor
        self.plotter = plotter or PlotService(db)
        self.memory_service = memory_service or MemoryService(db)
        self.briefing_service = briefing_service or BriefingService(
            db, memory_service=self.memory_service
        )
        self.workflow = workflow or AgentWorkflow(
            db=db,
            extractor=extractor,
            plotter=self.plotter,
            memory_service=self.memory_service,
            briefing_service=self.briefing_service,
        )
        self.client = client
        self.voice_transcriber = voice_transcriber
        self.allowed_user_ids = allowed_user_ids
        self.send_confirmations = send_confirmations
        self.voice_notes_enabled = voice_notes_enabled
        self.voice_max_bytes = voice_max_bytes

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

        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return TelegramResult(ok=False, status="missing_chat_id")

        transcript: str | None = None
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            voice_result = await self._voice_text(message, chat_id)
            if voice_result.status:
                return TelegramResult(ok=voice_result.ok, status=voice_result.status)
            text = voice_result.text
            transcript = voice_result.text

        entry_date = _telegram_entry_date(message.get("date"))
        result = await self.workflow.process_text(text, source="telegram", entry_date=entry_date)
        if self.client and self.send_confirmations:
            for plot in result.plot_results:
                caption = f"{plot.title} ({plot.detail})"
                await self.client.send_photo(
                    chat_id,
                    str(plot.path),
                    _telegram_plain_text(caption),
                )
            if result.confirmation and (not result.plot_results or len(result.plot_results) > 1):
                await self.client.send_message(chat_id, _telegram_plain_text(result.confirmation))

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
            transcript=transcript,
        )

    async def _voice_text(self, message: dict[str, Any], chat_id: int) -> "_VoiceTextResult":
        voice = message.get("voice")
        if not isinstance(voice, dict):
            return _VoiceTextResult(ok=True, status="ignored_non_text_message")

        if not self.voice_notes_enabled or self.voice_transcriber is None or self.client is None:
            if self.client and self.send_confirmations:
                await self.client.send_message(
                    chat_id,
                    "Voice notes are not configured yet. Send this as text for now.",
                )
            return _VoiceTextResult(ok=False, status="voice_notes_not_configured")

        file_id = voice.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            return _VoiceTextResult(ok=False, status="missing_voice_file_id")

        file_size = voice.get("file_size")
        if isinstance(file_size, int) and file_size > self.voice_max_bytes:
            if self.client and self.send_confirmations:
                await self.client.send_message(
                    chat_id,
                    "That voice note is too large to transcribe. Send a shorter note or type it.",
                )
            return _VoiceTextResult(ok=False, status="voice_note_too_large")

        try:
            file_info = await self.client.get_file(file_id)
            file_path = file_info.get("file_path")
            if not isinstance(file_path, str) or not file_path:
                return _VoiceTextResult(ok=False, status="missing_voice_file_path")

            audio = await self.client.download_file(file_path)
            if len(audio) > self.voice_max_bytes:
                if self.client and self.send_confirmations:
                    await self.client.send_message(
                        chat_id,
                        "That voice note is too large to transcribe. Send a shorter note or type it.",
                    )
                return _VoiceTextResult(ok=False, status="voice_note_too_large")

            text = await self.voice_transcriber.transcribe(
                audio=audio,
                filename=_voice_filename(file_path),
                mime_type=str(voice.get("mime_type") or "audio/ogg"),
            )
        except Exception as error:
            logger.warning("Telegram voice note transcription failed: %s", error)
            if self.client and self.send_confirmations:
                await self.client.send_message(
                    chat_id,
                    "I could not transcribe that voice note. Send it as text for now.",
                )
            return _VoiceTextResult(ok=False, status="voice_transcription_failed")

        if not text:
            if self.client and self.send_confirmations:
                await self.client.send_message(
                    chat_id,
                    "I could not hear any text in that voice note.",
                )
            return _VoiceTextResult(ok=False, status="voice_transcription_empty")

        return _VoiceTextResult(ok=True, text=text)

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
        try:
            with self.db.connect() as connection:
                connection.execute(
                    """
                    UPDATE telegram_updates
                    SET status = ?, updated_at = ?
                    WHERE update_id = ?
                    """,
                    (status, now, update_id),
                )
        except Exception:
            logger.exception("Failed to finalize telegram update %s", update_id)


def make_telegram_service(db: LifeDatabase, extractor: ExtractionService) -> TelegramService:
    client = TelegramBotClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
    voice_transcriber = _make_voice_transcriber()
    return TelegramService(
        db=db,
        extractor=extractor,
        plotter=PlotService(db),
        memory_service=MemoryService(db),
        client=client,
        voice_transcriber=voice_transcriber,
    )


def _make_voice_transcriber() -> VoiceTranscriber | None:
    if not settings.telegram_voice_notes_enabled:
        return None

    backend = settings.voice_transcription_backend
    if backend in {"faster-whisper", "faster_whisper", "local"}:
        return FasterWhisperVoiceTranscriber()

    if backend in {"api", "openai", "openai-compatible", "openai_compatible"}:
        if not settings.voice_transcription_api_key:
            return None
        return OpenAICompatibleVoiceTranscriber(settings.voice_transcription_api_key)

    logger.warning("Unknown Telegram voice transcription backend: %s", backend)
    return None


def verify_telegram_secret(header_value: str | None) -> bool:
    if not settings.telegram_webhook_secret:
        return True
    return header_value == settings.telegram_webhook_secret


def _telegram_entry_date(timestamp: Any):
    if not isinstance(timestamp, int):
        return None
    return datetime.fromtimestamp(timestamp, ZoneInfo(settings.timezone)).date()


def _telegram_plain_text(text: str) -> str:
    for char in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(f"\\{char}", char)
    text = re.sub(r"\*([^*\n]+)\*", r"\1", text)
    text = re.sub(r"_([^_\n]+)_", r"\1", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return text


@dataclass(frozen=True)
class _VoiceTextResult:
    ok: bool
    text: str | None = None
    status: str | None = None


def _voice_filename(file_path: str) -> str:
    filename = file_path.rsplit("/", 1)[-1].strip()
    return filename or "telegram-voice.ogg"


def _voice_suffix(filename: str) -> str:
    basename = _voice_filename(filename)
    if "." not in basename:
        return ".ogg"
    suffix = "." + basename.rsplit(".", 1)[-1].strip().lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return ".ogg"
    return suffix


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_unique_error(error: Exception) -> bool:
    message = str(error).lower()
    return (
        isinstance(error, sqlite3.IntegrityError) or "unique" in message or "constraint" in message
    )
