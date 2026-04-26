from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from backend.app.db import LifeDatabase
from backend.app.extraction import extract_daily_log
from backend.app.plotting import PlotRequest, PlotService, parse_plot_request
from backend.app.schemas import MessageIn


class PlottingTests(TestCase):
    def test_parse_plot_request(self) -> None:
        request = parse_plot_request("show me my energy for the last week")

        self.assertIsNotNone(request)
        self.assertEqual(request.metric, "energy")
        self.assertEqual(request.days, 7)

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
