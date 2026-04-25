from __future__ import annotations

import re
from datetime import date

from backend.app.schemas import (
    CareerEntry,
    NutritionEntry,
    ParsedDailyLog,
    WellbeingEntry,
    WorkoutEntry,
)


_NUMBER = r"(\d+(?:\.\d+)?)"


def extract_daily_log(text: str, entry_date: date | None = None) -> ParsedDailyLog:
    normalized = " ".join(text.strip().split())
    log_date = entry_date or date.today()

    nutrition = _extract_nutrition(normalized)
    workout = _extract_workout(normalized)
    wellbeing = _extract_wellbeing(normalized)
    career = _extract_career(normalized)
    journal_text = _extract_journal(normalized, nutrition, workout, wellbeing, career)

    questions: list[str] = []
    if nutrition and all(item.calories is None for item in nutrition):
        questions.append("Do you want calorie and macro estimates for these meals?")
    if workout and workout.duration_min is None:
        questions.append("How long was the workout?")

    return ParsedDailyLog(
        entry_date=log_date,
        nutrition=nutrition,
        workout=workout,
        wellbeing=wellbeing,
        career=career,
        journal_text=journal_text,
        missing_info_questions=questions,
    )


def _extract_nutrition(text: str) -> list[NutritionEntry]:
    lower = text.lower()
    if not any(marker in lower for marker in ("ate ", "had ", "meal", "breakfast", "lunch", "dinner")):
        return []

    calorie_match = re.search(rf"{_NUMBER}\s*(?:cal|cals|calories|kcal)\b", lower)
    protein_match = re.search(rf"{_NUMBER}\s*g?\s*protein\b", lower)

    meal_segment = re.split(
        r"\b(?:trained|workout|lifted|ran|energy|mood|stress|slept|sleep|worked|deep work)\b",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]

    meal_text = re.sub(rf"\b{_NUMBER}\s*(?:cal|cals|calories|kcal)\b", "", meal_segment, flags=re.I)
    meal_text = re.sub(rf"\b{_NUMBER}\s*g?\s*protein\b", "", meal_text, flags=re.I)
    meal_text = re.sub(r"\b(?:i\s+)?(?:ate|had)\b", "", meal_text, flags=re.I).strip(" .")

    parts = [
        part.strip(" .,")
        for part in re.split(r"\b(?:then|and then|plus|,)\b", meal_text, flags=re.I)
        if part.strip(" .")
    ]
    if not parts:
        parts = [meal_text or text]

    entries: list[NutritionEntry] = []
    for index, part in enumerate(parts):
        entries.append(
            NutritionEntry(
                meal_name=part,
                calories=float(calorie_match.group(1)) if calorie_match and index == 0 else None,
                protein_g=float(protein_match.group(1)) if protein_match and index == 0 else None,
                confidence=0.74 if calorie_match or protein_match else 0.58,
                estimated=calorie_match is None and protein_match is None,
            )
        )
    return entries


def _extract_workout(text: str) -> WorkoutEntry | None:
    lower = text.lower()
    workout_markers = ("trained", "workout", "lifted", "ran", "did legs", "did upper", "metcon")
    if not any(marker in lower for marker in workout_markers):
        return None

    duration_match = re.search(rf"{_NUMBER}\s*(?:min|mins|minutes)\b", lower)
    intensity_match = re.search(rf"(?:intensity|rpe)\s*{_NUMBER}", lower)

    workout_type = None
    for candidate in (
        "upper body",
        "lower body",
        "legs",
        "push",
        "pull",
        "shoulders",
        "chest",
        "back",
        "run",
        "metcon",
    ):
        if candidate in lower:
            workout_type = candidate
            break

    if workout_type is None and "trained" in lower:
        after_trained = re.search(r"trained\s+([^.;,]+)", text, flags=re.I)
        if after_trained:
            workout_type = after_trained.group(1).strip()

    return WorkoutEntry(
        workout_type=workout_type,
        duration_min=float(duration_match.group(1)) if duration_match else None,
        intensity=int(float(intensity_match.group(1))) if intensity_match else None,
        notes=text,
        confidence=0.7 if workout_type else 0.52,
    )


def _extract_wellbeing(text: str) -> WellbeingEntry | None:
    lower = text.lower()

    mood = _rating(lower, "mood")
    energy = _rating(lower, "energy")
    stress = _rating(lower, "stress")
    sleep_quality = _rating(lower, "sleep quality")

    sleep_match = re.search(rf"(?:slept|sleep)\s*{_NUMBER}\s*(?:h|hr|hrs|hours)?\b", lower)
    if sleep_match is None:
        sleep_match = re.search(rf"{_NUMBER}\s*(?:h|hr|hrs|hours)\s*(?:of\s*)?sleep\b", lower)

    if all(value is None for value in (mood, energy, stress, sleep_quality)) and sleep_match is None:
        return None

    return WellbeingEntry(
        mood=mood,
        energy=energy,
        stress=stress,
        sleep_hours=float(sleep_match.group(1)) if sleep_match else None,
        sleep_quality=sleep_quality,
        confidence=0.78,
    )


def _extract_career(text: str) -> list[CareerEntry]:
    lower = text.lower()
    if not any(marker in lower for marker in ("worked", "deep work", "paper", "career", "project", "research")):
        return []

    duration_match = re.search(rf"{_NUMBER}\s*(?:h|hr|hrs|hours)\b", lower)
    project = None

    project_match = re.search(
        rf"(?:worked|deep work)\s*(?:for\s*)?{_NUMBER}?\s*(?:h|hr|hrs|hours)?\s*(?:on|for)\s+([^.;]+)",
        text,
        flags=re.I,
    )
    if project_match is None:
        project_match = re.search(r"(?:paper|project|research)\s+(?:on|for)\s+([^.;]+)", text, flags=re.I)
    if project_match:
        project = project_match.group(2 if project_match.lastindex and project_match.lastindex > 1 else 1).strip()
        project = re.split(
            r"\s+and\s+(?:fixed|finished|drafted|wrote|advanced|completed)\b",
            project,
            maxsplit=1,
            flags=re.I,
        )[0].strip()

    progress_note = None
    progress_match = re.search(r"(?:fixed|finished|drafted|wrote|advanced|completed)\s+([^.;]+)", text, flags=re.I)
    if progress_match:
        progress_note = progress_match.group(0).strip()

    return [
        CareerEntry(
            project=project,
            activity="deep work" if "deep work" in lower else "work",
            duration_hours=float(duration_match.group(1)) if duration_match else None,
            progress_note=progress_note,
            confidence=0.68 if duration_match else 0.55,
        )
    ]


def _extract_journal(
    text: str,
    nutrition: list[NutritionEntry],
    workout: WorkoutEntry | None,
    wellbeing: WellbeingEntry | None,
    career: list[CareerEntry],
) -> str | None:
    lower = text.lower()
    if lower.startswith("journal:") or any(marker in lower for marker in ("felt ", "thinking about", "grateful")):
        return text.removeprefix("journal:").strip()
    if not any((nutrition, workout, wellbeing, career)):
        return text
    return None


def _rating(text: str, label: str) -> int | None:
    escaped = re.escape(label)
    match = re.search(rf"\b{escaped}\s*(?:is|was|:)?\s*([1-9]|10)(?:/10)?\b", text)
    if match:
        return int(match.group(1))
    return None
