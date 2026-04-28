from __future__ import annotations

import re

from backend.app.schemas import AgentMessageIn, AgentReply
from backend.app.workflow import AgentWorkflow, Intent, WorkflowResult


MODE_INTENTS: dict[str, Intent | None] = {
    "auto": None,
    "log": "log",
    "briefing": "briefing",
    "plot": "plot",
    "memory": "memory",
    "chat": "chat",
}

MODE_ASSUMPTIONS = {
    "auto": "Auto mode routed this message from its wording.",
    "log": "Log mode stores this as a daily record, even if it looks like a command.",
    "briefing": "Briefing mode treats this as a request for a summary, not a log.",
    "memory": "Memory mode looks only for durable preferences, strategies, goals, and reminders.",
    "plot": "Plot mode expects a chart request and leaves daily logs unchanged.",
    "chat": "Chat mode is for conversation and won't save any logs.",
}


async def process_agent_message(workflow: AgentWorkflow, message: AgentMessageIn) -> AgentReply:
    intent = MODE_INTENTS[message.mode]
    result = await workflow.process_text(
        message.text,
        source=message.source,
        entry_date=message.entry_date,
        forced_intent=intent,
    )
    return build_agent_reply(message, result)


def build_agent_reply(message: AgentMessageIn, result: WorkflowResult) -> AgentReply:
    return AgentReply(
        ok=result.ok,
        status=result.status,
        mode=message.mode,
        tone=message.tone,
        confirmation=apply_tone(result.confirmation, message.tone),
        assumption=MODE_ASSUMPTIONS.get(message.mode),
        raw_message_id=result.raw_message_id,
        parsed=result.parsed,
        records=result.records or {},
        extraction_method=result.extraction_method,
        extraction_error=result.extraction_error,
        learned_memory_count=result.learned_memory_count,
        plot_count=len(result.plot_results),
    )


def apply_tone(text: str | None, tone: str) -> str | None:
    if text is None:
        return None
    if tone == "terse":
        # Extract the first line, but strip MarkdownV2 formatting for a clean summary
        # unless it's a simple bold header.
        first_line = text.splitlines()[0]
        # Remove emojis and specific markdown for the terse version to keep it "minimal"
        clean = re.sub(r"[✅🧠✨🏃📖❓⚠️] ", "", first_line)
        clean = clean.replace("*", "").replace("`", "").replace("\\", "")
        return clean
    return text
