from __future__ import annotations

from backend.app.schemas import ParsedDailyLog


def build_followup_questions(parsed: ParsedDailyLog) -> list[str]:
    questions: list[str] = []

    if parsed.workout and not parsed.workout.exercises:
        questions.append("Want to add the main exercises or sets from that workout?")

    if parsed.wellbeing is None:
        questions.append("Want to add energy, stress, or mood for today?")
    elif parsed.wellbeing.energy is None and parsed.wellbeing.stress is None:
        questions.append("Want to add energy or stress, 1-10?")

    if parsed.workout and parsed.workout.duration_min is not None and parsed.workout.intensity is None:
        questions.append("How hard was the workout, 1-10?")

    if parsed.nutrition and any(item.confidence < 0.6 for item in parsed.nutrition):
        questions.append("Want to clarify the meal details or portions?")

    if parsed.nutrition and any(item.estimated and item.calories is not None for item in parsed.nutrition):
        questions.append("Want to replace the estimated calories with actual calories for any meal?")

    questions.extend(parsed.clarification_questions)

    return _dedupe(questions)[:2]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        output.append(value)
        seen.add(normalized)
    return output
