from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, TypedDict

from backend.app.agent_planning import (
    AgentPlan,
    AgentPlanner,
    PlannedAction,
    configured_agent_planner,
)
from backend.app.briefing import Briefing, BriefingService, is_briefing_request
from backend.app.db import LifeDatabase
from backend.app.deletion import DeleteResult, handle_delete_request, is_delete_request
from backend.app.extraction import contains_non_logging_reply, is_non_logging_reply
from backend.app.llm_extraction import ExtractionService
from backend.app.memory import MemoryService, is_memory_request
from backend.app.plotting import PlotResult, PlotService, parse_plot_requests
from backend.app.schemas import MessageIn, ParsedDailyLog

logger = logging.getLogger(__name__)


Intent = Literal["ignore", "memory", "delete", "briefing", "plot", "log", "chat"]


class WorkflowState(TypedDict, total=False):
    text: str
    source: str
    entry_date: date | None
    intent: Intent
    result: "WorkflowResult"


@dataclass(frozen=True)
class WorkflowResult:
    ok: bool
    status: str
    confirmation: str | None = None
    raw_message_id: int | None = None
    parsed: ParsedDailyLog | None = None
    records: dict[str, list[dict[str, Any]]] | None = None
    extraction_method: str | None = None
    extraction_error: str | None = None
    plot_results: tuple[PlotResult, ...] = ()
    briefing: Briefing | None = None
    deletion: DeleteResult | None = None
    learned_memory_count: int = 0
    action_results: tuple["WorkflowResult", ...] = ()
    duplicate_note: str | None = None


