from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


Source = Literal["web", "telegram", "whatsapp", "openclaw", "api"]


class MessageIn(BaseModel):
    text: str = Field(min_length=1)
    entry_date: date | None = None
    source: Source = "web"


class NutritionEntry(BaseModel):
    meal_name: str
    calories: float | None = None
    protein_g: float | None = None
    confidence: float = Field(ge=0, le=1)
    estimated: bool = True


class WorkoutEntry(BaseModel):
    workout_type: str | None = None
    duration_min: float | None = None
    intensity: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    confidence: float = Field(ge=0, le=1)


class WellbeingEntry(BaseModel):
    mood: int | None = Field(default=None, ge=1, le=10)
    energy: int | None = Field(default=None, ge=1, le=10)
    stress: int | None = Field(default=None, ge=1, le=10)
    sleep_hours: float | None = None
    sleep_quality: int | None = Field(default=None, ge=1, le=10)
    confidence: float = Field(ge=0, le=1)


class CareerEntry(BaseModel):
    project: str | None = None
    activity: str | None = None
    duration_hours: float | None = None
    progress_note: str | None = None
    blockers: str | None = None
    confidence: float = Field(ge=0, le=1)


class ParsedDailyLog(BaseModel):
    entry_date: date
    nutrition: list[NutritionEntry] = Field(default_factory=list)
    workout: WorkoutEntry | None = None
    wellbeing: WellbeingEntry | None = None
    career: list[CareerEntry] = Field(default_factory=list)
    journal_text: str | None = None
    missing_info_questions: list[str] = Field(default_factory=list)


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
