"""Shared helpers for OpenRouter chat-completion responses."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.app.config import settings


def decode_response_json(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the first choice's message content as a JSON object."""
    for choice in payload.get("choices", []):
        message = choice.get("message", {})
        content = message.get("content")
        if isinstance(content, dict):
            return content
        if isinstance(content, str):
            return json.loads(content)
    raise ValueError("Could not find structured JSON in LLM response")


def format_error(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return f"OpenRouter request exceeded {settings.llm_timeout_seconds:g}s timeout"
    message = str(error).strip()
    return message or error.__class__.__name__
