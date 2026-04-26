from datetime import date
from unittest import IsolatedAsyncioTestCase

from backend.app.llm_extraction import ExtractionService
from backend.app.llm_extraction import OpenRouterClient


class FakeLLMClient:
    async def extract(self, text: str, entry_date: date) -> dict[str, object]:
        return {
            "entry_date": entry_date.isoformat(),
            "nutrition": [
                {
                    "meal_name": "oatmeal with dates",
                    "calories": None,
                    "protein_g": None,
                    "confidence": 0.82,
                    "estimated": True,
                }
            ],
            "workout": {
                "workout_type": "legs",
                "duration_min": 60,
                "intensity": 8,
                "notes": "heavy leg day",
                "confidence": 0.9,
            },
            "wellbeing": {
                "mood": None,
                "energy": 6,
                "stress": 5,
                "sleep_hours": None,
                "sleep_quality": None,
                "confidence": 0.88,
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
            "journal_text": None,
            "missing_info_questions": [],
        }


class BrokenLLMClient:
    async def extract(self, text: str, entry_date: date) -> dict[str, object]:
        return {"not": "valid"}


class FallbackOpenRouterClient(OpenRouterClient):
    def __init__(self) -> None:
        super().__init__(
            api_key="test",
            model="primary-model",
            fallback_models=("fallback-model",),
        )
        self.models: list[str] = []

    async def _extract_with_model(self, model: str, text: str, entry_date: date) -> dict[str, object]:
        self.models.append(model)
        if model == "primary-model":
            raise TimeoutError("primary timed out")
        return {
            "entry_date": entry_date.isoformat(),
            "nutrition": [],
            "workout": None,
            "wellbeing": {
                "mood": None,
                "energy": 7,
                "stress": None,
                "sleep_hours": None,
                "sleep_quality": None,
                "confidence": 0.8,
            },
            "career": [],
            "journal_text": None,
            "missing_info_questions": [],
        }


class LLMExtractionTests(IsolatedAsyncioTestCase):
    async def test_validates_fake_llm_output(self) -> None:
        service = ExtractionService(mode="llm", llm_client=FakeLLMClient())

        parsed, method, error = await service.extract(
            "messy daily text",
            date(2026, 4, 25),
        )

        self.assertEqual(method, "llm")
        self.assertIsNone(error)
        self.assertEqual(parsed.entry_date.isoformat(), "2026-04-25")
        self.assertEqual(parsed.nutrition[0].meal_name, "oatmeal with dates")
        self.assertEqual(parsed.workout.workout_type, "legs")
        self.assertEqual(parsed.career[0].project, "thesis")

    async def test_falls_back_when_llm_output_is_invalid(self) -> None:
        service = ExtractionService(mode="llm", llm_client=BrokenLLMClient())

        parsed, method, error = await service.extract(
            "Ate eggs. Trained legs for 30 min. Energy 7.",
            date(2026, 4, 25),
        )

        self.assertEqual(method, "deterministic")
        self.assertIn("LLM extraction failed", error)
        self.assertEqual(parsed.workout.workout_type, "legs")

    async def test_openrouter_client_tries_fallback_models(self) -> None:
        client = FallbackOpenRouterClient()
        service = ExtractionService(mode="llm", llm_client=client)

        parsed, method, error = await service.extract("Energy 7.", date(2026, 4, 25))

        self.assertEqual(method, "llm")
        self.assertIsNone(error)
        self.assertEqual(client.models, ["primary-model", "fallback-model"])
        self.assertEqual(parsed.wellbeing.energy, 7)
