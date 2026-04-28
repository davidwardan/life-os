from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from backend.app.briefing import BriefingService
from backend.app.db import LifeDatabase
from backend.app.integrations import (
    ExternalSyncService,
    GoogleCalendarClient,
    GoogleOAuthTokenProvider,
)


class FakeTodoistClient:
    async def fetch_tasks(self) -> list[dict[str, object]]:
        return [
            {
                "id": "task-overdue",
                "content": "Submit passport form",
                "description": "Needs final check",
                "priority": 1,
                "labels": ["admin"],
                "due": {
                    "date": "2026-04-24",
                    "string": "yesterday",
                    "is_recurring": False,
                },
                "url": "https://todoist.com/showTask?id=task-overdue",
            },
            {
                "id": "task-today",
                "content": "Review calendar API notes",
                "priority": 2,
                "labels": ["life-os"],
                "due": {
                    "date": "2026-04-25",
                    "datetime": "2026-04-25T15:00:00Z",
                    "string": "today at 11",
                    "timezone": "America/Toronto",
                },
            },
        ]


class FakeCalendarClient:
    calendar_ids = ("primary",)

    async def fetch_events(self, start_at: datetime, end_at: datetime) -> list[dict[str, object]]:
        return [
            {
                "_calendar_id": "primary",
                "_calendar_summary": "Personal",
                "id": "event-standup",
                "summary": "Morning standup",
                "status": "confirmed",
                "transparency": "opaque",
                "eventType": "default",
                "start": {"dateTime": "2026-04-25T09:00:00-04:00"},
                "end": {"dateTime": "2026-04-25T09:30:00-04:00"},
                "htmlLink": "https://calendar.google.com/event?eid=event-standup",
                "updated": "2026-04-24T18:00:00Z",
            },
            {
                "_calendar_id": "primary",
                "_calendar_summary": "Personal",
                "id": "event-focus",
                "summary": "Focus block",
                "status": "confirmed",
                "transparency": "opaque",
                "eventType": "focusTime",
                "start": {"dateTime": "2026-04-25T13:00:00-04:00"},
                "end": {"dateTime": "2026-04-25T15:00:00-04:00"},
            },
        ]


class FakeGoogleResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeGoogleHttpClient:
    token_requests = 0
    calendar_headers: list[dict[str, str]] = []

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "FakeGoogleHttpClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, _url: str, data: dict[str, str]) -> FakeGoogleResponse:
        self.__class__.token_requests += 1
        self.__class__.last_token_data = data
        return FakeGoogleResponse({"access_token": "fresh-access-token", "expires_in": 3600})

    async def get(
        self,
        _url: str,
        headers: dict[str, str],
        params: dict[str, object],
    ) -> FakeGoogleResponse:
        self.__class__.calendar_headers.append(headers)
        return FakeGoogleResponse(
            {
                "summary": "Personal",
                "items": [
                    {
                        "id": "event-api",
                        "summary": "API check",
                        "start": {"dateTime": "2026-04-25T10:00:00-04:00"},
                        "end": {"dateTime": "2026-04-25T10:30:00-04:00"},
                    }
                ],
            }
        )


class IntegrationSyncTests(IsolatedAsyncioTestCase):
    async def test_sync_stores_todoist_tasks_and_calendar_events(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            service = ExternalSyncService(
                db,
                todoist_client=FakeTodoistClient(),
                calendar_client=FakeCalendarClient(),
            )

            result = await service.sync(date(2026, 4, 25), lookahead_days=7)

            self.assertEqual(result.todoist_tasks, 2)
            self.assertEqual(result.calendar_events, 2)
            self.assertEqual(result.errors, ())
            with db.connect() as connection:
                tasks = connection.execute("SELECT * FROM todoist_tasks ORDER BY id").fetchall()
                events = connection.execute(
                    "SELECT * FROM calendar_events ORDER BY event_id"
                ).fetchall()

            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0]["content"], "Submit passport form")
            self.assertEqual(len(events), 2)
            self.assertEqual(
                {event["summary"] for event in events}, {"Morning standup", "Focus block"}
            )

    async def test_briefing_features_include_synced_tasks_and_calendar(self) -> None:
        with TemporaryDirectory() as directory:
            db = LifeDatabase(Path(directory) / "life.sqlite3")
            sync = ExternalSyncService(
                db,
                todoist_client=FakeTodoistClient(),
                calendar_client=FakeCalendarClient(),
            )
            await sync.sync(date(2026, 4, 25), lookahead_days=7)
            briefing = await BriefingService(db).generate(date(2026, 4, 25))

            self.assertEqual(briefing.features["todoist"]["overdue_count"], 1)
            self.assertEqual(briefing.features["todoist"]["today_due_count"], 1)
            self.assertEqual(briefing.features["calendar"]["events_today_count"], 2)
            self.assertGreater(briefing.features["calendar"]["busy_hours_today"], 0)
            self.assertIn("overdue Todoist", briefing.text)

    async def test_google_oauth_provider_refreshes_and_caches_access_token(self) -> None:
        FakeGoogleHttpClient.token_requests = 0

        provider = GoogleOAuthTokenProvider(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        )

        with patch("backend.app.integrations.httpx.AsyncClient", FakeGoogleHttpClient):
            first = await provider.access_token()
            second = await provider.access_token()

        self.assertEqual(first, "fresh-access-token")
        self.assertEqual(second, "fresh-access-token")
        self.assertEqual(FakeGoogleHttpClient.token_requests, 1)

    async def test_google_calendar_client_uses_refreshed_oauth_token(self) -> None:
        FakeGoogleHttpClient.token_requests = 0
        FakeGoogleHttpClient.calendar_headers = []
        provider = GoogleOAuthTokenProvider(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        )
        client = GoogleCalendarClient(token_provider=provider)

        with patch("backend.app.integrations.httpx.AsyncClient", FakeGoogleHttpClient):
            events = await client.fetch_events(
                datetime.fromisoformat("2026-04-25T00:00:00-04:00"),
                datetime.fromisoformat("2026-04-26T00:00:00-04:00"),
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["_calendar_id"], "primary")
        self.assertEqual(
            FakeGoogleHttpClient.calendar_headers[0]["Authorization"],
            "Bearer fresh-access-token",
        )
