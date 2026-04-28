from __future__ import annotations

import json
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import httpx
from pydantic import ValidationError

from backend.app.agent_planning import (
    AgentPlan,
    OpenRouterAgentPlanner,
    PlannedAction,
    _clean_plan,
    _decode_response_json,
)


def _openrouter_response(plan: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(plan)}}]}


class CleanPlanTests(TestCase):
    def test_collapses_whitespace_and_caps_actions(self) -> None:
        actions = [PlannedAction(intent="log", text=f"  msg {i}  ") for i in range(7)]
        cleaned = _clean_plan(AgentPlan(actions=actions), fallback_text="fallback")

        self.assertEqual(len(cleaned.actions), 5)
        self.assertEqual(cleaned.actions[0].text, "msg 0")

    def test_empty_actions_falls_back_to_log(self) -> None:
        cleaned = _clean_plan(AgentPlan(actions=[]), fallback_text="hello")

        self.assertEqual(len(cleaned.actions), 1)
        self.assertEqual(cleaned.actions[0].intent, "log")
        self.assertEqual(cleaned.actions[0].text, "hello")

    def test_blank_text_uses_fallback(self) -> None:
        actions = [PlannedAction(intent="briefing", text="x")]
        # Manually break the text after construction to simulate a model returning whitespace.
        object.__setattr__(actions[0], "text", "   ")
        cleaned = _clean_plan(AgentPlan(actions=actions), fallback_text="default")

        self.assertEqual(cleaned.actions[0].text, "default")


class DecodeResponseTests(TestCase):
    def test_extracts_json_from_string_content(self) -> None:
        payload = _openrouter_response({"actions": [{"intent": "log", "text": "x"}]})

        decoded = _decode_response_json(payload)

        self.assertEqual(decoded["actions"][0]["intent"], "log")

    def test_extracts_dict_content(self) -> None:
        payload = {
            "choices": [{"message": {"content": {"actions": [{"intent": "memory", "text": "y"}]}}}]
        }

        decoded = _decode_response_json(payload)

        self.assertEqual(decoded["actions"][0]["intent"], "memory")

    def test_missing_content_raises(self) -> None:
        with self.assertRaises(ValueError):
            _decode_response_json({"choices": []})


class PlannerHTTPTests(IsolatedAsyncioTestCase):
    async def test_single_intent_round_trips(self) -> None:
        planner = OpenRouterAgentPlanner(api_key="test", fallback_models=())
        response_payload = _openrouter_response(
            {"actions": [{"intent": "log", "text": "energy 7"}]}
        )

        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            mock_post.return_value = httpx.Response(
                200,
                json=response_payload,
                request=httpx.Request("POST", "https://example/chat/completions"),
            )

            plan = await planner.plan("energy 7", context={})

        self.assertEqual(len(plan.actions), 1)
        self.assertEqual(plan.actions[0].intent, "log")
        self.assertEqual(plan.actions[0].text, "energy 7")

    async def test_multi_intent_round_trips(self) -> None:
        planner = OpenRouterAgentPlanner(api_key="test", fallback_models=())
        response_payload = _openrouter_response(
            {
                "actions": [
                    {"intent": "log", "text": "energy 7"},
                    {"intent": "briefing", "text": "morning brief"},
                ],
                "duplicate_hint": None,
            }
        )

        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            mock_post.return_value = httpx.Response(
                200,
                json=response_payload,
                request=httpx.Request("POST", "https://example/chat/completions"),
            )

            plan = await planner.plan("energy 7 and brief me", context={})

        intents = [action.intent for action in plan.actions]
        self.assertEqual(intents, ["log", "briefing"])

    async def test_malformed_json_raises_after_models_exhausted(self) -> None:
        planner = OpenRouterAgentPlanner(api_key="test", fallback_models=())

        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            mock_post.return_value = httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not json"}}]},
                request=httpx.Request("POST", "https://example/chat/completions"),
            )

            with self.assertRaises(ValueError):
                await planner.plan("anything", context={})

    async def test_validation_error_when_intent_missing(self) -> None:
        planner = OpenRouterAgentPlanner(api_key="test", fallback_models=())
        response_payload = _openrouter_response({"actions": [{"text": "no intent here"}]})

        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            mock_post.return_value = httpx.Response(
                200,
                json=response_payload,
                request=httpx.Request("POST", "https://example/chat/completions"),
            )

            # The planner aggregates errors across models then raises ValueError.
            with self.assertRaises((ValueError, ValidationError)):
                await planner.plan("anything", context={})

    async def test_falls_back_to_secondary_model_on_first_failure(self) -> None:
        planner = OpenRouterAgentPlanner(
            api_key="test",
            model="primary",
            fallback_models=("secondary",),
        )

        good = httpx.Response(
            200,
            json=_openrouter_response({"actions": [{"intent": "memory", "text": "remember x"}]}),
            request=httpx.Request("POST", "https://example/chat/completions"),
        )
        bad = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "garbage"}}]},
            request=httpx.Request("POST", "https://example/chat/completions"),
        )

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=[bad, good])):
            plan = await planner.plan("remember x", context={})

        self.assertEqual(plan.actions[0].intent, "memory")


class ConfiguredPlannerTests(TestCase):
    def test_returns_none_when_unconfigured(self) -> None:
        from backend.app.agent_planning import configured_agent_planner

        with patch("backend.app.agent_planning.settings") as mock_settings:
            mock_settings.openrouter_api_key = ""
            self.assertIsNone(configured_agent_planner())
