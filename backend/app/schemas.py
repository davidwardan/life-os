from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Source = Literal["web", "telegram", "whatsapp", "openclaw", "api"]


class MessageIn(BaseModel):
    text: str = Field(min_length=1)
    entry_date: date | None = None
    source: Source = "web"


class WellbeingEntry(BaseModel):
    sleep_hours: float | None = Field(default=None, ge=0, le=16)
    sleep_quality: int | None = Field(default=None, ge=1, le=10)
    energy: int | None = Field(default=None, ge=1, le=10)
    stress: int | None = Field(default=None, ge=1, le=10)
    mood: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    confidence: float = Field(default=0.7, ge=0, le=1)


class NutritionEntry(BaseModel):
    meal_type: str | None = None
    description: str
    calories: float | None = Field(default=None, ge=0)
    protein_g: float | None = Field(default=None, ge=0)
    carbs_g: float | None = Field(default=None, ge=0)
    fat_g: float | None = Field(default=None, ge=0)
    estimated: bool = False
    confidence: float = Field(ge=0, le=1)


class ExerciseEntry(BaseModel):
    name: str
    sets: int | None = Field(default=None, ge=1)
    reps: int | None = Field(default=None, ge=1)
    load: str | None = None
    duration_min: float | None = Field(default=None, ge=0)
    notes: str | None = None


class WorkoutEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workout_type: str | None = Field(default=None, alias="type")
    duration_min: float | None = Field(default=None, ge=0)
    distance_km: float | None = Field(default=None, ge=0)
    pace: float | None = Field(default=None, ge=0)
    intensity: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    exercises: list[ExerciseEntry] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0, le=1)


class CareerEntry(BaseModel):
    project: str | None = None
    duration_hours: float | None = Field(default=None, ge=0)
    activity: str | None = None
    progress_note: str | None = None
    blockers: str | None = None
    confidence: float = Field(default=0.7, ge=0, le=1)


class JournalEntry(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)
    sentiment: float | None = Field(default=None, ge=-1, le=1)


class ParsedDailyLog(BaseModel):
    date: date
    wellbeing: WellbeingEntry | None = None
    nutrition: list[NutritionEntry] = Field(default_factory=list)
    workout: WorkoutEntry | None = None
    career: list[CareerEntry] = Field(default_factory=list)
    journal: JournalEntry | None = None
    clarification_questions: list[str] = Field(default_factory=list)

    @property
    def entry_date(self) -> date:
        return self.date

    @entry_date.setter
    def entry_date(self, value: date) -> None:
        self.date = value

    @property
    def missing_info_questions(self) -> list[str]:
        return self.clarification_questions

    @property
    def journal_text(self) -> str | None:
        return self.journal.text if self.journal else None


class LoggedMessage(BaseModel):
    raw_message_id: int
    parsed: ParsedDailyLog
    records: dict[str, list[dict[str, Any]]]
    extraction_method: str
    extraction_error: str | None = None


class ExtractionStatus(BaseModel):
    mode: str
    configured: bool
    model: str | None = None


class TelegramStatus(BaseModel):
    configured: bool
    allowlist_enabled: bool
    confirmations_enabled: bool
    webhook_secret_enabled: bool
