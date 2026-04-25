from datetime import date
from unittest import TestCase

from backend.app.extraction import extract_daily_log


class ExtractionTests(TestCase):
    def test_extracts_mixed_daily_log(self) -> None:
        parsed = extract_daily_log(
            "Ate oatmeal and chicken rice. Trained upper body for 45 min. "
            "Energy 7, stress 4. Worked 2h on global LSTM paper and fixed SKF section.",
            date(2026, 4, 25),
        )

        self.assertEqual(parsed.entry_date.isoformat(), "2026-04-25")
        self.assertGreaterEqual(len(parsed.nutrition), 1)
        self.assertEqual(parsed.workout.workout_type, "upper body")
        self.assertEqual(parsed.workout.duration_min, 45)
        self.assertEqual(parsed.wellbeing.energy, 7)
        self.assertEqual(parsed.wellbeing.stress, 4)
        self.assertEqual(parsed.career[0].duration_hours, 2)
        self.assertIn("global LSTM paper", parsed.career[0].project)

    def test_journal_fallback_when_no_structured_signals(self) -> None:
        parsed = extract_daily_log("Thinking through whether I am overcommitting this week.")

        self.assertEqual(parsed.journal_text, "Thinking through whether I am overcommitting this week.")
        self.assertEqual(parsed.nutrition, [])
        self.assertIsNone(parsed.workout)

