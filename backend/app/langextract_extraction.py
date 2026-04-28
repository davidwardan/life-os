from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Protocol

from backend.app.config import settings
from backend.app.followup import build_followup_questions
from backend.app.schemas import (
    CareerEntry,
    ExerciseEntry,
    JournalEntry,
    NutritionEntry,
    ParsedDailyLog,
    WellbeingEntry,
    WorkoutEntry,
)


LANGEXTRACT_PROMPT = """
Extract personal life log facts in order of appearance.

Rules:
- Use exact text spans from the input for every extraction.
- Do not extract facts that are only in the examples.
- Do not paraphrase extraction_text.
- Put normalized values in attributes.
- Use null only by omitting unknown attributes.
- Mark values as explicit when directly stated.
- Mark calories or macros as estimated only when inferred.

Extraction classes:
- wellbeing_metric: sleep, energy, stress, mood, sleep_quality, fatigue/recovery notes.
- meal: meals, food, calories, protein, carbs, fats, meal timing.
- workout: workout type, duration, distance, pace, intensity, broad training note.
- exercise: exercise name, sets, reps, load, duration.
- career: work session, project, activity, duration, progress, blockers.
- journal: subjective reflection, mood note, durable tags.

Useful attributes:
- date
- metric, value, unit, confidence
- meal_type, calories, protein_g, carbs_g, fat_g, estimated, confidence
- workout_type, duration_min, distance_km, pace, intensity, confidence
- name, sets, reps, load, notes
- project, activity, duration_hours, progress_note, blockers
- text, tags, sentiment
""".strip()


class LangExtractRunner(Protocol):
    async def extract(self, text: str, entry_date: date) -> list[Any]: ...


