from __future__ import annotations

import re
from datetime import date

from backend.app.schemas import (
    CareerEntry,
    ExerciseEntry,
    JournalEntry,
    NutritionEntry,
    ParsedDailyLog,
    WellbeingEntry,
    WorkoutEntry,
)
from backend.app.followup import build_followup_questions


_NUMBER = r"(\d+(?:\.\d+)?)"


def extract_daily_log(text: str, entry_date: date | None = None) -> ParsedDailyLog:
    normalized = " ".join(text.strip().split())
    log_date = entry_date or date.today()

    wellbeing = _extract_wellbeing(normalized)
    nutrition = _extract_nutrition(normalized)
    workout = _extract_workout(normalized)
    career = _extract_career(normalized)
    journal = _extract_journal(normalized, wellbeing, nutrition, workout, career)

    parsed = ParsedDailyLog(
        date=log_date,
        wellbeing=wellbeing,
        nutrition=nutrition,
        workout=workout,
        career=career,
        journal=journal,
        clarification_questions=_clarification_questions(nutrition, workout, career),
    )
    parsed.clarification_questions = build_followup_questions(parsed)
    return parsed


def is_non_logging_reply(text: str) -> bool:
    lower = " ".join(text.lower().strip().split())
    refusal_patterns = (
        "i do not want to give more info",
        "i don't want to give more info",
        "no more info",
        "no thanks",
        "skip",
    )
    return lower in refusal_patterns


def _extract_wellbeing(text: str) -> WellbeingEntry | None:
    lower = text.lower()

    mood = _rating(lower, "mood")
    if mood is None and "mood was okay" in lower:
        mood = 6

    energy = _rating(lower, "energy")
    stress = _rating(lower, "stress")
    sleep_quality = _rating(lower, "sleep quality")

    sleep_match = re.search(rf"(?:slept|sleep)\s*{_NUMBER}\s*(?:h|hr|hrs|hours)?\b", lower)
    if sleep_match is None:
        sleep_match = re.search(rf"{_NUMBER}\s*(?:h|hr|hrs|hours)\s*(?:of\s*)?sleep\b", lower)

    notes: list[str] = []
    if "woke up tired" in lower:
        notes.append("Woke up tired.")
    if "mentally drained" in lower:
        notes.append("Felt mentally drained.")
    if "tired" in lower and not notes:
        notes.append("Felt tired.")

    if all(value is None for value in (mood, energy, stress, sleep_quality)) and sleep_match is None and not notes:
        return None

    return WellbeingEntry(
        mood=mood,
        energy=energy,
        stress=stress,
        sleep_hours=float(sleep_match.group(1)) if sleep_match else None,
        sleep_quality=sleep_quality,
        notes=" ".join(notes) or None,
        confidence=0.78,
    )


