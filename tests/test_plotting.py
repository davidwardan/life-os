from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from backend.app.db import LifeDatabase
from backend.app.extraction import extract_daily_log
from backend.app.plotting import PlotRequest, PlotService, parse_plot_request, parse_plot_requests
from backend.app.schemas import MessageIn


class PlottingTests(TestCase):
    def test_parse_plot_request(self) -> None:
        request = parse_plot_request("show me my energy for the last week")

        self.assertIsNotNone(request)
        self.assertEqual(request.metric, "energy")
        self.assertEqual(request.days, 7)

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

        self.assertEqual([request.metric for request in requests], ["energy", "career", "workout", "protein"])
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
