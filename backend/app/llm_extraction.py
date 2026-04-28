from __future__ import annotations

import json
import asyncio
import inspect
from datetime import date
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from backend.app.config import settings
from backend.app.extraction import extract_daily_log
from backend.app.followup import build_followup_questions
from backend.app.langextract_extraction import LangExtractClient, LangExtractRunner
from backend.app.langextract_extraction import parsed_log_from_langextract
from backend.app.schemas import ParsedDailyLog


CHAT_SYSTEM_PROMPT = """
You are a helpful and warm personal life logging assistant.

The user is talking to you or greeting you without providing specific life data to log.
Respond in a friendly, concise, and natural way.
If the user asks who you are, explain that you help them track their daily life (nutrition, workouts, wellbeing, career).
Keep your response to 1-2 sentences unless a longer explanation is needed.
""".strip()


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
- Use already_logged_context to avoid extracting duplicate same-day facts when the user appears to be repeating information already logged.
- If the user is clearly updating or adding missing detail, extract only the new or corrected detail.

Extraction checklist:
- Food, meals, calories, protein, macros -> nutrition.
- Meal timing such as morning/lunch/dinner -> nutrition.meal_type.
- Training, exercise, workout duration, RPE, intensity -> workout and workout.exercises.
- Running/cardio distance and pace -> workout.distance_km and workout.pace; do not ask for sets/exercises for running.
- Parse flexible exercise phrasing into the same structure. Example: "squats 3 sets of 10 reps 100 kg" and "3sets 10 each squats with a 100 kg" both mean name=squat, sets=3, reps=10, load="100 kg".
- If workout exercise details are missing, leave them null; the backend may fill them from prior matching workouts.
- Energy, mood, stress, sleep, soreness, recovery -> wellbeing. Map qualitative values conservatively, e.g. energy low -> 3/10, stress low -> 3/10, destroyed -> wellbeing notes.
- Work sessions, career progress, project names, research, writing, blockers -> career.
- For meals, extract explicitly provided calories when present. If calories are absent, estimate average calories for a normal portion, set estimated=true, and keep confidence conservative.

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
    async def extract(
        self,
        text: str,
        entry_date: date,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    async def chat(self, text: str, context: dict[str, Any] | None = None) -> str: ...


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

    async def extract(
        self,
        text: str,
        entry_date: date,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        for model in (self.model, *self.fallback_models):
            try:
                return await self._extract_with_model(model, text, entry_date, context)
            except (
                asyncio.TimeoutError,
                httpx.HTTPError,
                json.JSONDecodeError,
                ValidationError,
                ValueError,
            ) as error:
                errors.append(f"{model}: {_format_error(error)}")

        raise ValueError("; ".join(errors))

    async def _extract_with_model(
        self,
        model: str,
        text: str,
        entry_date: date,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Target entry_date: {entry_date.isoformat()}\n\n"
                        f"Already logged context:\n{json.dumps(context or {}, sort_keys=True)}\n\n"
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

    async def chat(self, text: str, context: dict[str, Any] | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Context: {json.dumps(context or {})}\n\nUser says: {text}",
                },
            ],
            "temperature": 0.7,
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

        return response.json()["choices"][0]["message"]["content"]


class ExtractionService:
    def __init__(
        self,
        mode: str = settings.extractor,
        llm_client: LLMClient | None = None,
        langextract_client: LangExtractRunner | None = None,
    ):
        self.mode = mode
        self.llm_client = llm_client
        self.langextract_client = langextract_client

    async def extract(
        self,
        text: str,
        entry_date: date | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[ParsedDailyLog, str, str | None]:
        target_date = entry_date or date.today()

        if self.mode == "deterministic":
            return extract_daily_log(text, target_date), "deterministic", None

        langextract_error = None
        should_try_langextract = self.mode == "langextract" or (
            self.mode == "auto" and settings.langextract_enabled
        )
        if should_try_langextract:
            client = self.langextract_client or _configured_langextract_client()
            if client is None:
                langextract_error = "OPENROUTER_API_KEY is not configured for LangExtract"
                if self.mode == "langextract":
                    fallback = extract_daily_log(text, target_date)
                    return fallback, "deterministic", langextract_error
            else:
                try:
                    extractions = await asyncio.wait_for(
                        client.extract(text, target_date),
                        timeout=settings.llm_timeout_seconds,
                    )
                    if not extractions:
                        raise ValueError("LangExtract returned no grounded extractions")
                    parsed = parsed_log_from_langextract(extractions, target_date)
                    if not _has_structured_signal(parsed):
                        raise ValueError("LangExtract returned no supported life log fields")
                    _reconcile_with_deterministic(parsed, text, target_date)
                    if entry_date is not None:
                        parsed.entry_date = entry_date
                    return parsed, "langextract", None
                except Exception as error:
                    langextract_error = f"LangExtract failed: {_format_error(error)}"
                    if self.mode == "langextract":
                        fallback = extract_daily_log(text, target_date)
                        return fallback, "deterministic", langextract_error

        client = self.llm_client or _configured_llm_client()
        if client is None:
            if self.mode == "llm":
                fallback = extract_daily_log(text, target_date)
                return fallback, "deterministic", "OPENROUTER_API_KEY is not configured"
            return extract_daily_log(text, target_date), "deterministic", None

        try:
            parsed = ParsedDailyLog.model_validate(
                await _extract_with_optional_context(client, text, target_date, context)
            )
            if entry_date is not None:
                parsed.entry_date = entry_date
            _reconcile_with_deterministic(parsed, text, target_date)
            return parsed, "llm", None
        except (
            asyncio.TimeoutError,
            httpx.HTTPError,
            json.JSONDecodeError,
            ValidationError,
            ValueError,
        ) as error:
            fallback = extract_daily_log(text, target_date)
            prefix = f"{langextract_error}; " if langextract_error else ""
            return (
                fallback,
                "deterministic",
                f"{prefix}LLM extraction failed: {_format_error(error)}",
            )

    async def chat(self, text: str, context: dict[str, Any] | None = None) -> str:
        client = self.llm_client or _configured_llm_client()
        if client is None:
            return "Hi there! I'm your life logging assistant. (Connect an API key for more natural conversation!)"
        try:
            return await client.chat(text, context)
        except Exception:
            return "Hi! I'm here and ready to help you log your day."


def _configured_llm_client() -> OpenRouterClient | None:
    if not settings.openrouter_api_key:
        return None
    return OpenRouterClient(api_key=settings.openrouter_api_key)


def _configured_langextract_client() -> LangExtractClient | None:
    if not settings.openrouter_api_key:
        return None
    return LangExtractClient(api_key=settings.openrouter_api_key)


async def _extract_with_optional_context(
    client: LLMClient,
    text: str,
    target_date: date,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    parameters = inspect.signature(client.extract).parameters
    if "context" in parameters:
        return await client.extract(text, target_date, context=context)
    return await client.extract(text, target_date)


def _has_structured_signal(parsed: ParsedDailyLog) -> bool:
    return bool(
        parsed.wellbeing or parsed.nutrition or parsed.workout or parsed.career or parsed.journal
    )


def _reconcile_with_deterministic(parsed: ParsedDailyLog, text: str, target_date: date) -> None:
    deterministic = extract_daily_log(text, target_date)
    if deterministic.wellbeing:
        if parsed.wellbeing is None:
            parsed.wellbeing = deterministic.wellbeing
        else:
            for field in ("sleep_hours", "sleep_quality", "energy", "stress", "mood", "notes"):
                if getattr(parsed.wellbeing, field) is None:
                    setattr(parsed.wellbeing, field, getattr(deterministic.wellbeing, field))

    if deterministic.workout:
        if parsed.workout is None:
            parsed.workout = deterministic.workout
        else:
            for field in (
                "workout_type",
                "duration_min",
                "distance_km",
                "pace",
                "intensity",
                "notes",
            ):
                if getattr(parsed.workout, field) is None:
                    setattr(parsed.workout, field, getattr(deterministic.workout, field))
            if not parsed.workout.exercises and deterministic.workout.exercises:
                parsed.workout.exercises = deterministic.workout.exercises

    parsed.clarification_questions = build_followup_questions(parsed)


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
