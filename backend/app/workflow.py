from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, TypedDict

from backend.app.briefing import Briefing, BriefingService, is_briefing_request
from backend.app.db import LifeDatabase
from backend.app.deletion import DeleteResult, handle_delete_request, is_delete_request
from backend.app.extraction import contains_non_logging_reply, is_non_logging_reply
from backend.app.llm_extraction import ExtractionService
from backend.app.memory import MemoryService, is_memory_request
from backend.app.plotting import PlotResult, PlotService, parse_plot_requests
from backend.app.schemas import MessageIn, ParsedDailyLog


Intent = Literal["ignore", "memory", "delete", "briefing", "plot", "log"]


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


class AgentWorkflow:
    def __init__(
        self,
        db: LifeDatabase,
        extractor: ExtractionService,
        plotter: PlotService,
        memory_service: MemoryService,
        briefing_service: BriefingService,
    ) -> None:
        self.db = db
        self.extractor = extractor
        self.plotter = plotter
        self.memory_service = memory_service
        self.briefing_service = briefing_service
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
        return await self._run_log(state)

    async def _classify(self, state: WorkflowState) -> WorkflowState:
        text = state["text"]
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

    async def _run_log(self, state: WorkflowState) -> WorkflowState:
        entry_date = state.get("entry_date")
        parsed, method, error = await self.extractor.extract(state["text"], entry_date)
        saved = self.db.save_message(
            MessageIn(text=state["text"], entry_date=entry_date, source=state["source"]),
            parsed,
        )
        learned = self.memory_service.learn_from_message(state["text"], parsed, saved["raw_message_id"])
        confirmation = format_log_confirmation(saved["raw_message_id"], parsed, method, error)
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
            )
        }


def _route_intent(state: WorkflowState) -> Intent:
    return state.get("intent", "log")


def format_log_confirmation(
    raw_message_id: int,
    parsed: ParsedDailyLog,
    method: str,
    error: str | None,
) -> str:
    lines = [f"Logged {parsed.date:%b %-d} as #{raw_message_id}."]
    if parsed.wellbeing:
        wellbeing = []
        if parsed.wellbeing.sleep_hours is not None:
            wellbeing.append(f"sleep {parsed.wellbeing.sleep_hours:g}h")
        if parsed.wellbeing.energy is not None:
            wellbeing.append(f"energy {parsed.wellbeing.energy}/10")
        if parsed.wellbeing.stress is not None:
            wellbeing.append(f"stress {parsed.wellbeing.stress}/10")
        if parsed.wellbeing.mood is not None:
            wellbeing.append(f"mood {parsed.wellbeing.mood}/10")
        if wellbeing:
            lines.append("Wellbeing: " + ", ".join(wellbeing))
        if parsed.wellbeing.notes:
            lines.append(f"Note: {parsed.wellbeing.notes}")

    if parsed.nutrition:
        lines.append("Nutrition:")
        for item in parsed.nutrition[:4]:
            meal = f"{item.meal_type}: " if item.meal_type else ""
            macro_bits = []
            if item.calories is not None:
                macro_bits.append(f"{item.calories:g} cal")
            if item.protein_g is not None:
                marker = "~" if item.estimated else ""
                macro_bits.append(f"{marker}{item.protein_g:g}g protein")
            suffix = f" ({', '.join(macro_bits)})" if macro_bits else ""
            lines.append(f"- {meal}{item.description}{suffix}")

    if parsed.workout:
        workout = parsed.workout.workout_type or "workout"
        details = []
        if parsed.workout.distance_km is not None:
            details.append(f"{parsed.workout.distance_km:g} km")
        if parsed.workout.pace is not None:
            details.append(f"pace {parsed.workout.pace:g}")
        if parsed.workout.duration_min is not None:
            details.append(f"{parsed.workout.duration_min:g} min")
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"Workout: {workout}{suffix}")
        for exercise in parsed.workout.exercises[:5]:
            if exercise.sets and exercise.reps:
                load = f" at {exercise.load}" if exercise.load else ""
                lines.append(f"- {exercise.name}: {exercise.sets}x{exercise.reps}{load}")
            elif exercise.duration_min:
                lines.append(f"- {exercise.name}: {exercise.duration_min:g} min")

    if parsed.career:
        lines.append("Career:")
        for item in parsed.career[:3]:
            duration = f"{item.duration_hours:g}h " if item.duration_hours is not None else ""
            project = item.project or "work"
            progress = f" - {item.progress_note}" if item.progress_note else ""
            lines.append(f"- {duration}on {project}{progress}")

    if parsed.journal:
        tag_text = f" [{', '.join(parsed.journal.tags)}]" if parsed.journal.tags else ""
        lines.append(f"Journal: saved{tag_text}")

    if parsed.clarification_questions:
        label = "Question" if len(parsed.clarification_questions) == 1 else "Questions"
        lines.append(label + ":")
        for question in parsed.clarification_questions[:2]:
            lines.append(f"- {question}")
    if error:
        lines.append(f"Extraction note: {method} fallback handled this because {error}")
    return "\n".join(lines)


def format_memory_confirmation(items: list[dict[str, Any]]) -> str:
    if not items:
        return "I did not find a durable preference or strategy to remember. Try phrasing it as: remember that briefings should be direct and concise."
    lines = [f"I will remember {len(items)} item(s)."]
    for item in items[:4]:
        lines.append(f"- {item['category']}: {item['value']}")
    return "\n".join(lines)


def format_learned_memory_note(items: list[dict[str, Any]]) -> str:
    if len(items) == 1:
        item = items[0]
        return f"Also remembered: {item['value']}."
    return f"Also remembered {len(items)} durable preferences or strategies."
