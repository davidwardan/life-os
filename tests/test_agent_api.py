from datetime import date
from unittest import TestCase

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.schemas import ParsedDailyLog, WellbeingEntry
from backend.app.workflow import WorkflowResult


class FakeWorkflow:
    def __init__(self) -> None:
        self.forced_intents: list[str | None] = []

    async def process_text(
        self,
        text: str,
        *,
        source: str,
        entry_date: date | None,
        forced_intent: str | None = None,
    ) -> WorkflowResult:
        self.forced_intents.append(forced_intent)
        if forced_intent == "log":
            return self._logged_result(entry_date)
        return WorkflowResult(
            ok=True,
            status=f"{forced_intent or 'auto'}_handled",
            confirmation="Got it. I left the log unchanged.",
        )

    def _logged_result(self, entry_date: date | None) -> WorkflowResult:
        parsed = ParsedDailyLog(
            date=entry_date or date(2026, 4, 25),
            wellbeing=WellbeingEntry(energy=7, confidence=1),
        )
        return WorkflowResult(
            ok=True,
            status="logged",
            confirmation="Logged Apr 25 as #42.\nWellbeing: energy 7/10",
            raw_message_id=42,
            parsed=parsed,
            records={"daily_checkins": [{"id": 1, "energy": 7}]},
            extraction_method="deterministic",
        )


class AgentApiTests(TestCase):
    def setUp(self) -> None:
        self.original_workflow = main.workflow
        self.original_require_web_auth = main.settings.require_web_auth
        self.fake_workflow = FakeWorkflow()
        main.workflow = self.fake_workflow
        main.settings.require_web_auth = False
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        main.workflow = self.original_workflow
        main.settings.require_web_auth = self.original_require_web_auth

    def test_agent_log_mode_returns_conversation_metadata(self) -> None:
        response = self.client.post(
            "/api/agent",
            json={
                "text": "Energy 7.",
                "entry_date": "2026-04-25",
                "source": "web",
                "mode": "log",
                "tone": "terse",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "logged")
        self.assertEqual(payload["confirmation"], "Logged Apr 25 as #42.")
        self.assertEqual(
            payload["assumption"],
            "Log mode stores this as a daily record, even if it looks like a command.",
        )
        self.assertEqual(payload["raw_message_id"], 42)
        self.assertEqual(self.fake_workflow.forced_intents, ["log"])

    def test_agent_auto_mode_can_return_non_log_reply(self) -> None:
        response = self.client.post(
            "/api/agent",
            json={"text": "no more info", "source": "web", "mode": "auto"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "auto_handled")
        self.assertIsNone(payload["parsed"])
        self.assertEqual(self.fake_workflow.forced_intents, [None])

    def test_agent_explicit_modes_bypass_auto_classification(self) -> None:
        response = self.client.post(
            "/api/agent",
            json={"text": "summary please", "source": "web", "mode": "briefing"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "briefing_handled")
        self.assertEqual(self.fake_workflow.forced_intents, ["briefing"])

    def test_agent_chat_mode_is_accepted(self) -> None:
        response = self.client.post(
            "/api/agent",
            json={"text": "hi", "source": "web", "mode": "chat"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "chat_handled")
        self.assertEqual(self.fake_workflow.forced_intents, ["chat"])