class AgentWorkflow:
    def __init__(
        self,
        db: LifeDatabase,
        extractor: ExtractionService,
        plotter: PlotService,
        memory_service: MemoryService,
        briefing_service: BriefingService,
        planner: AgentPlanner | None = None,
        use_configured_planner: bool = True,
    ) -> None:
        self.db = db
        self.extractor = extractor
        self.plotter = plotter
        self.memory_service = memory_service
        self.briefing_service = briefing_service
        self.planner = planner or (configured_agent_planner() if use_configured_planner else None)
        self._graph = self._build_graph()

    async def process_text(
        self,
        text: str,
        *,
        source: str,
        entry_date: date | None,
        forced_intent: Intent | None = None,
    ) -> WorkflowResult:
        state: WorkflowState = {"text": text, "source": source, "entry_date": entry_date}
        if forced_intent is not None:
            state["intent"] = forced_intent
            state = await self._execute_without_graph(state)
            return state["result"]

        plan = await self._plan_actions(state)
        if plan is not None:
            return await self._execute_plan(state, plan)

        if self._graph is not None:
            final_state = await self._graph.ainvoke(state)
            return final_state["result"]

        state = await self._classify(state)
        state = await self._execute_without_graph(state)
        return state["result"]

    async def log_text(
        self,
        text: str,
        *,
        source: str,
        entry_date: date | None,
    ) -> WorkflowResult:
        return await self.process_text(
            text,
            source=source,
            entry_date=entry_date,
            forced_intent="log",
        )

    async def _plan_actions(self, state: WorkflowState) -> AgentPlan | None:
        if self.planner is None:
            return None
        try:
            return await self.planner.plan(
                state["text"],
                context=self._planning_context(state.get("entry_date")),
            )
        except Exception:
            logger.exception("Agent planner failed; falling back to deterministic classification")
            return None

    async def _execute_plan(self, state: WorkflowState, plan: AgentPlan) -> WorkflowResult:
        actions = [
            action for action in plan.actions if action.intent != "ignore" or len(plan.actions) == 1
        ]
        if not actions:
            actions = [PlannedAction(intent="ignore", text=state["text"])]

        results = []
        for action in actions:
            action_state: WorkflowState = {
                "text": action.text or state["text"],
                "source": state["source"],
                "entry_date": state.get("entry_date"),
                "intent": action.intent,
            }
            final_state = await self._execute_without_graph(action_state)
            results.append(final_state["result"])

        if len(results) == 1:
            return results[0]
        return _combine_action_results(tuple(results), plan)

    def _build_graph(self) -> Any | None:
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError:
            return None

        builder = StateGraph(WorkflowState)
        builder.add_node("classify", self._classify)
        builder.add_node("ignore", self._run_ignore)
        builder.add_node("memory", self._run_memory)
        builder.add_node("delete", self._run_delete)
        builder.add_node("briefing", self._run_briefing)
        builder.add_node("plot", self._run_plot)
        builder.add_node("log", self._run_log)
        builder.add_edge(START, "classify")
        builder.add_conditional_edges(
            "classify",
            _route_intent,
            {
                "ignore": "ignore",
                "memory": "memory",
                "delete": "delete",
                "briefing": "briefing",
                "plot": "plot",
                "log": "log",
            },
        )
        for node in ("ignore", "memory", "delete", "briefing", "plot", "log"):
            builder.add_edge(node, END)
        return builder.compile()

    async def _execute_without_graph(self, state: WorkflowState) -> WorkflowState:
        intent = state["intent"]
        if intent == "ignore":
            return await self._run_ignore(state)
        if intent == "memory":
            return await self._run_memory(state)
        if intent == "delete":
            return await self._run_delete(state)
        if intent == "briefing":
            return await self._run_briefing(state)
        if intent == "plot":
            return await self._run_plot(state)
        if intent == "chat":
            return await self._run_chat(state)
        return await self._run_log(state)

    async def _classify(self, state: WorkflowState) -> WorkflowState:
        text = state["text"]
        lower = text.lower().strip()
        if lower in {"hey", "hi", "hello", "how are you", "how are you?", "yo"}:
            return {"intent": "chat"}
        if contains_non_logging_reply(text) and is_briefing_request(text):
            return {"intent": "briefing"}
        if is_non_logging_reply(text):
            return {"intent": "ignore"}
        if is_memory_request(text):
            return {"intent": "memory"}
        if is_delete_request(text):
            return {"intent": "delete"}
        if is_briefing_request(text):
            return {"intent": "briefing"}
        if parse_plot_requests(text):
            return {"intent": "plot"}
        return {"intent": "log"}

    async def _run_ignore(self, state: WorkflowState) -> WorkflowState:
        return {
            "result": WorkflowResult(
                ok=True,
                status="ignored_non_logging_reply",
                confirmation="Got it. I left the log unchanged.",
            )
        }

    async def _run_memory(self, state: WorkflowState) -> WorkflowState:
        learned = self.memory_service.learn_from_message(state["text"])
        return {
            "result": WorkflowResult(
                ok=True,
                status="memory_updated",
                confirmation=format_memory_confirmation(learned),
                learned_memory_count=len(learned),
            )
        }

    async def _run_delete(self, state: WorkflowState) -> WorkflowState:
        deletion = handle_delete_request(
            self.db,
            state["text"],
            entry_date=state.get("entry_date"),
        )
        return {
            "result": WorkflowResult(
                ok=deletion.ok,
                status=deletion.status,
                confirmation=deletion.confirmation,
                deletion=deletion,
            )
        }

    async def _run_briefing(self, state: WorkflowState) -> WorkflowState:
        briefing = await self.briefing_service.generate(state.get("entry_date"))
        return {
            "result": WorkflowResult(
                ok=True,
                status="briefing_sent",
                confirmation=briefing.text,
                briefing=briefing,
            )
        }

    async def _run_plot(self, state: WorkflowState) -> WorkflowState:
        requests = parse_plot_requests(state["text"])
        plots = tuple(self.plotter.generate(request) for request in requests)
        captions = [f"{plot.title} ({plot.detail})" for plot in plots]
        confirmation = captions[0] if len(captions) == 1 else f"I made {len(captions)} plots."
        return {
            "result": WorkflowResult(
                ok=True,
                status="plot_sent",
                confirmation=confirmation,
                plot_results=plots,
            )
        }

    async def _run_chat(self, state: WorkflowState) -> WorkflowState:
        response = await self.extractor.chat(state["text"], context=self._planning_context(None))
        return {
            "result": WorkflowResult(
                ok=True,
                status="completed_actions",
                confirmation=response,
            )
        }

    async def _run_log(self, state: WorkflowState) -> WorkflowState:
        entry_date = state.get("entry_date")
        context = self._planning_context(entry_date)
        parsed, method, error = await self.extractor.extract(
            state["text"],
            entry_date,
            context=context,
        )
        saved = self.db.save_message(
            MessageIn(text=state["text"], entry_date=entry_date, source=state["source"]),
            parsed,
        )
        learned = self.memory_service.learn_from_message(
            state["text"], parsed, saved["raw_message_id"]
        )
        confirmation = format_log_confirmation(saved["raw_message_id"], parsed, method, error)
        duplicate_note = format_duplicate_note(parsed, saved["records"])
        if duplicate_note:
            confirmation += "\n" + duplicate_note
        if learned:
            confirmation += "\n" + format_learned_memory_note(learned)
        return {
            "result": WorkflowResult(
                ok=True,
                status="logged",
                confirmation=confirmation,
                raw_message_id=saved["raw_message_id"],
                parsed=parsed,
                records=saved["records"],
                extraction_method=method,
                extraction_error=error,
                learned_memory_count=len(learned),
                duplicate_note=duplicate_note,
            )
        }

    def _planning_context(self, entry_date: date | None) -> dict[str, Any]:
        logs = self.db.recent_logs(limit=40)
        target_date = entry_date.isoformat() if entry_date else None
        return {
            "target_date": target_date,
            "same_day_logs": _logs_for_date(logs, target_date),
            "recent_logs": _compact_recent_logs(logs),
            "memory": self.memory_service.briefing_context(),
        }


