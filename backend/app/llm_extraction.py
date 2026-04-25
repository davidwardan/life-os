from __future__ import annotations

import json
import asyncio
from datetime import date
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from backend.app.config import settings
from backend.app.extraction import extract_daily_log
from backend.app.schemas import ParsedDailyLog


SYSTEM_PROMPT = """
You extract structured records from one personal daily log message.

Return only JSON that matches the provided schema.

Rules:
- Preserve the user's raw meaning. Do not invent facts.
- Extract every category independently; do not stop after finding nutrition or workout.
- Use null when a value is not stated.
- Use confidence between 0 and 1 for each extracted record.
- Mark nutrition as estimated=true unless exact calories or macros are explicitly provided.
- Put open-ended reflection into journal_text when it is a journal note.
- Add missing_info_questions only for useful follow-up questions.
- Dates must use ISO format YYYY-MM-DD.

Extraction checklist:
- Food, meals, calories, protein, macros -> nutrition.
- Training, exercise, workout duration, RPE, intensity -> workout.
- Energy, mood, stress, sleep, soreness, recovery -> wellbeing.
- Work sessions, career progress, project names, research, writing, blockers -> career.

Example:
Text: "Ate yogurt. Trained legs 55 min intensity 8. Energy 6, stress 5. Worked 2h on thesis and drafted intro."
Must include nutrition, workout, wellbeing with energy=6 and stress=5, and career with project="thesis", duration_hours=2, progress_note="drafted intro".
""".strip()


class LLMClient(Protocol):
    async def extract(self, text: str, entry_date: date) -> dict[str, Any]:
        ...


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str = settings.openrouter_model,
        base_url: str = settings.openrouter_base_url,
        timeout_seconds: float = settings.llm_timeout_seconds,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def extract(self, text: str, entry_date: date) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Target entry_date: {entry_date.isoformat()}\n\n"
                        f"Daily log text:\n{text}"
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "parsed_daily_log",
                    "strict": False,
                    "schema": ParsedDailyLog.model_json_schema(),
                },
            },
            "provider": {
                "require_parameters": True,
            },
            "temperature": 0,
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await asyncio.wait_for(
                client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "http://127.0.0.1:8000",
                        "X-Title": "Life OS",
                    },
                    json=payload,
                ),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()

        return _decode_response_json(response.json())


class ExtractionService:
    def __init__(self, mode: str = settings.extractor, llm_client: LLMClient | None = None):
        self.mode = mode
        self.llm_client = llm_client

    async def extract(self, text: str, entry_date: date | None = None) -> tuple[ParsedDailyLog, str, str | None]:
        target_date = entry_date or date.today()

        if self.mode == "deterministic":
            return extract_daily_log(text, target_date), "deterministic", None

        client = self.llm_client or _configured_llm_client()
        if client is None:
            if self.mode == "llm":
                fallback = extract_daily_log(text, target_date)
                return fallback, "deterministic", "OPENROUTER_API_KEY is not configured"
            return extract_daily_log(text, target_date), "deterministic", None

        try:
            parsed = ParsedDailyLog.model_validate(await client.extract(text, target_date))
            if entry_date is not None:
                parsed.entry_date = entry_date
            return parsed, "llm", None
        except (asyncio.TimeoutError, httpx.HTTPError, json.JSONDecodeError, ValidationError, ValueError) as error:
            fallback = extract_daily_log(text, target_date)
            return fallback, "deterministic", f"LLM extraction failed: {_format_error(error)}"


def _configured_llm_client() -> OpenRouterClient | None:
    if not settings.openrouter_api_key:
        return None
    return OpenRouterClient(api_key=settings.openrouter_api_key)


def _decode_response_json(payload: dict[str, Any]) -> dict[str, Any]:
    for choice in payload.get("choices", []):
        message = choice.get("message", {})
        content = message.get("content")
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            return json.loads(content)

    raise ValueError("Could not find structured JSON in LLM response")


def _format_error(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return f"OpenRouter request exceeded {settings.llm_timeout_seconds:g}s timeout"
    message = str(error).strip()
    return message or error.__class__.__name__
