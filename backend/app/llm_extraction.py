from __future__ import annotations

import json
import asyncio
from datetime import date
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from backend.app.config import settings
from backend.app.extraction import extract_daily_log
from backend.app.followup import build_followup_questions
from backend.app.schemas import ParsedDailyLog


SYSTEM_PROMPT = """
You are an information extraction system for a local personal life logging app.

Convert one daily message into structured JSON. Return only JSON that matches the provided schema.

Rules:
- Only extract information supported by the text.
- Do not invent missing values.
- Use null for unknown fields.
- Preserve the user's raw meaning.
- Extract every category independently; do not stop after finding nutrition or workout.
- Use confidence between 0 and 1 for each extracted record.
- If you estimate calories or macros, mark estimated=true and keep confidence conservative.
- If a numeric value is explicitly stated, store it directly and do not mark it as estimated.
- Store vague logs too; use low confidence and ask at most two clarification questions.
- Put open-ended reflection into journal.text with concise tags.
- Add clarification_questions only for useful follow-up questions.
- Dates must use ISO format YYYY-MM-DD.

Extraction checklist:
- Food, meals, calories, protein, macros -> nutrition.
- Meal timing such as morning/lunch/dinner -> nutrition.meal_type.
- Training, exercise, workout duration, RPE, intensity -> workout and workout.exercises.
- Energy, mood, stress, sleep, soreness, recovery -> wellbeing.
- Work sessions, career progress, project names, research, writing, blockers -> career.

Example:
Text: "Today I slept 6h, energy 5/10 and stress 7/10. Ate oatmeal with dates in the morning. Lunch was 180g cooked chicken with rice. Did lower body: squats 4x5 at 80%, RDL 3x8, and 12 min metcon. Worked 3 hours on the global TAGI-LSTM paper and fixed the SKF motivation section. Mood was okay but I felt mentally drained."
Must include:
- date
- wellbeing.sleep_hours=6, energy=5, stress=7, mood around 6 if "okay"
- breakfast and lunch nutrition entries
- estimated protein only if estimating from chicken, with estimated=true
- workout.type/lower body plus exercise rows for squat, Romanian deadlift, metcon
- career project, duration_hours=3, activity, progress_note
- journal text and tags for fatigue/stress/research
""".strip()


class LLMClient(Protocol):
    async def extract(self, text: str, entry_date: date) -> dict[str, Any]:
        ...


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str = settings.openrouter_model,
        fallback_models: tuple[str, ...] = settings.openrouter_fallback_models,
        base_url: str = settings.openrouter_base_url,
        timeout_seconds: float = settings.llm_timeout_seconds,
    ):
        self.api_key = api_key
        self.model = model
        self.fallback_models = fallback_models
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def extract(self, text: str, entry_date: date) -> dict[str, Any]:
        errors: list[str] = []
        for model in (self.model, *self.fallback_models):
            try:
                return await self._extract_with_model(model, text, entry_date)
            except (
                asyncio.TimeoutError,
                httpx.HTTPError,
                json.JSONDecodeError,
                ValidationError,
                ValueError,
            ) as error:
                errors.append(f"{model}: {_format_error(error)}")

        raise ValueError("; ".join(errors))

    async def _extract_with_model(self, model: str, text: str, entry_date: date) -> dict[str, Any]:
        payload = {
            "model": model,
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
            parsed.clarification_questions = build_followup_questions(parsed)
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
