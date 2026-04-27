from __future__ import annotations

from datetime import date

from backend.app.followup import build_followup_questions
from backend.app.schemas import NutritionEntry, ParsedDailyLog, WorkoutEntry


_META_NUTRITION_MARKERS = (
    "already provided my meals",
    "already provide my meals",
    "already provided meals",
    "already provide meals",
    "already gave my meals",
    "already gave you my meals",
    "already told you my meals",
    "already logged my meals",
    "i gave you my meals",
    "i told you my meals",
    "i provided my meals",
    "i provide my meals",
)

_WORKOUT_TEXT_MARKERS = (
    "workout",
    "trained",
    "training",
    "gym",
    "lifted",
    "ran",
    "run",
    "running",
    "cardio",
    "bike",
    "cycling",
    "swim",
    "lower body",
    "upper body",
    "legs",
    "push",
    "pull",
    "shoulders",
    "chest",
    "back",
    "metcon",
    "squat",
    "deadlift",
    "rdl",
    "lunge",
    "chin up",
    "chin-up",
    "press",
)


def sanitize_parsed_log(parsed: ParsedDailyLog, source_text: str) -> ParsedDailyLog:
    """Remove obvious artifacts produced while answering bot follow-ups.

    This keeps the extractor from turning meta replies such as
    "I already provided my meals" into fake nutrition rows, or from saving a
    placeholder workout when the user's message contains no workout signal.
    """

    parsed.nutrition = _sanitize_nutrition(parsed.nutrition)
    if parsed.workout and _is_unsupported_placeholder_workout(parsed.workout, source_text):
        parsed.workout = None

    parsed.clarification_questions = []
    parsed.clarification_questions = build_followup_questions(parsed)
    return parsed


def suppress_redundant_followups(
    parsed: ParsedDailyLog,
    existing_logs: dict[str, list[dict]],
    entry_date: date | None = None,
) -> None:
    """Drop questions that are already answered elsewhere on the same day."""

    log_date = (entry_date or parsed.date).isoformat()
    has_nutrition = _has_rows_for_date(existing_logs.get("nutrition", []), log_date)
    has_workout_exercises = _has_rows_for_date(existing_logs.get("workout_exercises", []), log_date)

    has_energy = parsed.wellbeing is not None and parsed.wellbeing.energy is not None
    has_stress = parsed.wellbeing is not None and parsed.wellbeing.stress is not None
    has_mood = parsed.wellbeing is not None and parsed.wellbeing.mood is not None
    for row in existing_logs.get("daily_checkins", []):
        if not _row_matches_date(row, log_date):
            continue
        has_energy = has_energy or row.get("energy") is not None
        has_stress = has_stress or row.get("stress") is not None
        has_mood = has_mood or row.get("mood") is not None

    filtered: list[str] = []
    for question in parsed.clarification_questions:
        lower = question.lower()
        if has_nutrition and any(marker in lower for marker in ("meal", "nutrition", "calorie", "macro")):
            continue
        if has_workout_exercises and any(marker in lower for marker in ("exercise", "sets")):
            continue
        if has_energy and has_stress and any(marker in lower for marker in ("energy", "stress")):
            continue
        if has_mood and "mood" in lower:
            continue
        filtered.append(question)

    parsed.clarification_questions = filtered[:2]


def _sanitize_nutrition(entries: list[NutritionEntry]) -> list[NutritionEntry]:
    return [entry for entry in entries if not _is_meta_nutrition_text(entry.description)]


def _is_meta_nutrition_text(text: str) -> bool:
    lower = " ".join(text.lower().strip().split())
    if any(marker in lower for marker in _META_NUTRITION_MARKERS):
        return True
    return (
        "already" in lower
        and any(marker in lower for marker in ("meal", "meals", "food", "nutrition"))
        and any(marker in lower for marker in ("provided", "provide", "gave", "told", "logged"))
    )


def _is_unsupported_placeholder_workout(workout: WorkoutEntry, source_text: str) -> bool:
    lower = source_text.lower()
    has_text_signal = any(marker in lower for marker in _WORKOUT_TEXT_MARKERS)
    has_structured_signal = bool(
        workout.exercises
        or workout.duration_min is not None
        or workout.distance_km is not None
        or workout.pace is not None
        or workout.intensity is not None
    )
    return not has_text_signal and not has_structured_signal


def _has_rows_for_date(rows: list[dict], log_date: str) -> bool:
    return any(_row_matches_date(row, log_date) for row in rows)


def _row_matches_date(row: dict, log_date: str) -> bool:
    return row.get("date") == log_date or row.get("entry_date") == log_date
