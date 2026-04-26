from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from backend.app.db import LifeDatabase
from backend.app.llm_extraction import ExtractionService
from backend.app.telegram import TelegramService


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


class TelegramTests(IsolatedAsyncioTestCase):
    async def test_logs_allowed_text_message_and_sends_confirmation(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
                send_confirmations=True,
            )

            result = await service.handle_update(
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 10,
                        "date": 1777132800,
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "Ate eggs. Trained legs for 30 min. Energy 7.",
                    },
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "logged")
            self.assertEqual(result.extraction_method, "deterministic")
            self.assertEqual(client.sent[0][0], 456)
            self.assertIn("Logged #1", client.sent[0][1])
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_rejects_user_outside_allowlist(self) -> None:
        with TemporaryDirectory() as directory:
            service = TelegramService(
                db=LifeDatabase(Path(directory) / "life.sqlite3"),
                extractor=ExtractionService(mode="deterministic"),
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 999},
                        "chat": {"id": 456},
                        "text": "Ate eggs.",
                    }
                }
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "unauthorized_user")

    async def test_ignores_non_text_messages(self) -> None:
        with TemporaryDirectory() as directory:
            service = TelegramService(
                db=LifeDatabase(Path(directory) / "life.sqlite3"),
                extractor=ExtractionService(mode="deterministic"),
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "photo": [{"file_id": "abc"}],
                    }
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "ignored_non_text_message")

