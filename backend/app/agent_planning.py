from __future__ import annotations

import asyncio
import json
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from backend.app.config import settings


PlannedIntent = Literal["ignore", "memory", "delete", "briefing", "plot", "log"]


PLANNER_SYSTEM_PROMPT = """
You are the planning layer for a personal life logging assistant.

Decide what the user's message is asking the app to do. Return only JSON.

The user can ask for more than one thing in the same message. Preserve that by
returning ordered actions. Examples:
- "Energy 7, stress 4 and give me a brief" -> log, briefing
- "delete my last meal and plot protein" -> delete, plot
- "remember that I like concise briefings and log sleep 7h" -> memory, log

Use recent_logs and same_day_logs to decide whether the user appears to be
repeating information that is already logged. Do not invent database changes.

Action guidance:
- log: the user gives new life data, corrections, follow-up answers, or journal content.
- briefing: the user asks for a morning/daily brief or summary.
- delete: the user asks to delete/remove logs.
- plot: the user asks for a chart, graph, or trend.
- memory: the user asks the assistant to remember a durable preference, goal, or strategy.
- ignore: the user declines to provide more info without asking for another action.

For each action, set text to the exact part of the message that action should
operate on. For a log action, exclude plot/delete/briefing command text when
possible.
""".strip()


class PlannedAction(BaseModel):
    intent: PlannedIntent
    text: str = Field(min_length=1)
    reason: str | None = None


class AgentPlan(BaseModel):
    actions: list[PlannedAction] = Field(default_factory=list)
    duplicate_hint: str | None = None


class AgentPlanner(Protocol):
    async def plan(
        self,
        text: str,
        *,
        context: dict[str, Any],
    ) -> AgentPlan: ...


class OpenRouterAgentPlanner:
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

    async def plan(
        self,
        text: str,
        *,
        context: dict[str, Any],
    ) -> AgentPlan:
        errors: list[str] = []
        for model in (self.model, *self.fallback_models):
            try:
                return await self._plan_with_model(model, text, context)
            except (
                asyncio.TimeoutError,
                httpx.HTTPError,
                json.JSONDecodeError,
                ValidationError,
                ValueError,
            ) as error:
                errors.append(f"{model}: {_format_error(error)}")
        raise ValueError("; ".join(errors))

    async def _plan_with_model(self, model: str, text: str, context: dict[str, Any]) -> AgentPlan:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": text,
                            "context": context,
                        },
                        sort_keys=True,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_plan",
                    "strict": False,
                    "schema": AgentPlan.model_json_schema(),
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

        plan = AgentPlan.model_validate(_decode_response_json(response.json()))
        return _clean_plan(plan, text)


def configured_agent_planner() -> OpenRouterAgentPlanner | None:
    if not settings.openrouter_api_key:
        return None
    return OpenRouterAgentPlanner(api_key=settings.openrouter_api_key)


def _clean_plan(plan: AgentPlan, fallback_text: str) -> AgentPlan:
    actions = []
    for action in plan.actions[:5]:
        text = " ".join(action.text.split()) or fallback_text
        actions.append(PlannedAction(intent=action.intent, text=text, reason=action.reason))
    if not actions:
        actions = [PlannedAction(intent="log", text=fallback_text)]
    return AgentPlan(actions=actions, duplicate_hint=plan.duplicate_hint)


def _decode_response_json(payload: dict[str, Any]) -> dict[str, Any]:
    for choice in payload.get("choices", []):
        message = choice.get("message", {})
        content = message.get("content")
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            return json.loads(content)
    raise ValueError("Could not find structured JSON in planner response")


def _format_error(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return f"OpenRouter request exceeded {settings.llm_timeout_seconds:g}s timeout"
    message = str(error).strip()
    return message or error.__class__.__name__