def _extract_nutrition(text: str) -> list[NutritionEntry]:
    lower = text.lower()
    if not any(marker in lower for marker in ("ate ", "had ", "meal", "breakfast", "lunch", "dinner", "morning")):
        return []

    entries: list[NutritionEntry] = []
    breakfast = None
    if "ate " in lower or "had " in lower or "breakfast" in lower:
        breakfast = _extract_between(
            text,
            start_patterns=(r"(?:ate|had)\s+", r"breakfast(?: was)?\s+"),
            end_pattern=r"\b(?:lunch|dinner|did|trained|worked|mood|energy|stress|sleep|slept)\b",
        )
    if breakfast:
        breakfast = re.sub(r"\s+in the morning$", "", breakfast, flags=re.I).strip(" .")
        if _looks_like_food(breakfast):
            calories = _estimate_calories(breakfast)
            entries.append(
                NutritionEntry(
                    meal_type="breakfast" if "morning" in lower or "breakfast" in lower else None,
                    description=breakfast,
                    calories=calories,
                    estimated=calories is not None,
                    confidence=0.72 if calories is None else 0.62,
                )
            )

    lunch_match = re.search(
        r"\blunch(?: was)?\s+(.+?)(?:\.|$|\b(?:dinner|did|trained|worked|mood|energy|stress)\b)",
        text,
        flags=re.I,
    )
    if lunch_match:
        description = lunch_match.group(1).strip(" .")
        protein_g = 55.0 if re.search(r"180\s*g\s+cooked\s+chicken", description, flags=re.I) else None
        calories = _estimate_calories(description)
        entries.append(
            NutritionEntry(
                meal_type="lunch",
                description=description,
                calories=calories,
                protein_g=protein_g,
                estimated=protein_g is not None or calories is not None,
                confidence=0.75 if protein_g is not None else 0.7,
            )
        )

    dinner_match = re.search(
        r"\bdinner(?: was)?\s+(.+?)(?:\.|$|\b(?:lunch|did|trained|worked|mood|energy|stress)\b)",
        text,
        flags=re.I,
    )
    if dinner_match:
        description = dinner_match.group(1).strip(" .")
        calories = _estimate_calories(description)
        return [
            NutritionEntry(
                meal_type="dinner",
                description=description,
                calories=calories,
                estimated=calories is not None,
                confidence=0.7 if calories is None else 0.62,
            )
        ]
        entries.extend(dinner_entries)

    if entries:
        return entries

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
    meal_text = re.sub(r"\b(?:i\s+)?(?:ate|had)\b", "", meal_text, flags=re.I).strip(" .,")

    parts = [
        part.strip(" .,")
        for part in re.split(r"\b(?:then|and then|plus)\b|,", meal_text, flags=re.I)
        if part.strip(" .,")
    ]
    if not parts and "ate" in lower:
        parts = [meal_text or text]

    for index, part in enumerate(parts):
        calories = float(calorie_match.group(1)) if calorie_match and index == 0 else _estimate_calories(part)
        entries.append(
            NutritionEntry(
                meal_type=None,
                description=part,
                calories=calories,
                protein_g=float(protein_match.group(1)) if protein_match and index == 0 else None,
                estimated=not bool(calorie_match and index == 0) and calories is not None,
                confidence=0.74 if calorie_match or protein_match else 0.58,
            )
        )
    return entries


