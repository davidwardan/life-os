from datetime import date
from dataclasses import dataclass
from unittest import IsolatedAsyncioTestCase

from backend.app.llm_extraction import ExtractionService
from backend.app.llm_extraction import OpenRouterClient


@dataclass
class FakeLangExtraction:
    extraction_class: str
    extraction_text: str
    attributes: dict[str, object]
    char_interval: tuple[int, int] = (0, 1)


class FakeLLMClient:
    async def extract(self, text: str, entry_date: date) -> dict[str, object]:
        return {
            "date": entry_date.isoformat(),
            "wellbeing": {
                "mood": None,
                "energy": 6,
                "stress": 5,
                "sleep_hours": None,
                "sleep_quality": None,
                "notes": None,
                "confidence": 0.88,
            },
            "nutrition": [
                {
                    "meal_type": "breakfast",
                    "description": "oatmeal with dates",
                    "calories": None,
                    "protein_g": None,
                    "carbs_g": None,
                    "fat_g": None,
                    "confidence": 0.82,
                    "estimated": True,
                }
            ],
            "workout": {
                "workout_type": "legs",
                "duration_min": 60,
                "intensity": 8,
                "notes": "heavy leg day",
                "exercises": [{"name": "squat", "sets": 4, "reps": 5, "load": None}],
                "confidence": 0.9,
            },
            "career": [
                {
                    "project": "thesis",
                    "activity": "writing",
                    "duration_hours": 2,
                    "progress_note": "drafted introduction",
                    "blockers": None,
                    "confidence": 0.86,
                }
            ],
            "journal": None,
            "clarification_questions": [],
        }


