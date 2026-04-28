from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from backend.app.agent_planning import AgentPlan, PlannedAction
from backend.app.briefing import BriefingService
from backend.app.db import LifeDatabase
from backend.app.extraction import extract_daily_log
from backend.app.llm_extraction import ExtractionService
from backend.app.memory import MemoryService
from backend.app.plotting import PlotService
from backend.app.schemas import MessageIn
from backend.app.workflow import AgentWorkflow


class WorkflowTests(IsolatedAsyncioTestCase):
    async def test_routes_plot_without_creating_raw_log(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            db.save_message(
                MessageIn(text="Energy 7, stress 4.", entry_date=date(2026, 4, 25), source="api"),
                extract_daily_log("Energy 7, stress 4.", date(2026, 4, 25)),
            )
            workflow = _workflow(db)

            result = await workflow.process_text(
                "plot my energy",
                source="telegram",
                entry_date=date(2026, 4, 25),
            )

            self.assertEqual(result.status, "plot_sent")
            self.assertEqual(len(result.plot_results), 1)
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_routes_memory_without_creating_raw_log(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            workflow = _workflow(db)

            result = await workflow.process_text(
                "Remember that training early works for me.",
                source="telegram",
                entry_date=date(2026, 4, 25),
            )

            self.assertEqual(result.status, "memory_updated")
            self.assertIn("I will remember", result.confirmation or "")
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 0)

    async def test_log_text_for_web_always_logs(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            workflow = _workflow(db)

            result = await workflow.log_text(
                "plot my energy",
                source="web",
                entry_date=date(2026, 4, 25),
            )

            self.assertEqual(result.status, "logged")
            self.assertIn("Logged Apr 25 as #1.", result.confirmation or "")
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_combined_no_more_info_and_briefing_routes_to_briefing(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            workflow = _workflow(db)

            result = await workflow.process_text(
                "no more info and provide me with morning brief",
                source="telegram",
                entry_date=date(2026, 4, 27),
            )

            self.assertEqual(result.status, "briefing_sent")
            self.assertIsNotNone(result.briefing)
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 0)

    async def test_llm_plan_can_log_and_send_briefing_from_one_message(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            workflow = _workflow(
                db,
                planner=FakePlanner(
                    [
                        PlannedAction(intent="log", text="Energy 7, stress 4."),
                        PlannedAction(intent="briefing", text="provide me with morning brief"),
                    ]
                ),
            )

            result = await workflow.process_text(
                "Energy 7, stress 4 and provide me with morning brief",
                source="telegram",
                entry_date=date(2026, 4, 27),
            )

            self.assertEqual(result.status, "completed_actions")
            self.assertEqual(len(result.action_results), 2)
            self.assertIsNotNone(result.briefing)
            self.assertIn("Logged Apr 27 as #1.", result.confirmation or "")
            self.assertIn("Morning brief", result.confirmation or "")
            self.assertEqual(len(db.recent_logs()["raw_messages"]), 1)

    async def test_duplicate_structured_rows_are_called_out_in_confirmation(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            first = MessageIn(
                text="Dinner was chicken and fries.",
                entry_date=date(2026, 4, 25),
                source="api",
            )
            db.save_message(first, extract_daily_log(first.text, first.entry_date))
            workflow = _workflow(db)

            result = await workflow.log_text(
                "Dinner was chicken and fries.",
                source="telegram",
                entry_date=date(2026, 4, 25),
            )

            self.assertEqual(result.status, "logged")
            self.assertEqual(result.records["nutrition"], [])
            self.assertIn("Already logged", result.confirmation or "")


class FakePlanner:
    def __init__(self, actions: list[PlannedAction]):
        self.actions = actions
        self.contexts: list[dict[str, object]] = []

    async def plan(self, text: str, *, context: dict[str, object]) -> AgentPlan:
        self.contexts.append(context)
        return AgentPlan(actions=self.actions)


def _workflow(db: LifeDatabase, planner: FakePlanner | None = None) -> AgentWorkflow:
    memory = MemoryService(db)
    return AgentWorkflow(
        db=db,
        extractor=ExtractionService(mode="deterministic"),
        plotter=PlotService(db),
        memory_service=memory,
        briefing_service=BriefingService(db, memory_service=memory),
        planner=planner,
        use_configured_planner=False,
    )