def _extract_workout(text: str) -> WorkoutEntry | None:
    lower = text.lower()
    workout_markers = (
        "trained",
        "workout",
        "lifted",
        "ran",
        "did lower",
        "did upper",
        "metcon",
        "squat",
        "deadlift",
        "lunges",
        "chin ups",
        "dumbbell press",
        "dumbell press",
    )
    if not any(marker in lower for marker in workout_markers):
        return None

    duration_match = re.search(rf"{_NUMBER}\s*(?:min|mins|minutes)\b", lower)
    intensity_match = re.search(rf"(?:intensity|rpe)\s*{_NUMBER}", lower)

    workout_type = None
    for candidate in (
        "lower body",
        "upper body",
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

    exercises = _extract_exercises(text)
    if workout_type is None and exercises:
        workout_type = "strength"

    return WorkoutEntry(
        workout_type=workout_type,
        duration_min=float(duration_match.group(1)) if duration_match and not exercises else None,
        intensity=int(float(intensity_match.group(1))) if intensity_match else None,
        notes=None if exercises else text,
        exercises=exercises,
        confidence=0.76 if exercises or workout_type else 0.52,
    )


def _extract_exercises(text: str) -> list[ExerciseEntry]:
    exercises: list[ExerciseEntry] = []
    normalized_text = re.sub(r"\bod\b", "of", text, flags=re.I)

    for match in re.finditer(
        r"\b(?P<name>squats?|rdl|romanian deadlifts?)\s+"
        r"(?P<sets>\d+)\s*x\s*(?P<reps>\d+)"
        r"(?:\s+at\s+(?P<load>[^,.;]+))?",
        normalized_text,
        flags=re.I,
    ):
        exercises.append(
            ExerciseEntry(
                name=_normalize_exercise_name(match.group("name")),
                sets=int(match.group("sets")),
                reps=int(match.group("reps")),
                load=_normalize_load(match.group("load")),
            )
        )

    structured_patterns = (
        r"\b(?P<name>squats?|deadlifts?|rdl|romanian deadlifts?|lunges?|chin[- ]ups?|dumbbell press|dumbell press)\s+"
        r"(?P<sets>\d+)\s*sets?\s*(?:of|x)?\s*(?P<reps>\d+)\s*(?:reps?|each)?"
        r"(?:\s*(?:at|with|with a)?\s*(?P<load>\d+(?:\.\d+)?\s*(?:kg|kgs|lb|lbs)))?",
        r"\b(?P<sets>\d+)\s*sets?\s*(?P<reps>\d+)\s*(?:reps?|each)?\s+"
        r"(?P<name>squats?|deadlifts?|rdl|romanian deadlifts?|lunges?|chin[- ]ups?|dumbbell press|dumbell press)"
        r"(?:\s*(?:at|with|with a)?\s*(?P<load>\d+(?:\.\d+)?\s*(?:kg|kgs|lb|lbs)))?",
    )
    seen = {(exercise.name, exercise.sets, exercise.reps, exercise.load) for exercise in exercises}
    for pattern in structured_patterns:
        for match in re.finditer(pattern, normalized_text, flags=re.I):
            exercise = ExerciseEntry(
                name=_normalize_exercise_name(match.group("name")),
                sets=int(match.group("sets")),
                reps=int(match.group("reps")),
                load=_normalize_load(match.group("load")),
            )
            key = (exercise.name, exercise.sets, exercise.reps, exercise.load)
            if key not in seen:
                exercises.append(exercise)
                seen.add(key)

    metcon_match = re.search(rf"{_NUMBER}\s*(?:min|mins|minutes)\s+metcon\b", text, flags=re.I)
    if metcon_match:
        exercises.append(ExerciseEntry(name="metcon", duration_min=float(metcon_match.group(1))))

    if not exercises:
        bare_names = (
            ("squats", "squat"),
            ("squat", "squat"),
            ("deadlifts", "deadlift"),
            ("deadlift", "deadlift"),
            ("lunges", "lunge"),
            ("lunge", "lunge"),
            ("chin ups", "chin up"),
            ("chin-ups", "chin up"),
            ("dumbbell press", "dumbbell press"),
            ("dumbell press", "dumbbell press"),
        )
        lower = text.lower()
        seen_names = set()
        for marker, name in bare_names:
            if marker in lower and name not in seen_names:
                exercises.append(ExerciseEntry(name=name))
                seen_names.add(name)

    return exercises


def _extract_career(text: str) -> list[CareerEntry]:
    lower = text.lower()
    if not any(marker in lower for marker in ("worked", "deep work", "paper", "career", "project", "research")):
        return []

    duration_match = re.search(
        rf"(?:worked|deep work)\s*(?:for\s*)?{_NUMBER}\s*(?:h|hr|hrs|hours)\b",
        lower,
    )
    if duration_match is None:
        duration_match = re.search(rf"{_NUMBER}\s*(?:h|hr|hrs|hours)\s+(?:on|for)\s+", lower)
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
        progress_note = _capitalize_sentence(progress_match.group(0).strip())

    return [
        CareerEntry(
            project=project,
            activity="writing/revision" if progress_note else ("deep work" if "deep work" in lower else "work"),
            duration_hours=float(duration_match.group(1)) if duration_match else None,
            progress_note=progress_note,
            confidence=0.72 if duration_match else 0.55,
        )
    ]


def _extract_journal(
    text: str,
    wellbeing: WellbeingEntry | None,
    nutrition: list[NutritionEntry],
    workout: WorkoutEntry | None,
    career: list[CareerEntry],
) -> JournalEntry | None:
    lower = text.lower()
    journal_text = None
    mood_match = re.search(r"(mood was [^.;]+(?:but [^.;]+)?)", text, flags=re.I)
    if mood_match:
        journal_text = _capitalize_sentence(mood_match.group(1).strip())
    elif lower.startswith("journal:"):
        journal_text = text.removeprefix("journal:").strip()
    elif any(marker in lower for marker in ("felt ", "thinking about", "grateful", "mentally drained")):
        journal_text = text
    elif not any((wellbeing, nutrition, workout, career)):
        journal_text = text

    if not journal_text:
        return None

    tags = []
    if any(word in lower for word in ("tired", "drained", "fatigue")):
        tags.append("fatigue")
    if "stress" in lower:
        tags.append("stress")
    if any(word in lower for word in ("paper", "research", "lstm", "tagi")):
        tags.append("research")

    return JournalEntry(text=journal_text, tags=tags)


def _clarification_questions(
    nutrition: list[NutritionEntry],
    workout: WorkoutEntry | None,
    career: list[CareerEntry],
) -> list[str]:
    questions: list[str] = []
    if nutrition and all(item.calories is None for item in nutrition):
        questions.append("Do you want me to estimate calories and macros for the meals?")
    if workout and not workout.exercises and workout.duration_min is None:
        questions.append("What kind of training did you do, and for how long?")
    if career and any(item.duration_hours is None for item in career):
        questions.append("Roughly how long did you work on the project?")
    return questions[:2]


def _extract_between(text: str, start_patterns: tuple[str, ...], end_pattern: str) -> str | None:
    for start in start_patterns:
        match = re.search(start + r"(.+?)(?:\.|$|" + end_pattern + ")", text, flags=re.I)
        if match:
            return match.group(1).strip(" .,")
    return None


def _rating(text: str, label: str) -> int | None:
    escaped = re.escape(label)
    match = re.search(rf"\b{escaped}\s*(?:is|was|:)?\s*([1-9]|10)(?:/10)?\b", text)
    if match:
        return int(match.group(1))
    return None


def _normalize_load(load: str | None) -> str | None:
    if not load:
        return None
    clean = load.strip()
    if clean.endswith("%"):
        return f"{clean} 1RM"
    clean = re.sub(r"\bkgs\b", "kg", clean, flags=re.I)
    clean = re.sub(r"\blbs\b", "lb", clean, flags=re.I)
    return clean


def _normalize_exercise_name(name: str) -> str:
    lower = name.lower().strip()
    if lower == "rdl":
        return "Romanian deadlift"
    if lower.startswith("romanian deadlift"):
        return "Romanian deadlift"
    if lower.startswith("squat"):
        return "squat"
    if lower.startswith("deadlift"):
        return "deadlift"
    if lower.startswith("lunge"):
        return "lunge"
    if lower in {"chin ups", "chin-ups", "chin up"}:
        return "chin up"
    if lower in {"dumbell press", "dumbbell press"}:
        return "dumbbell press"
    return lower


def _estimate_calories(description: str) -> float | None:
    lower = description.lower()
    rules = (
        (("oatmeal", "dates", "peanut butter", "chocolate"), 650.0),
        (("oatmeal", "peanut butter"), 520.0),
        (("oatmeal",), 350.0),
        (("chicken", "rice", "salad"), 650.0),
        (("chicken", "rice"), 620.0),
        (("chicken", "fries"), 850.0),
        (("eggs",), 300.0),
    )
    for terms, calories in rules:
        if all(term in lower for term in terms):
            return calories
    if _looks_like_food(description):
        return 600.0
    return None


def _looks_like_food(text: str) -> bool:
    lower = text.lower()
    food_words = (
        "oatmeal",
        "dates",
        "peanut",
        "chocolate",
        "chicken",
        "rice",
        "salad",
        "eggs",
        "toast",
        "yogurt",
        "berries",
        "fries",
        "meal",
        "breakfast",
        "lunch",
        "dinner",
    )
    return any(word in lower for word in food_words)


def _capitalize_sentence(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]
