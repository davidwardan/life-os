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

    def test_extracts_structured_complex_daily_log(self) -> None:
        parsed = extract_daily_log(
            "Today I slept 6h, woke up tired, energy 5/10 and stress 7/10. "
            "Ate oatmeal with dates, peanut butter, and chocolate in the morning. "
            "Lunch was 180g cooked chicken with rice and salad. "
            "Did lower body: squats 4x5 at 80%, RDL 3x8, and 12 min metcon. "
            "Worked 3 hours on the global TAGI-LSTM paper and fixed the SKF motivation section. "
            "Mood was okay but I felt mentally drained.",
            date(2026, 4, 25),
        )

        self.assertEqual(parsed.date.isoformat(), "2026-04-25")
        self.assertEqual(parsed.wellbeing.sleep_hours, 6)
        self.assertEqual(parsed.wellbeing.energy, 5)
        self.assertEqual(parsed.wellbeing.stress, 7)
        self.assertIn("mentally drained", parsed.wellbeing.notes.lower())
        self.assertEqual(parsed.nutrition[0].meal_type, "breakfast")
        self.assertIn("oatmeal", parsed.nutrition[0].description)
        self.assertEqual(parsed.nutrition[1].meal_type, "lunch")
        self.assertEqual(parsed.nutrition[1].protein_g, 55)
        self.assertEqual(parsed.workout.workout_type, "lower body")
        self.assertEqual(parsed.workout.exercises[0].name, "squat")
        self.assertEqual(parsed.workout.exercises[0].sets, 4)
        self.assertEqual(parsed.workout.exercises[0].reps, 5)
        self.assertEqual(parsed.workout.exercises[0].load, "80% 1RM")
        self.assertEqual(parsed.workout.exercises[1].name, "Romanian deadlift")
        self.assertEqual(parsed.workout.exercises[2].name, "metcon")
        self.assertEqual(parsed.workout.exercises[2].duration_min, 12)
        self.assertEqual(parsed.career[0].duration_hours, 3)
        self.assertIn("TAGI-LSTM", parsed.career[0].project)
        self.assertIn("SKF motivation", parsed.career[0].progress_note)
        self.assertIn("fatigue", parsed.journal.tags)

    def test_journal_fallback_when_no_structured_signals(self) -> None:
        parsed = extract_daily_log("Thinking through whether I am overcommitting this week.")

        self.assertEqual(parsed.journal_text, "Thinking through whether I am overcommitting this week.")
        self.assertEqual(parsed.nutrition, [])
        self.assertIsNone(parsed.workout)

    def test_vague_workout_gets_bounded_followup(self) -> None:
        parsed = extract_daily_log(
            "Had a tough day but still did a good workout for 90mins at the gym. "
            "I did legs and upper body. Dinner was chicken and fries.",
            date(2026, 4, 25),
        )

        self.assertEqual(parsed.workout.duration_min, 90)
        self.assertLessEqual(len(parsed.clarification_questions), 2)
        self.assertTrue(
            any("exercises" in question.lower() for question in parsed.clarification_questions)
        )
        self.assertTrue(
            any("energy" in question.lower() or "stress" in question.lower() for question in parsed.clarification_questions)
        )

    def test_bare_exercise_reply_extracts_workout_exercises(self) -> None:
        parsed = extract_daily_log(
            "i did squats deadlifts lunges chin ups dumbell press",
            date(2026, 4, 25),
        )

        self.assertEqual(parsed.workout.workout_type, "strength")
        self.assertEqual(
            [exercise.name for exercise in parsed.workout.exercises],
            ["squat", "deadlift", "lunge", "chin up", "dumbbell press"],
        )

    def test_extracts_name_first_sets_reps_and_load(self) -> None:
        parsed = extract_daily_log(
            "I did squats 3 sets od 10 reps 100 kg",
            date(2026, 4, 25),
        )

        exercise = parsed.workout.exercises[0]
        self.assertEqual(exercise.name, "squat")
        self.assertEqual(exercise.sets, 3)
        self.assertEqual(exercise.reps, 10)
        self.assertEqual(exercise.load, "100 kg")

    def test_extracts_sets_first_sets_reps_and_load(self) -> None:
        parsed = extract_daily_log(
            "i did 3sets 10 each squats with a 100 kg",
            date(2026, 4, 25),
        )

        exercise = parsed.workout.exercises[0]
        self.assertEqual(exercise.name, "squat")
        self.assertEqual(exercise.sets, 3)
        self.assertEqual(exercise.reps, 10)
        self.assertEqual(exercise.load, "100 kg")

    def test_estimates_calories_when_meal_calories_are_missing(self) -> None:
        parsed = extract_daily_log(
            "Dinner was chicken and fries.",
            date(2026, 4, 25),
        )

        self.assertEqual(parsed.nutrition[0].meal_type, "dinner")
        self.assertEqual(parsed.nutrition[0].calories, 850)
        self.assertTrue(parsed.nutrition[0].estimated)
        self.assertTrue(any("actual calories" in q.lower() for q in parsed.clarification_questions))