class ContextAwareLLMClient(FakeLLMClient):
    def __init__(self) -> None:
        self.contexts: list[dict[str, object] | None] = []

    async def extract(
        self,
        text: str,
        entry_date: date,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.contexts.append(context)
        return await super().extract(text, entry_date)


class BrokenLLMClient:
    async def extract(self, text: str, entry_date: date) -> dict[str, object]:
        return {"not": "valid"}


class IncompleteRunningLLMClient:
    async def extract(self, text: str, entry_date: date) -> dict[str, object]:
        return {
            "date": entry_date.isoformat(),
            "nutrition": [],
            "workout": {
                "workout_type": "running",
                "duration_min": None,
                "intensity": None,
                "notes": None,
                "exercises": [],
                "confidence": 0.8,
            },
            "wellbeing": None,
            "career": [],
            "journal": {"text": text, "tags": [], "sentiment": None},
            "clarification_questions": [],
        }


class FakeLangExtractClient:
    async def extract(self, text: str, entry_date: date) -> list[FakeLangExtraction]:
        return [
            FakeLangExtraction(
                extraction_class="wellbeing_metric",
                extraction_text="energy 8/10",
                attributes={"metric": "energy", "value": 8, "confidence": 0.9},
            ),
            FakeLangExtraction(
                extraction_class="meal",
                extraction_text="chicken rice bowl",
                attributes={
                    "meal_type": "lunch",
                    "description": "chicken rice bowl",
                    "calories": 650,
                    "estimated": True,
                    "confidence": 0.7,
                },
            ),
            FakeLangExtraction(
                extraction_class="workout",
                extraction_text="lower body",
                attributes={"workout_type": "lower body"},
            ),
            FakeLangExtraction(
                extraction_class="exercise",
                extraction_text="squats 3x10 at 100 kg",
                attributes={"name": "squat", "sets": 3, "reps": 10, "load": "100 kg"},
            ),
            FakeLangExtraction(
                extraction_class="career",
                extraction_text="Worked 2 hours on Life OS",
                attributes={
                    "project": "Life OS",
                    "activity": "development",
                    "duration_hours": 2,
                },
            ),
            FakeLangExtraction(
                extraction_class="journal",
                extraction_text="felt focused",
                attributes={"text": "felt focused", "tags": ["focus"]},
            ),
        ]


class BrokenLangExtractClient:
    async def extract(self, text: str, entry_date: date) -> list[FakeLangExtraction]:
        raise RuntimeError("langextract unavailable")


class EmptyLangExtractClient:
    async def extract(self, text: str, entry_date: date) -> list[FakeLangExtraction]:
        return []


class FallbackOpenRouterClient(OpenRouterClient):
    def __init__(self) -> None:
        super().__init__(
            api_key="test",
            model="primary-model",
            fallback_models=("fallback-model",),
        )
        self.models: list[str] = []

    async def _extract_with_model(
        self,
        model: str,
        text: str,
        entry_date: date,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.models.append(model)
        if model == "primary-model":
            raise TimeoutError("primary timed out")
        return {
            "date": entry_date.isoformat(),
            "nutrition": [],
            "workout": None,
            "wellbeing": {
                "mood": None,
                "energy": 7,
                "stress": None,
                "sleep_hours": None,
                "sleep_quality": None,
                "notes": None,
                "confidence": 0.8,
            },
            "career": [],
            "journal": None,
            "clarification_questions": [],
        }


class LLMExtractionTests(IsolatedAsyncioTestCase):
    async def test_langextract_mode_maps_grounded_extractions(self) -> None:
        service = ExtractionService(
            mode="langextract",
            langextract_client=FakeLangExtractClient(),
        )

        parsed, method, error = await service.extract(
            "energy 8/10. chicken rice bowl. lower body squats 3x10 at 100 kg. "
            "Worked 2 hours on Life OS. felt focused",
            date(2026, 4, 25),
        )

        self.assertEqual(method, "langextract")
        self.assertIsNone(error)
        self.assertEqual(parsed.wellbeing.energy, 8)
        self.assertEqual(parsed.nutrition[0].description, "chicken rice bowl")
        self.assertTrue(parsed.nutrition[0].estimated)
        self.assertEqual(parsed.workout.workout_type, "lower body")
        self.assertEqual(parsed.workout.exercises[0].sets, 3)
        self.assertEqual(parsed.workout.exercises[0].load, "100 kg")
        self.assertEqual(parsed.career[0].project, "Life OS")
        self.assertEqual(parsed.journal.tags, ["focus"])

    async def test_langextract_mode_falls_back_when_extractor_fails(self) -> None:
        service = ExtractionService(
            mode="langextract",
            langextract_client=BrokenLangExtractClient(),
        )

        parsed, method, error = await service.extract(
            "Ate eggs. Energy 7.",
            date(2026, 4, 25),
        )

        self.assertEqual(method, "deterministic")
        self.assertIn("LangExtract failed", error)
        self.assertEqual(parsed.wellbeing.energy, 7)

    async def test_langextract_mode_falls_back_on_empty_extractions(self) -> None:
        service = ExtractionService(
            mode="langextract",
            langextract_client=EmptyLangExtractClient(),
        )

        parsed, method, error = await service.extract(
            "Ate eggs. Energy 7.",
            date(2026, 4, 25),
        )

        self.assertEqual(method, "deterministic")
        self.assertIn("no grounded extractions", error)
        self.assertEqual(parsed.nutrition[0].description, "eggs")

    async def test_validates_fake_llm_output(self) -> None:
        service = ExtractionService(mode="llm", llm_client=FakeLLMClient())

        parsed, method, error = await service.extract(
            "messy daily text",
            date(2026, 4, 25),
        )

        self.assertEqual(method, "llm")
        self.assertIsNone(error)
        self.assertEqual(parsed.entry_date.isoformat(), "2026-04-25")
        self.assertEqual(parsed.nutrition[0].description, "oatmeal with dates")
        self.assertEqual(parsed.workout.workout_type, "legs")
        self.assertEqual(parsed.workout.exercises[0].name, "squat")
        self.assertEqual(parsed.career[0].project, "thesis")

    async def test_passes_existing_log_context_to_context_aware_llm_client(self) -> None:
        client = ContextAwareLLMClient()
        service = ExtractionService(mode="llm", llm_client=client)
        context = {"same_day_logs": {"nutrition": [{"description": "chicken and fries"}]}}

        parsed, method, error = await service.extract(
            "Dinner was chicken and fries.",
            date(2026, 4, 25),
            context=context,
        )

        self.assertEqual(method, "llm")
        self.assertIsNone(error)
        self.assertEqual(client.contexts, [context])
        self.assertEqual(parsed.nutrition[0].description, "oatmeal with dates")

    async def test_falls_back_when_llm_output_is_invalid(self) -> None:
        service = ExtractionService(mode="llm", llm_client=BrokenLLMClient())

        parsed, method, error = await service.extract(
            "Ate eggs. Trained legs for 30 min. Energy 7.",
            date(2026, 4, 25),
        )

        self.assertEqual(method, "deterministic")
        self.assertIn("LLM extraction failed", error)
        self.assertEqual(parsed.workout.workout_type, "legs")

    async def test_llm_output_is_reconciled_with_obvious_deterministic_signals(self) -> None:
        service = ExtractionService(mode="llm", llm_client=IncompleteRunningLLMClient())

        parsed, method, error = await service.extract(
            "i ran for 5km with a pace of 5.5 yet i am destroyed "
            "stress level low but energy level also low",
            date(2026, 4, 27),
        )

        self.assertEqual(method, "llm")
        self.assertIsNone(error)
        self.assertEqual(parsed.workout.distance_km, 5)
        self.assertEqual(parsed.workout.pace, 5.5)
        self.assertEqual(parsed.wellbeing.energy, 3)
        self.assertEqual(parsed.wellbeing.stress, 3)
        self.assertEqual(parsed.clarification_questions, [])

    async def test_openrouter_client_tries_fallback_models(self) -> None:
        client = FallbackOpenRouterClient()
        service = ExtractionService(mode="llm", llm_client=client)

        parsed, method, error = await service.extract("Energy 7.", date(2026, 4, 25))

        self.assertEqual(method, "llm")
        self.assertIsNone(error)
        self.assertEqual(client.models, ["primary-model", "fallback-model"])
        self.assertEqual(parsed.wellbeing.energy, 7)

    async def test_llm_result_gets_followup_policy(self) -> None:
        class VagueLLMClient:
            async def extract(self, text: str, entry_date: date) -> dict[str, object]:
                return {
                    "date": entry_date.isoformat(),
                    "nutrition": [
                        {
                            "meal_type": "dinner",
                            "description": "chicken and fries",
                            "calories": None,
                            "protein_g": None,
                            "carbs_g": None,
                            "fat_g": None,
                            "estimated": False,
                            "confidence": 0.5,
                        }
                    ],
                    "workout": {
                        "workout_type": "strength",
                        "duration_min": 90,
                        "intensity": None,
                        "notes": None,
                        "exercises": [],
                        "confidence": 0.8,
                    },
                    "wellbeing": None,
                    "career": [],
                    "journal": None,
                    "clarification_questions": [],
                }

        service = ExtractionService(mode="llm", llm_client=VagueLLMClient())
        parsed, method, error = await service.extract("vague", date(2026, 4, 25))

        self.assertEqual(method, "llm")
        self.assertIsNone(error)
        self.assertLessEqual(len(parsed.clarification_questions), 2)
        self.assertTrue(any("exercises" in q.lower() for q in parsed.clarification_questions))
