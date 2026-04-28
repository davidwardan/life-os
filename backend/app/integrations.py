from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from backend.app.config import settings
from backend.app.db import LifeDatabase


class TodoistTaskClient(Protocol):
    async def fetch_tasks(self) -> list[dict[str, Any]]: ...


class CalendarEventClient(Protocol):
    async def fetch_events(self, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]: ...


class AccessTokenProvider(Protocol):
    async def access_token(self) -> str: ...


@dataclass(frozen=True)
class ExternalSyncResult:
    todoist_configured: bool
    google_calendar_configured: bool
    todoist_tasks: int = 0
    calendar_events: int = 0
    errors: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class TodoistClient:
    def __init__(
        self,
        api_token: str,
        base_url: str = settings.todoist_base_url,
        timeout_seconds: float = 20,
    ):
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def fetch_tasks(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        cursor: str | None = None
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            while True:
                params: dict[str, Any] = {"limit": 200}
                if cursor:
                    params["cursor"] = cursor
                response = await client.get(
                    f"{self.base_url}/tasks",
                    headers={"Authorization": f"Bearer {self.api_token}"},
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    tasks.extend(item for item in payload if isinstance(item, dict))
                    break
                if not isinstance(payload, dict):
                    raise ValueError("Todoist tasks response was not a JSON object")
                results = payload.get("results", [])
                if not isinstance(results, list):
                    raise ValueError("Todoist tasks response did not include a results list")
                tasks.extend(item for item in results if isinstance(item, dict))
                cursor = payload.get("next_cursor")
                if not cursor:
                    break
        return tasks


class GoogleCalendarClient:
    def __init__(
        self,
        access_token: str | None = None,
        token_provider: AccessTokenProvider | None = None,
        calendar_ids: tuple[str, ...] = settings.google_calendar_ids,
        base_url: str = settings.google_calendar_base_url,
        timezone: str = settings.timezone,
        timeout_seconds: float = 20,
    ):
        self.access_token = access_token
        self.token_provider = token_provider
        self.calendar_ids = calendar_ids
        self.base_url = base_url.rstrip("/")
        self.timezone = timezone
        self.timeout_seconds = timeout_seconds

    async def fetch_events(self, start_at: datetime, end_at: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        access_token = await self._access_token()
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for calendar_id in self.calendar_ids:
                page_token: str | None = None
                while True:
                    params: dict[str, Any] = {
                        "timeMin": start_at.isoformat(),
                        "timeMax": end_at.isoformat(),
                        "singleEvents": "true",
                        "orderBy": "startTime",
                        "maxResults": 2500,
                        "timeZone": self.timezone,
                    }
                    if page_token:
                        params["pageToken"] = page_token
                    response = await client.get(
                        f"{self.base_url}/calendars/{quote(calendar_id, safe='')}/events",
                        headers={"Authorization": f"Bearer {access_token}"},
                        params=params,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("Google Calendar events response was not a JSON object")
                    calendar_summary = payload.get("summary")
                    for item in payload.get("items", []):
                        if isinstance(item, dict):
                            events.append(
                                {
                                    **item,
                                    "_calendar_id": calendar_id,
                                    "_calendar_summary": calendar_summary,
                                }
                            )
                    page_token = payload.get("nextPageToken")
                    if not page_token:
                        break
        return events

    async def _access_token(self) -> str:
        if self.token_provider is not None:
            return await self.token_provider.access_token()
        if self.access_token:
            return self.access_token
        raise ValueError("Google Calendar access token is not configured")


class GoogleOAuthTokenProvider:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        token_url: str = settings.google_oauth_token_url,
        timeout_seconds: float = 20,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.token_url = token_url
        self.timeout_seconds = timeout_seconds
        self._access_token: str | None = None
        self._expires_at: datetime | None = None

    async def access_token(self) -> str:
        now = datetime.now(ZoneInfo(settings.timezone))
        if self._access_token and self._expires_at and now < self._expires_at:
            return self._access_token

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self.token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            payload = response.json()

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Google OAuth token response did not include access_token")
        expires_in = _as_int(payload.get("expires_in")) or 3600
        self._access_token = access_token
        self._expires_at = now + timedelta(seconds=max(60, expires_in - 60))
        return access_token


class ExternalSyncService:
    def __init__(
        self,
        db: LifeDatabase,
        todoist_client: TodoistTaskClient | None = None,
        calendar_client: CalendarEventClient | None = None,
    ):
        self.db = db
        self.todoist_client = todoist_client or _configured_todoist_client()
        self.calendar_client = calendar_client or _configured_calendar_client()

    async def sync(
        self,
        target_date: date | None = None,
        lookahead_days: int = settings.integration_sync_lookahead_days,
    ) -> ExternalSyncResult:
        start_date = target_date or _today()
        end_date = start_date + timedelta(days=max(1, lookahead_days))
        start_at = datetime.combine(start_date, time.min, ZoneInfo(settings.timezone))
        end_at = datetime.combine(end_date, time.min, ZoneInfo(settings.timezone))

        todoist_count = 0
        calendar_count = 0
        errors: list[str] = []

        if self.todoist_client is not None:
            try:
                tasks = await self.todoist_client.fetch_tasks()
                todoist_count = self.replace_todoist_tasks(tasks)
            except Exception as error:
                errors.append(f"todoist: {_format_error(error)}")

        if self.calendar_client is not None:
            try:
                events = await self.calendar_client.fetch_events(start_at, end_at)
                calendar_ids = tuple(
                    str(item) for item in getattr(self.calendar_client, "calendar_ids", ())
                )
                calendar_count = self.replace_calendar_events(
                    events, start_date, end_date, calendar_ids=calendar_ids
                )
            except Exception as error:
                errors.append(f"google_calendar: {_format_error(error)}")

        return ExternalSyncResult(
            todoist_configured=self.todoist_client is not None,
            google_calendar_configured=self.calendar_client is not None,
            todoist_tasks=todoist_count,
            calendar_events=calendar_count,
            errors=tuple(errors),
        )

    def replace_todoist_tasks(self, tasks: list[dict[str, Any]]) -> int:
        now = _now()
        with self.db.connect() as connection:
            connection.execute("DELETE FROM todoist_tasks")
            for task in tasks:
                row = _normalize_todoist_task(task, now)
                if row is None:
                    continue
                connection.execute(
                    """
                    INSERT INTO todoist_tasks
                    (id, content, description, project_id, section_id, parent_id, labels_json,
                     priority, due_date, due_datetime, due_timezone, due_string, due_recurring,
                     url, updated_at, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["content"],
                        row["description"],
                        row["project_id"],
                        row["section_id"],
                        row["parent_id"],
                        row["labels_json"],
                        row["priority"],
                        row["due_date"],
                        row["due_datetime"],
                        row["due_timezone"],
                        row["due_string"],
                        row["due_recurring"],
                        row["url"],
                        row["updated_at"],
                        row["synced_at"],
                    ),
                )
        return len([task for task in tasks if task.get("id") and task.get("content")])

    def replace_calendar_events(
        self,
        events: list[dict[str, Any]],
        start_date: date,
        end_date: date,
        calendar_ids: tuple[str, ...] = (),
    ) -> int:
        now = _now()
        synced_calendar_ids = set(calendar_ids) | {
            str(event.get("_calendar_id") or "primary")
            for event in events
            if event.get("_calendar_id") or event.get("id")
        }
        with self.db.connect() as connection:
            for calendar_id in synced_calendar_ids:
                connection.execute(
                    """
                    DELETE FROM calendar_events
                    WHERE calendar_id = ?
                      AND COALESCE(start_date, substr(start_at, 1, 10)) < ?
                      AND COALESCE(end_date, substr(end_at, 1, 10), start_date, substr(start_at, 1, 10)) >= ?
                    """,
                    (calendar_id, end_date.isoformat(), start_date.isoformat()),
                )
            count = 0
            for event in events:
                row = _normalize_calendar_event(event, now)
                if row is None:
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO calendar_events
                    (calendar_id, event_id, calendar_summary, summary, description, location,
                     start_at, end_at, start_date, end_date, all_day, status, transparency,
                     event_type, html_link, updated_at, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["calendar_id"],
                        row["event_id"],
                        row["calendar_summary"],
                        row["summary"],
                        row["description"],
                        row["location"],
                        row["start_at"],
                        row["end_at"],
                        row["start_date"],
                        row["end_date"],
                        row["all_day"],
                        row["status"],
                        row["transparency"],
                        row["event_type"],
                        row["html_link"],
                        row["updated_at"],
                        row["synced_at"],
                    ),
                )
                count += 1
        return count


def configured_external_sync_service(db: LifeDatabase) -> ExternalSyncService:
    return ExternalSyncService(db)


def _configured_todoist_client() -> TodoistClient | None:
    if not settings.todoist_api_token:
        return None
    return TodoistClient(api_token=settings.todoist_api_token)


def _configured_calendar_client() -> GoogleCalendarClient | None:
    if (
        settings.google_oauth_client_id
        and settings.google_oauth_client_secret
        and settings.google_oauth_refresh_token
    ):
        return GoogleCalendarClient(
            token_provider=GoogleOAuthTokenProvider(
                client_id=settings.google_oauth_client_id,
                client_secret=settings.google_oauth_client_secret,
                refresh_token=settings.google_oauth_refresh_token,
            )
        )
    if settings.google_calendar_access_token:
        return GoogleCalendarClient(access_token=settings.google_calendar_access_token)
    return None


def _normalize_todoist_task(task: dict[str, Any], synced_at: str) -> dict[str, Any] | None:
    task_id = task.get("id")
    content = task.get("content")
    if not task_id or not content:
        return None
    due = task.get("due") if isinstance(task.get("due"), dict) else {}
    due_date = _as_text(due.get("date"))
    due_datetime = _as_text(due.get("datetime"))
    if due_date and "T" in due_date and due_datetime is None:
        due_datetime = due_date
        due_date = due_date[:10]
    labels = task.get("labels")
    if not isinstance(labels, list):
        labels = []
    return {
        "id": str(task_id),
        "content": str(content),
        "description": _as_text(task.get("description")),
        "project_id": _as_text(task.get("project_id")),
        "section_id": _as_text(task.get("section_id")),
        "parent_id": _as_text(task.get("parent_id")),
        "labels_json": json.dumps([str(label) for label in labels]),
        "priority": _as_int(task.get("priority")),
        "due_date": due_date,
        "due_datetime": due_datetime,
        "due_timezone": _as_text(due.get("timezone")),
        "due_string": _as_text(due.get("string")),
        "due_recurring": int(bool(due.get("is_recurring") or due.get("recurring"))),
        "url": _as_text(task.get("url")),
        "updated_at": _as_text(task.get("updated_at")),
        "synced_at": synced_at,
    }


def _normalize_calendar_event(event: dict[str, Any], synced_at: str) -> dict[str, Any] | None:
    event_id = event.get("id")
    if not event_id:
        return None
    start = event.get("start") if isinstance(event.get("start"), dict) else {}
    end = event.get("end") if isinstance(event.get("end"), dict) else {}
    start_at = _as_text(start.get("dateTime"))
    end_at = _as_text(end.get("dateTime"))
    start_date = _as_text(start.get("date"))
    end_date = _as_text(end.get("date"))
    return {
        "calendar_id": str(event.get("_calendar_id") or "primary"),
        "event_id": str(event_id),
        "calendar_summary": _as_text(event.get("_calendar_summary")),
        "summary": _as_text(event.get("summary")) or "(busy)",
        "description": _as_text(event.get("description")),
        "location": _as_text(event.get("location")),
        "start_at": start_at,
        "end_at": end_at,
        "start_date": start_date or _date_prefix(start_at),
        "end_date": end_date or _date_prefix(end_at),
        "all_day": int(bool(start_date)),
        "status": _as_text(event.get("status")) or "confirmed",
        "transparency": _as_text(event.get("transparency")),
        "event_type": _as_text(event.get("eventType")),
        "html_link": _as_text(event.get("htmlLink")),
        "updated_at": _as_text(event.get("updated")),
        "synced_at": synced_at,
    }


def _date_prefix(value: str | None) -> str | None:
    if not value:
        return None
    return value[:10]


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_error(error: Exception) -> str:
    message = str(error).strip()
    return message or error.__class__.__name__


def _now() -> str:
    return datetime.now(ZoneInfo(settings.timezone)).isoformat()


def _today() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()