def _route_intent(state: WorkflowState) -> Intent:
    return state.get("intent", "log")


def _combine_action_results(results: tuple[WorkflowResult, ...], plan: AgentPlan) -> WorkflowResult:
    confirmations = [result.confirmation for result in results if result.confirmation]
    if plan.duplicate_hint:
        confirmations.append(f"Context: {plan.duplicate_hint}")

    records: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        for key, values in (result.records or {}).items():
            records.setdefault(key, []).extend(values)

    return WorkflowResult(
        ok=all(result.ok for result in results),
        status="completed_actions",
        confirmation="\n\n".join(confirmations) if confirmations else None,
        raw_message_id=next(
            (result.raw_message_id for result in results if result.raw_message_id), None
        ),
        parsed=next((result.parsed for result in results if result.parsed is not None), None),
        records=records or None,
        extraction_method=next(
            (result.extraction_method for result in results if result.extraction_method),
            None,
        ),
        extraction_error=next(
            (result.extraction_error for result in results if result.extraction_error),
            None,
        ),
        plot_results=tuple(plot for result in results for plot in result.plot_results),
        briefing=next((result.briefing for result in results if result.briefing is not None), None),
        deletion=next((result.deletion for result in results if result.deletion is not None), None),
        learned_memory_count=sum(result.learned_memory_count for result in results),
        action_results=results,
    )


def escape_markdown(text: str) -> str:
    """Escapes characters reserved by Telegram's MarkdownV2."""
    reserved = r"_*[]()~`>#+-=|{}.!"
    for char in reserved:
        text = text.replace(char, f"\\{char}")
    return text


