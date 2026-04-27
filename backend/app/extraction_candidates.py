from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


ExtractionClass = Literal[
    "wellbeing_metric",
    "meal",
    "workout",
    "exercise",
    "career",
    "journal",
    "followup_answer",
    "already_answered",
    "no_more_info",
    "correction",
    "query",
]


_META_MEAL_MARKERS = (
    "already provided",
    "already provide",
    "already gave",
    "already told",
    "already logged",
    "i provided",
    "i provide",
    "i gave",
    "i told",
)

_FOOD_WORDS = (
    "oatmeal",
    "dates",
    "peanut",
    "chocolate",
    "chicken",
    "rice",
    "salad",
    "eggs",
    "egg",
    "toast",
    "yogurt",
    "berries",
    "fries",
    "beef",
    "fish",
    "tuna",
    "bread",
    "pasta",
    "potato",
    "protein bar",
)

_WORKOUT_WORDS = (
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

_META_REPLY_WORDS = (
    "already",
    "provided",
    "provide",
    "gave",
    "told",
    "logged",
    "skip",
    "no thanks",
    "no more info",
)


class ExtractionCandidate(BaseModel):
    """Validated, grounded extraction emitted by LangExtract.

    LangExtract is good at identifying spans. This model is the contract that
    prevents conversation-management text from being stored as life data.
    """

    extraction_class: ExtractionClass
    extraction_text: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.7, ge=0, le=1)

    @model_validator(mode="after")
    def reject_meta_as_life_data(self) -> "ExtractionCandidate":
        lower = " ".join(self.extraction_text.lower().split())
        attrs = {str(key): value for key, value in self.attributes.items()}

        if self.extraction_class == "meal":
            description = str(attrs.get("description") or self.extraction_text).lower()
            if _is_meta_meal_reply(description):
                raise ValueError("Meta statement about meals cannot be extracted as a meal")
            if not any(word in description for word in _FOOD_WORDS) and not any(
                key in attrs for key in ("calories", "protein_g", "carbs_g", "fat_g", "meal_type")
            ):
                raise ValueError("Meal extraction must contain actual food or nutrition attributes")

        if self.extraction_class == "workout":
            workout_type = str(attrs.get("workout_type") or self.extraction_text).lower()
            has_structured_signal = any(
                key in attrs for key in ("duration_min", "distance_km", "pace", "intensity")
            )
            if not has_structured_signal and not any(word in workout_type for word in _WORKOUT_WORDS):
                raise ValueError("Workout extraction lacks workout evidence")

        if self.extraction_class == "journal":
            if _is_only_meta_reply(lower):
                raise ValueError("Meta reply cannot be extracted as journal text")

        return self


def validate_extraction_candidates(extractions: list[Any]) -> list[ExtractionCandidate]:
    candidates: list[ExtractionCandidate] = []
    for item in extractions:
        attrs = getattr(item, "attributes", None)
        if not isinstance(attrs, dict):
            attrs = {}
        try:
            candidates.append(
                ExtractionCandidate(
                    extraction_class=getattr(item, "extraction_class", ""),
                    extraction_text=str(getattr(item, "extraction_text", "") or "").strip(),
                    attributes=attrs,
                    confidence=float(attrs.get("confidence") or 0.7),
                )
            )
        except (ValidationError, ValueError, TypeError):
            continue
    return candidates


def _is_meta_meal_reply(text: str) -> bool:
    lower = " ".join(text.lower().split())
    return any(marker in lower for marker in _META_MEAL_MARKERS) and any(
        marker in lower for marker in ("meal", "meals", "food", "nutrition")
    )


def _is_only_meta_reply(text: str) -> bool:
    lower = " ".join(text.lower().split())
    return bool(lower) and any(word in lower for word in _META_REPLY_WORDS) and not any(
        word in lower for word in _FOOD_WORDS + _WORKOUT_WORDS
    )
