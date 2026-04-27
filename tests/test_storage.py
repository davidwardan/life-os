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

    def test_fills_missing_exercise_fields_from_recent_matching_workout(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            first = MessageIn(
                text="I did squats 3 sets of 10 reps 100 kg.",
                entry_date=date(2026, 4, 24),
                source="telegram",
            )
            db.save_message(first, extract_daily_log(first.text, first.entry_date))
            second = MessageIn(
                text="I did squats.",
                entry_date=date(2026, 4, 25),
                source="telegram",
            )

            db.save_message(second, extract_daily_log(second.text, second.entry_date))
            logs = db.recent_logs()

            latest_squat = logs["workout_exercises"][0]
            self.assertEqual(latest_squat["name"], "squat")
            self.assertEqual(latest_squat["sets"], 3)
            self.assertEqual(latest_squat["reps"], 10)
            self.assertEqual(latest_squat["load"], "100 kg")

    def test_skips_duplicate_same_day_structured_workout(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text="I did squats 3 sets of 10 reps 100 kg.",
                entry_date=date(2026, 4, 25),
                source="telegram",
            )

            db.save_message(message, extract_daily_log(message.text, message.entry_date))
            second = db.save_message(message, extract_daily_log(message.text, message.entry_date))
            logs = db.recent_logs()

            self.assertEqual(len(logs["raw_messages"]), 2)
            self.assertEqual(second["records"]["workout"], [])
            self.assertEqual(second["records"]["workout_exercises"], [])
            self.assertEqual(len(logs["workout_exercises"]), 1)

    def test_skips_duplicate_same_day_nutrition(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text="Dinner was chicken and fries.",
                entry_date=date(2026, 4, 25),
                source="telegram",
            )

            db.save_message(message, extract_daily_log(message.text, message.entry_date))
            second = db.save_message(message, extract_daily_log(message.text, message.entry_date))
            logs = db.recent_logs()

            self.assertEqual(second["records"]["nutrition"], [])
            self.assertEqual(len(logs["nutrition"]), 1)

    def test_deletes_single_structured_log(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text="Dinner was chicken and fries.",
                entry_date=date(2026, 4, 25),
                source="telegram",
            )
            db.save_message(message, extract_daily_log(message.text, message.entry_date))

            deleted = db.delete_log("nutrition", 1)
            logs = db.recent_logs()

            self.assertTrue(deleted["deleted"])
            self.assertEqual(deleted["kind"], "nutrition")
            self.assertEqual(len(logs["nutrition"]), 0)
            self.assertEqual(len(logs["raw_messages"]), 1)

    def test_deletes_raw_log_and_associated_records(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text="Ate eggs. I did squats 3 sets of 10 reps 100 kg. Energy 7.",
                entry_date=date(2026, 4, 25),
                source="telegram",
            )
            db.save_message(message, extract_daily_log(message.text, message.entry_date))

            deleted = db.delete_log("log", 1)
            logs = db.recent_logs()

            self.assertTrue(deleted["deleted"])
            self.assertEqual(len(logs["raw_messages"]), 0)
            self.assertEqual(len(logs["nutrition"]), 0)
            self.assertEqual(len(logs["workout"]), 0)
            self.assertEqual(len(logs["workout_exercises"]), 0)
            self.assertEqual(len(logs["daily_checkins"]), 0)

    def test_lists_deletable_logs(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text="Worked 2h on Life OS.",
                entry_date=date(2026, 4, 25),
                source="web",
            )
            db.save_message(message, extract_daily_log(message.text, message.entry_date))

            candidates = db.deletable_logs(limit=5)

            self.assertTrue(any(item["kind"] == "raw_messages" for item in candidates))
            self.assertTrue(any(item["kind"] == "career" for item in candidates))
            self.assertTrue(all("summary" in item for item in candidates))

    def test_saves_running_distance_and_pace(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            message = MessageIn(
                text="i ran for 5km with a pace of 5.5",
                entry_date=date(2026, 4, 27),
                source="telegram",
            )

            db.save_message(message, extract_daily_log(message.text, message.entry_date))
            workout = db.recent_logs()["workout"][0]

            self.assertEqual(workout["workout_type"], "running")
            self.assertEqual(workout["distance_km"], 5)
            self.assertEqual(workout["pace"], 5.5)