def format_log_confirmation(
    raw_message_id: int,
    parsed: ParsedDailyLog,
    method: str,
    error: str | None,
) -> str:
    # Use emojis and bold text for a cleaner look
    header = f"✅ *Logged {parsed.date:%b %d}* as `#{raw_message_id}`"
    lines = [header]

    if parsed.wellbeing:
        bits = []
        if parsed.wellbeing.sleep_hours is not None:
            bits.append(f"💤 {parsed.wellbeing.sleep_hours:g}h")
        if parsed.wellbeing.energy is not None:
            bits.append(f"⚡️ {parsed.wellbeing.energy}/10")
        if parsed.wellbeing.stress is not None:
            bits.append(f"🧗 {parsed.wellbeing.stress}/10")
        if parsed.wellbeing.mood is not None:
            bits.append(f"🎭 {parsed.wellbeing.mood}/10")
        if bits:
            lines.append(" ".join(bits))
        if parsed.wellbeing.notes:
            lines.append(f"📝 _{escape_markdown(parsed.wellbeing.notes)}_")

    if parsed.nutrition:
        lines.append("\n*Nutrition*")
        for item in parsed.nutrition[:4]:
            meal = f"_{escape_markdown(item.meal_type)}_: " if item.meal_type else ""
            macro_bits = []
            if item.calories is not None:
                macro_bits.append(f"{item.calories:g} cal")
            if item.protein_g is not None:
                marker = "~" if item.estimated else ""
                macro_bits.append(f"{marker}{item.protein_g:g}g protein")
            suffix = f" \\({', '.join(macro_bits)}\\)" if macro_bits else ""
            lines.append(f"• {meal}{escape_markdown(item.description)}{suffix}")

    if parsed.workout:
        workout = escape_markdown(parsed.workout.workout_type or "workout")
        details = []
        if parsed.workout.distance_km is not None:
            details.append(f"{parsed.workout.distance_km:g} km")
        if parsed.workout.pace is not None:
            details.append(f"pace {parsed.workout.pace:g}")
        if parsed.workout.duration_min is not None:
            details.append(f"{parsed.workout.duration_min:g} min")
        suffix = f" \\({', '.join(details)}\\)" if details else ""
        lines.append(f"\n🏃 *{workout}*{suffix}")
        for exercise in parsed.workout.exercises[:5]:
            if exercise.sets and exercise.reps:
                load = f" at {escape_markdown(exercise.load)}" if exercise.load else ""
                lines.append(f"  ◦ {escape_markdown(exercise.name)}: {exercise.sets}x{exercise.reps}{load}")
            elif exercise.duration_min:
                lines.append(f"  ◦ {escape_markdown(exercise.name)}: {exercise.duration_min:g} min")

    if parsed.career:
        lines.append("\n*Career*")
        for item in parsed.career[:3]:
            duration = f"{item.duration_hours:g}h " if item.duration_hours is not None else ""
            project = escape_markdown(item.project or "work")
            progress = f" — {escape_markdown(item.progress_note)}" if item.progress_note else ""
            lines.append(f"• {duration}on *{project}*{progress}")

    if parsed.journal:
        tag_text = f" `[{', '.join(map(escape_markdown, parsed.journal.tags))}]`" if parsed.journal.tags else ""
        lines.append(f"\n📖 *Journal*: saved{tag_text}")

    if parsed.clarification_questions:
        label = "❓ *Question*" if len(parsed.clarification_questions) == 1 else "❓ *Questions*"
        lines.append("\n" + label)
        for question in parsed.clarification_questions[:2]:
            lines.append(f"• {escape_markdown(question)}")

    if error:
        lines.append(f"\n⚠️ _Extraction note: {escape_markdown(method)} fallback handled this because {escape_markdown(error)}_")

    return "\n".join(lines)


