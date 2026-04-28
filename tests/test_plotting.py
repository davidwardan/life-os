from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from backend.app.db import LifeDatabase
from backend.app.extraction import extract_daily_log
from backend.app.plotting import (
    PlotRequest,
    PlotService,
    parse_plot_request,
    parse_plot_requests,
    supported_plots,
)
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


class PlottingTests(TestCase):
    def test_parse_plot_request(self) -> None:
        request = parse_plot_request("show me my energy for the last week")

        self.assertIsNotNone(request)
        self.assertEqual(request.metric, "energy")
        self.assertEqual(request.days, 7)

    def test_parse_phase_four_plot_requests(self) -> None:
        cases = {
            "plot sleep vs energy": ("sleep_energy", None),
            "show stress vs workouts": ("stress_workout", None),
            "show workout frequency": ("workout_frequency", None),
            "plot squat history": ("exercise_history", "squat"),
            "plot deep work by project": ("career_projects", None),
            "show protein consistency": ("protein_consistency", None),
            "show habit heatmap": ("data_completeness", None),
        }

        for text, expected in cases.items():
            request = parse_plot_request(text)

            self.assertIsNotNone(request)
            self.assertEqual((request.metric, request.subject), expected)

    def test_parse_multiple_plot_requests_from_lines(self) -> None:
        requests = parse_plot_requests(
            "\n".join(
                [
                    "plot my energy",
                    "show my career hours",
                    "plot my workouts",
                    "plot protein for the last week",
                ]
            )
        )

        self.assertEqual(
            [request.metric for request in requests], ["energy", "career", "workout", "protein"]
        )
        self.assertEqual([request.days for request in requests], [30, 30, 30, 7])

    def test_generates_energy_plot_png(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            parsed = extract_daily_log("Energy 7, stress 4.", date.today())
            db.save_message(
                MessageIn(text="Energy 7, stress 4.", entry_date=date.today(), source="web"),
                parsed,
            )
            plotter = PlotService(db, plots_dir=Path(directory) / "plots")

            result = plotter.generate(PlotRequest(metric="energy", days=30))

            self.assertTrue(result.path.exists())
            self.assertEqual(result.path.suffix, ".png")
            self.assertGreater(result.path.stat().st_size, 0)

    def test_generates_all_supported_phase_four_plots(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            _seed_plot_data(db)
            plotter = PlotService(db, plots_dir=Path(directory) / "plots")

            requests = [
                PlotRequest(metric="energy"),
                PlotRequest(metric="sleep_energy"),
                PlotRequest(metric="stress_workout"),
                PlotRequest(metric="workout"),
                PlotRequest(metric="workout_frequency"),
                PlotRequest(metric="exercise_history", subject="squat"),
                PlotRequest(metric="exercise_history"),
                PlotRequest(metric="career"),
                PlotRequest(metric="career_projects"),
                PlotRequest(metric="protein"),
                PlotRequest(metric="protein_consistency"),
                PlotRequest(metric="calories"),
                PlotRequest(metric="data_completeness"),
            ]

            for request in requests:
                result = plotter.generate(request)

                self.assertTrue(result.path.exists(), request.metric)
                self.assertGreater(result.path.stat().st_size, 0, request.metric)

    def test_supported_plot_catalog_is_available(self) -> None:
        metrics = {plot["metric"] for plot in supported_plots()}

        self.assertIn("sleep_energy", metrics)
        self.assertIn("stress_workout", metrics)
        self.assertIn("data_completeness", metrics)


def _seed_plot_data(db: LifeDatabase) -> None:
    today = date.today()
    for offset in range(6):
        entry_date = today - timedelta(days=5 - offset)
        parsed = ParsedDailyLog(
            date=entry_date,
            wellbeing=WellbeingEntry(
                sleep_hours=6 + (offset % 3),
                energy=5 + (offset % 4),
                stress=7 - (offset % 3),
                mood=6,
                confidence=1.0,
            ),
            nutrition=[
                NutritionEntry(
                    meal_type="lunch",
                    description="chicken rice bowl",
                    calories=650 + (offset * 25),
                    protein_g=35 + offset,
                    estimated=False,
                    confidence=1.0,
                )
            ],
            workout=WorkoutEntry(
                workout_type="lower body" if offset % 2 == 0 else "upper body",
                duration_min=45 + offset,
                exercises=[
                    ExerciseEntry(name="squat", sets=4, reps=5, load="80%"),
                    ExerciseEntry(name="chin up", sets=3, reps=6),
                ],
                confidence=1.0,
            ),
            career=[
                CareerEntry(
                    project="global TAGI-LSTM paper" if offset < 3 else "Life OS",
                    activity="deep work",
                    duration_hours=1.5 + offset,
                    progress_note="Moved the work forward.",
                    confidence=1.0,
                )
            ],
            journal=JournalEntry(text="Focused but tired.", tags=["focus", "fatigue"]),
        )
        db.save_message(
            MessageIn(text=f"seed plot data {offset}", entry_date=entry_date, source="api"),
            parsed,
        )
