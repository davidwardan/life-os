"""Test package initialization.

Keeps the suite hermetic: a developer's real `.env` (loaded by
backend.app.config at import time) must never leak live API keys into
tests, otherwise extraction/briefing tests hit OpenRouter, Telegram,
Todoist, Google, or Turso and become slow and flaky.

This module runs before any test module imports backend code, and
``load_dotenv`` does not override variables that are already set.

Set LIFE_OS_TEST_ALLOW_NETWORK=1 to opt out (e.g. for manual smoke runs).
"""

import os

_EXTERNAL_SERVICE_VARS = (
    "OPENROUTER_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_ALLOWED_USER_IDS",
    "TELEGRAM_BRIEFING_CHAT_ID",
    "TODOIST_API_TOKEN",
    "GOOGLE_CALENDAR_ACCESS_TOKEN",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REFRESH_TOKEN",
    "TURSO_DATABASE_URL",
    "TURSO_AUTH_TOKEN",
    "BRIEFING_CRON_SECRET",
    "LIFE_OS_WEB_PASSWORD",
)

if not os.environ.get("LIFE_OS_TEST_ALLOW_NETWORK"):
    for _name in _EXTERNAL_SERVICE_VARS:
        os.environ[_name] = ""