def format_duplicate_note(
    parsed: ParsedDailyLog, records: dict[str, list[dict[str, Any]]]
) -> str | None:
    skipped: list[str] = []
    if parsed.wellbeing and not records.get("daily_checkins"):
        skipped.append(_summarize_wellbeing_dup(parsed.wellbeing))
    if parsed.nutrition:
        kept_descriptions = {
            (row.get("meal_type"), (row.get("description") or "").lower())
            for row in records.get("nutrition") or []
        }
        for item in parsed.nutrition:
            key = (item.meal_type, (item.description or "").lower())
            if key in kept_descriptions:
                continue
            label = item.meal_type or "meal"
            description = item.description or "?"
            skipped.append(f"{label}: {description}")
    if parsed.workout and not records.get("workout") and not records.get("workout_exercises"):
        skipped.append(_summarize_workout_dup(parsed.workout))
    if parsed.career:
        kept_projects = {
            (row.get("project"), row.get("progress_note")) for row in records.get("career") or []
        }
        for item in parsed.career:
            if (item.project, item.progress_note) in kept_projects:
                continue
            project = item.project or "career"
            note = f" — {item.progress_note}" if item.progress_note else ""
            skipped.append(f"{project}{note}")
    if parsed.journal and not records.get("journal"):
        skipped.append(_truncate_journal(parsed.journal.text))
    if not skipped:
        return None
    return "💡 *Already logged (skipped)*: " + escape_markdown("; ".join(skipped)) + "."


def _summarize_wellbeing_dup(item: Any) -> str:
    parts: list[str] = []
    if item.sleep_hours is not None:
        parts.append(f"sleep {item.sleep_hours:g}h")
    if item.energy is not None:
        parts.append(f"energy {item.energy}/10")
    if item.stress is not None:
        parts.append(f"stress {item.stress}/10")
    if item.mood is not None:
        parts.append(f"mood {item.mood}/10")
    return "wellbeing (" + ", ".join(parts) + ")" if parts else "wellbeing"


def _summarize_workout_dup(item: Any) -> str:
    name = item.workout_type or "workout"
    if item.duration_min is not None:
        return f"{name} ({item.duration_min:g} min)"
    if item.distance_km is not None:
        return f"{name} ({item.distance_km:g} km)"
    return name


def _truncate_journal(text: str, limit: int = 60) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return f"journal: {compact}"
    return f"journal: {compact[: limit - 1].rstrip()}..."


def format_memory_confirmation(items: list[dict[str, Any]]) -> str:
    if not items:
        return "🧠 I didn't find any durable preferences or strategies to remember. Try phrasing it as: _\"Remember that briefings should be direct and concise.\"_"
    lines = [f"🧠 *I will remember {len(items)} item(s)*:"]
    for item in items[:4]:
        lines.append(f"• _{escape_markdown(item['category'])}_: {escape_markdown(item['value'])}")
    return "\n".join(lines)


def format_learned_memory_note(items: list[dict[str, Any]]) -> str:
    if len(items) == 1:
        item = items[0]
        return f"✨ *Also remembered*: {escape_markdown(item['value'])}."
    return f"✨ *Also remembered {len(items)} durable preferences or strategies*."



def _logs_for_date(
    logs: dict[str, list[dict[str, Any]]], target_date: str | None
) -> dict[str, list[dict[str, Any]]]:
    if target_date is None:
        return {}
    return {
        kind: [_compact_log_row(kind, row) for row in rows if _row_date(row) == target_date][:8]
        for kind, rows in logs.items()
        if kind != "raw_messages"
    }


def _compact_recent_logs(logs: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {
        kind: [_compact_log_row(kind, row) for row in rows[:6]]
        for kind, rows in logs.items()
        if kind in {"raw_messages", "nutrition", "workout", "career", "daily_checkins"}
    }


def _compact_log_row(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "raw_messages": ("id", "entry_date", "source", "text"),
        "daily_checkins": ("id", "date", "sleep_hours", "energy", "stress", "mood", "notes"),
        "nutrition": ("id", "date", "meal_type", "description", "calories", "protein_g"),
        "workout": ("id", "date", "workout_type", "duration_min", "distance_km", "pace", "notes"),
        "workout_exercises": ("id", "date", "name", "sets", "reps", "load", "duration_min"),
        "career": ("id", "date", "project", "activity", "duration_hours", "progress_note"),
        "journal": ("id", "date", "text", "tags_json"),
    }.get(kind, ("id", "date", "entry_date"))
    return {key: row.get(key) for key in keys if row.get(key) not in (None, "")}


def _row_date(row: dict[str, Any]) -> str | None:
    return row.get("date") or row.get("entry_date")
