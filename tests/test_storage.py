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
            self.assertEqual(len(logs["daily_checkins"]), 1)
            self.assertEqual(len(logs["career"]), 1)
            self.assertTrue(logs["raw_messages"][0]["processed"])

    def test_saves_complex_log_as_normalized_rows(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text=(
                    "Today I slept 6h, woke up tired, energy 5/10 and stress 7/10. "
                    "Ate oatmeal with dates, peanut butter, and chocolate in the morning. "
                    "Lunch was 180g cooked chicken with rice and salad. "
                    "Did lower body: squats 4x5 at 80%, RDL 3x8, and 12 min metcon. "
                    "Worked 3 hours on the global TAGI-LSTM paper and fixed the SKF motivation section. "
                    "Mood was okay but I felt mentally drained."
                ),
                entry_date=date(2026, 4, 25),
                source="telegram",
            )
            parsed = extract_daily_log(message.text, message.entry_date)

            db.save_message(message, parsed)
            logs = db.recent_logs()

            self.assertEqual(len(logs["raw_messages"]), 1)
            self.assertEqual(logs["raw_messages"][0]["source"], "telegram")
            self.assertEqual(len(logs["daily_checkins"]), 1)
            self.assertEqual(len(logs["nutrition"]), 2)
            self.assertEqual(len(logs["workout"]), 1)
            self.assertEqual(len(logs["workout_exercises"]), 3)
            self.assertEqual(len(logs["career"]), 1)
            self.assertEqual(len(logs["journal"]), 1)

    def test_does_not_store_empty_daily_checkin(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text="Had a tough day. Dinner was chicken and fries.",
                entry_date=date(2026, 4, 25),
                source="telegram",
            )
            parsed = extract_daily_log(message.text, message.entry_date)

            db.save_message(message, parsed)
            logs = db.recent_logs()

            self.assertEqual(len(logs["daily_checkins"]), 0)
            self.assertEqual(len(logs["nutrition"]), 1)
