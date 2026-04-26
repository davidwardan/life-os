from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

from backend.app.briefing import BriefingService, is_briefing_request
from backend.app.db import LifeDatabase
from backend.app.memory import MemoryService
from backend.app.schemas import (
    CareerEntry,
    ExerciseEntry,
    JournalEntry,
    MessageIn,
    NutritionEntry,
    ParsedDailyLog,
    WellbeingEntry,
    WorkoutEntry,
)


class BriefingTests(IsolatedAsyncioTestCase):
    async def test_generates_deterministic_briefing_from_features(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            _seed_briefing_data(db, date(2026, 4, 25))
            service = BriefingService(db)

            briefing = await service.generate(date(2026, 4, 25))

            self.assertEqual(briefing.method, "deterministic")
            self.assertIn("Morning brief", briefing.text)
            self.assertIn("Push:", briefing.text)
            self.assertEqual(briefing.features["training"]["training_days_7d"], 4)
            self.assertGreater(briefing.features["career"]["deep_work_hours_7d"], 0)
            self.assertIn("last_training_day", briefing.features["training"])

    async def test_briefing_uses_personal_memory(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            _seed_briefing_data(db, date(2026, 4, 25))
            memory = MemoryService(db)
            memory.learn_from_message("Training early works for me. I don't like vague motivational advice.")
            service = BriefingService(db, memory_service=memory)

            briefing = await service.generate(date(2026, 4, 25))

            self.assertIn("personal_memory", briefing.features)
            self.assertIn("strategy", briefing.features["personal_memory"])
            self.assertIn("training early", briefing.text)


class BriefingRequestTests(TestCase):
    def test_detects_briefing_requests(self) -> None:
        self.assertTrue(is_briefing_request("morning brief"))
        self.assertTrue(is_briefing_request("/brief"))
        self.assertFalse(is_briefing_request("briefly worked on the paper"))


def _seed_briefing_data(db: LifeDatabase, end_date: date) -> None:
    for offset in range(7):
        entry_date = end_date - timedelta(days=6 - offset)
        parsed = ParsedDailyLog(
            date=entry_date,
            wellbeing=WellbeingEntry(
                sleep_hours=6 + (offset % 3),
                energy=5 + (offset % 4),
                stress=7 - (offset % 3),
                mood=6,
                notes="Felt steady.",
                confidence=1,
            ),
            nutrition=[
                NutritionEntry(
                    meal_type="lunch",
                    description="chicken rice bowl",
                    calories=700,
                    protein_g=35 + offset,
                    confidence=1,
                )
            ],
            workout=(
                WorkoutEntry(
                    workout_type="strength",
                    duration_min=45,
                    exercises=[ExerciseEntry(name="squat", sets=4, reps=5)],
                    confidence=1,
                )
                if offset in {0, 2, 4, 6}
                else None
            ),
            career=[
                CareerEntry(
                    project="Life OS",
                    activity="deep work",
                    duration_hours=1 + offset,
                    progress_note="Moved phase 5 forward.",
                    confidence=1,
                )
            ],
            journal=JournalEntry(text="Focused but tired.", tags=["focus", "fatigue"]),
        )
        db.save_message(MessageIn(text=f"seed {offset}", entry_date=entry_date, source="api"), parsed)