class LangExtractClient:
    def __init__(
        self,
        api_key: str,
        model: str = settings.langextract_model,
        base_url: str = settings.openrouter_base_url,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def extract(self, text: str, entry_date: date) -> list[Any]:
        return await asyncio.to_thread(self._extract_sync, text, entry_date)

    def _extract_sync(self, text: str, entry_date: date) -> list[Any]:
        try:
            import langextract as lx
            from langextract.factory import ModelConfig
        except ImportError as error:
            raise RuntimeError(
                "langextract is not installed. Install dependencies with `pip install -e .`."
            ) from error

        result = lx.extract(
            text_or_documents=text,
            prompt_description=LANGEXTRACT_PROMPT,
            examples=_examples(lx),
            config=ModelConfig(
                model_id=self.model,
                provider="openai",
                provider_kwargs={
                    "api_key": self.api_key,
                    "base_url": self.base_url,
                },
            ),
        )
        return [item for item in result.extractions if getattr(item, "char_interval", None)]


def parsed_log_from_langextract(extractions: list[Any], entry_date: date) -> ParsedDailyLog:
    wellbeing = _wellbeing_from_extractions(extractions)
    nutrition = _nutrition_from_extractions(extractions)
    workout = _workout_from_extractions(extractions)
    career = _career_from_extractions(extractions)
    journal = _journal_from_extractions(extractions)

    parsed = ParsedDailyLog(
        date=entry_date,
        wellbeing=wellbeing,
        nutrition=nutrition,
        workout=workout,
        career=career,
        journal=journal,
        clarification_questions=[],
    )
    parsed.clarification_questions = build_followup_questions(parsed)
    return parsed


def _wellbeing_from_extractions(extractions: list[Any]) -> WellbeingEntry | None:
    values: dict[str, Any] = {"confidence": 0.78}
    notes: list[str] = []
    for item in _of_class(extractions, "wellbeing_metric"):
        attrs = _attrs(item)
        metric = str(attrs.get("metric") or "").lower()
        value = _number(attrs.get("value"))
        if metric in {"sleep", "sleep_hours"} and value is not None:
            values["sleep_hours"] = value
        elif metric == "sleep_quality" and value is not None:
            values["sleep_quality"] = int(value)
        elif metric == "energy" and value is not None:
            values["energy"] = int(value)
        elif metric == "stress" and value is not None:
            values["stress"] = int(value)
        elif metric == "mood" and value is not None:
            values["mood"] = int(value)
        elif metric in {"fatigue", "recovery", "note"}:
            notes.append(_text(item))
        values["confidence"] = max(values["confidence"], float(attrs.get("confidence") or 0.78))

    if notes:
        values["notes"] = " ".join(_capitalize(note) for note in notes)
    if len(values) == 1:
        return None
    return WellbeingEntry(**values)


def _nutrition_from_extractions(extractions: list[Any]) -> list[NutritionEntry]:
    entries: list[NutritionEntry] = []
    for item in _of_class(extractions, "meal"):
        attrs = _attrs(item)
        description = str(attrs.get("description") or _text(item)).strip()
        if not description:
            continue
        entries.append(
            NutritionEntry(
                meal_type=_optional_str(attrs.get("meal_type")),
                description=description,
                calories=_number(attrs.get("calories")),
                protein_g=_number(attrs.get("protein_g")),
                carbs_g=_number(attrs.get("carbs_g")),
                fat_g=_number(attrs.get("fat_g")),
                estimated=_bool(attrs.get("estimated")),
                confidence=float(attrs.get("confidence") or 0.72),
            )
        )
    return entries


def _workout_from_extractions(extractions: list[Any]) -> WorkoutEntry | None:
    workout_type = None
    duration_min = None
    distance_km = None
    pace = None
    intensity = None
    notes = None
    confidence = 0.72
    workouts = _of_class(extractions, "workout")
    if workouts:
        attrs = _attrs(workouts[0])
        workout_type = _optional_str(attrs.get("workout_type")) or _text(workouts[0])
        duration_min = _number(attrs.get("duration_min"))
        distance_km = _number(attrs.get("distance_km"))
        pace = _number(attrs.get("pace"))
        intensity_number = _number(attrs.get("intensity"))
        intensity = int(intensity_number) if intensity_number is not None else None
        notes = _optional_str(attrs.get("notes"))
        confidence = float(attrs.get("confidence") or confidence)

    exercises = []
    for item in _of_class(extractions, "exercise"):
        attrs = _attrs(item)
        name = _optional_str(attrs.get("name")) or _text(item)
        exercises.append(
            ExerciseEntry(
                name=name,
                sets=_int(attrs.get("sets")),
                reps=_int(attrs.get("reps")),
                load=_optional_str(attrs.get("load")),
                duration_min=_number(attrs.get("duration_min")),
                notes=_optional_str(attrs.get("notes")),
            )
        )

    if not workouts and not exercises:
        return None
    if workout_type is None and exercises:
        workout_type = "strength"
    return WorkoutEntry(
        workout_type=workout_type,
        duration_min=duration_min if not exercises else None,
        distance_km=distance_km,
        pace=pace,
        intensity=intensity,
        notes=notes,
        exercises=exercises,
        confidence=confidence,
    )


def _career_from_extractions(extractions: list[Any]) -> list[CareerEntry]:
    entries: list[CareerEntry] = []
    for item in _of_class(extractions, "career"):
        attrs = _attrs(item)
        entry = CareerEntry(
            project=_optional_str(attrs.get("project")),
            activity=_optional_str(attrs.get("activity")),
            duration_hours=_number(attrs.get("duration_hours")),
            progress_note=_optional_str(attrs.get("progress_note")),
            blockers=_optional_str(attrs.get("blockers")),
            confidence=float(attrs.get("confidence") or 0.72),
        )
        if entries and not entry.project and not entry.duration_hours:
            previous = entries[-1]
            previous.progress_note = previous.progress_note or entry.progress_note
            previous.blockers = previous.blockers or entry.blockers
            previous.activity = previous.activity or entry.activity
            previous.confidence = max(previous.confidence, entry.confidence)
            continue
        entries.append(entry)
    return entries


def _journal_from_extractions(extractions: list[Any]) -> JournalEntry | None:
    journals = _of_class(extractions, "journal")
    if not journals:
        return None
    item = journals[0]
    attrs = _attrs(item)
    tags = attrs.get("tags") or []
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    return JournalEntry(
        text=_optional_str(attrs.get("text")) or _text(item),
        tags=tags,
        sentiment=_number(attrs.get("sentiment")),
    )


def _examples(lx: Any) -> list[Any]:
    return [
        lx.data.ExampleData(
            text=(
                "Today I slept 6h, energy 5/10 and stress 7/10. "
                "Ate oatmeal with dates in the morning. "
                "Did lower body: squats 4x5 at 80%, RDL 3x8, and 12 min metcon. "
                "Worked 3 hours on the global TAGI-LSTM paper and fixed the SKF motivation section. "
                "Mood was okay but I felt mentally drained."
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="wellbeing_metric",
                    extraction_text="slept 6h",
                    attributes={"metric": "sleep_hours", "value": 6, "unit": "h"},
                ),
                lx.data.Extraction(
                    extraction_class="wellbeing_metric",
                    extraction_text="energy 5/10",
                    attributes={"metric": "energy", "value": 5},
                ),
                lx.data.Extraction(
                    extraction_class="wellbeing_metric",
                    extraction_text="stress 7/10",
                    attributes={"metric": "stress", "value": 7},
                ),
                lx.data.Extraction(
                    extraction_class="meal",
                    extraction_text="oatmeal with dates",
                    attributes={"meal_type": "breakfast", "description": "oatmeal with dates"},
                ),
                lx.data.Extraction(
                    extraction_class="workout",
                    extraction_text="lower body",
                    attributes={"workout_type": "lower body"},
                ),
                lx.data.Extraction(
                    extraction_class="exercise",
                    extraction_text="squats 4x5 at 80%",
                    attributes={"name": "squat", "sets": 4, "reps": 5, "load": "80% 1RM"},
                ),
                lx.data.Extraction(
                    extraction_class="exercise",
                    extraction_text="RDL 3x8",
                    attributes={"name": "Romanian deadlift", "sets": 3, "reps": 8},
                ),
                lx.data.Extraction(
                    extraction_class="exercise",
                    extraction_text="12 min metcon",
                    attributes={"name": "metcon", "duration_min": 12},
                ),
                lx.data.Extraction(
                    extraction_class="career",
                    extraction_text="Worked 3 hours on the global TAGI-LSTM paper",
                    attributes={
                        "project": "global TAGI-LSTM paper",
                        "activity": "writing/revision",
                        "duration_hours": 3,
                    },
                ),
                lx.data.Extraction(
                    extraction_class="career",
                    extraction_text="fixed the SKF motivation section",
                    attributes={"progress_note": "Fixed the SKF motivation section."},
                ),
                lx.data.Extraction(
                    extraction_class="journal",
                    extraction_text="Mood was okay but I felt mentally drained",
                    attributes={
                        "text": "Mood was okay but I felt mentally drained.",
                        "tags": ["fatigue", "research"],
                    },
                ),
            ],
        )
    ]


def _of_class(extractions: list[Any], name: str) -> list[Any]:
    return [item for item in extractions if getattr(item, "extraction_class", None) == name]


def _attrs(item: Any) -> dict[str, Any]:
    attrs = getattr(item, "attributes", None)
    return attrs if isinstance(attrs, dict) else {}


def _text(item: Any) -> str:
    return str(getattr(item, "extraction_text", "") or "").strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "estimated"}


def _capitalize(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value
