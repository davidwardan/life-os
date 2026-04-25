from datetime import date
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase

from backend.app.db import LifeDatabase
from backend.app.extraction import extract_daily_log
from backend.app.schemas import MessageIn


class StorageTests(TestCase):
    def test_saves_raw_and_structured_records(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text="Ate eggs. Trained legs for 30 min. Mood 8. Worked 1.5h on thesis.",
                entry_date=date(2026, 4, 25),
                source="web",
            )
            parsed = extract_daily_log(message.text, message.entry_date)

            saved = db.save_message(message, parsed)
            logs = db.recent_logs()

            self.assertEqual(saved["raw_message_id"], 1)
            self.assertEqual(len(logs["raw_messages"]), 1)
            self.assertGreaterEqual(len(logs["nutrition"]), 1)
            self.assertEqual(len(logs["workout"]), 1)
            self.assertEqual(len(logs["wellbeing"]), 1)
            self.assertEqual(len(logs["career"]), 1)

