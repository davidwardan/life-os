from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from backend.app.db import LifeDatabase
from backend.app.extraction import extract_daily_log
from backend.app.llm_extraction import ExtractionService
from backend.app.schemas import MessageIn
from backend.app.telegram import TelegramBotClient, TelegramService


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.photos: list[tuple[int, str, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id: int, photo_path: str, caption: str) -> None:
        self.photos.append((chat_id, photo_path, caption))


class FakeHttpResponse:
    def raise_for_status(self) -> None:
        return None


class FakeHttpClient:
    sent_json: dict[str, object] | None = None

    def __init__(self, timeout: int) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "FakeHttpClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, _url: str, json: dict[str, object]) -> FakeHttpResponse:
        self.__class__.sent_json = json
        return FakeHttpResponse()


class TelegramTests(IsolatedAsyncioTestCase):
    async def test_bot_client_sends_plain_text_messages(self) -> None:
        FakeHttpClient.sent_json = None

        with patch("backend.app.telegram.httpx.AsyncClient", FakeHttpClient):
            await TelegramBotClient("token").send_message(456, "Logged Apr 25 as #1.")

        self.assertIsNotNone(FakeHttpClient.sent_json)
        self.assertEqual(FakeHttpClient.sent_json["text"], "Logged Apr 25 as #1.")
        self.assertNotIn("parse_mode", FakeHttpClient.sent_json)

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
            self.assertIn("Logged Apr", client.sent[0][1])
            self.assertIn("as #1", client.sent[0][1])
            self.assertNotIn("\\#", client.sent[0][1])
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_confirmation_includes_bounded_followup_for_vague_log(self) -> None:
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

            await service.handle_update(
                {
                    "message": {
                        "date": 1777132800,
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": (
                            "Had a tough day but still did a good workout for 90mins at the gym. "
                            "I did legs and upper body. Dinner was chicken and fries."
                        ),
                    }
                }
            )

            confirmation = client.sent[0][1]
            self.assertIn("Questions:", confirmation)
            self.assertIn("main exercises", confirmation)
            self.assertIn("energy", confirmation.lower())

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

    async def test_ignores_non_logging_refusal_reply(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "i do not want to give more info",
                    }
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "ignored_non_logging_reply")
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 0)
            self.assertIn("left the log unchanged", client.sent[0][1])

    async def test_plot_request_sends_photo_without_logging_message(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            db.save_message(
                MessageIn(
                    text="Energy 7, stress 4.",
                    entry_date=date(2026, 4, 25),
                    source="telegram",
                ),
                extract_daily_log("Energy 7, stress 4.", date(2026, 4, 25)),
            )
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "plot my energy",
                    }
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "plot_sent")
            self.assertEqual(client.photos[0][0], 456)
            self.assertTrue(Path(client.photos[0][1]).exists())
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_multiple_plot_requests_send_multiple_photos_without_logging_message(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            db.save_message(
                MessageIn(
                    text=(
                        "Energy 7, stress 4. Trained legs for 45 min. "
                        "Worked 2 hours on the paper. Ate chicken with 40g protein."
                    ),
                    entry_date=date(2026, 4, 25),
                    source="telegram",
                ),
                extract_daily_log(
                    (
                        "Energy 7, stress 4. Trained legs for 45 min. "
                        "Worked 2 hours on the paper. Ate chicken with 40g protein."
                    ),
                    date(2026, 4, 25),
                ),
            )
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "\n".join(
                            [
                                "plot my energy",
                                "show my career hours",
                                "plot my workouts",
                                "plot protein for the last week",
                            ]
                        ),
                    }
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "plot_sent")
            self.assertEqual(len(client.photos), 4)
            self.assertEqual(len(result.plot_paths), 4)
            self.assertIn("Energy and stress", client.photos[0][2])
            self.assertIn("Career hours", client.photos[1][2])
            self.assertIn("Workout duration", client.photos[2][2])
            self.assertIn("Protein", client.photos[3][2])
            self.assertEqual(client.sent[0], (456, "I made 4 plots."))
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_briefing_request_sends_briefing_without_logging_message(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            db.save_message(
                MessageIn(
                    text="Energy 7, stress 4. Worked 2h on Life OS.",
                    entry_date=date(2026, 4, 25),
                    source="telegram",
                ),
                extract_daily_log("Energy 7, stress 4. Worked 2h on Life OS.", date(2026, 4, 25)),
            )
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "date": 1777132800,
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "morning brief",
                    }
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "briefing_sent")
            self.assertEqual(result.briefing_method, "deterministic")
            self.assertIn("Morning brief", client.sent[0][1])
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_duplicate_update_id_is_ignored_without_resending(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )
            update = {
                "update_id": 999,
                "message": {
                    "date": 1777132800,
                    "from": {"id": 123},
                    "chat": {"id": 456},
                    "text": "morning brief",
                },
            }

            first = await service.handle_update(update)
            second = await service.handle_update(update)

            self.assertEqual(first.status, "briefing_sent")
            self.assertEqual(second.status, "ignored_duplicate_update")
            self.assertEqual(len(client.sent), 1)

    async def test_memory_request_updates_memory_without_logging_message(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "remember that briefings should be direct and concise",
                    }
                }
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "memory_updated")
            self.assertIn("I will remember", client.sent[0][1])
            self.assertNotIn("*I will remember", client.sent[0][1])
            self.assertNotIn("\\", client.sent[0][1])
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 0)

    async def test_delete_request_lists_recent_logs_without_logging_message(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            db.save_message(
                MessageIn(
                    text="Dinner was chicken and fries.",
                    entry_date=date(2026, 4, 25),
                    source="telegram",
                ),
                extract_daily_log("Dinner was chicken and fries.", date(2026, 4, 25)),
            )
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "delete logs",
                    }
                }
            )

            self.assertEqual(result.status, "delete_options_sent")
            self.assertIn("Recent deletable logs", client.sent[0][1])
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_delete_request_deletes_by_kind_and_id_without_logging_message(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            db.save_message(
                MessageIn(
                    text="Dinner was chicken and fries.",
                    entry_date=date(2026, 4, 25),
                    source="telegram",
                ),
                extract_daily_log("Dinner was chicken and fries.", date(2026, 4, 25)),
            )
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "delete meal #1",
                    }
                }
            )

            self.assertEqual(result.status, "deleted")
            self.assertIn("Deleted nutrition", client.sent[0][1])
            self.assertEqual(len(db.recent_logs()["nutrition"]), 0)
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_delete_last_log_cascades_raw_message_records(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            db.save_message(
                MessageIn(
                    text="Ate eggs. I did squats 3 sets of 10 reps 100 kg.",
                    entry_date=date(2026, 4, 25),
                    source="telegram",
                ),
                extract_daily_log(
                    "Ate eggs. I did squats 3 sets of 10 reps 100 kg.",
                    date(2026, 4, 25),
                ),
            )
            client = FakeTelegramClient()
            service = TelegramService(
                db=db,
                extractor=ExtractionService(mode="deterministic"),
                client=client,
                allowed_user_ids=frozenset({123}),
            )

            result = await service.handle_update(
                {
                    "message": {
                        "from": {"id": 123},
                        "chat": {"id": 456},
                        "text": "delete last log",
                    }
                }
            )

            self.assertEqual(result.status, "deleted")
            self.assertIn("Deleted raw messages", client.sent[0][1])
            logs = db.recent_logs()
            self.assertEqual(len(logs["raw_messages"]), 0)
            self.assertEqual(len(logs["nutrition"]), 0)
            self.assertEqual(len(logs["workout"]), 0)
            self.assertEqual(len(logs["workout_exercises"]), 0)
