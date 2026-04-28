from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from backend.app.db import LifeDatabase
from backend.app.memory import MemoryService, extract_memory_candidates, is_memory_request


class MemoryExtractionTests(TestCase):
    def test_extracts_preferences_strategies_and_style(self) -> None:
        candidates = extract_memory_candidates(
            "Remember that I like Swiss minimalist design. "
            "Briefings should be direct and concise. "
            "Training early works for me. "
            "Long motivational messages don't work for me."
        )

        by_category = {candidate.category: candidate for candidate in candidates}
        self.assertEqual(by_category["preference"].value, "swiss minimalist design")
        self.assertEqual(by_category["briefing_style"].value, "direct and concise")
        self.assertEqual(by_category["strategy"].value, "training early")
        self.assertEqual(by_category["anti_strategy"].value, "long motivational messages")

    def test_detects_explicit_memory_requests(self) -> None:
        self.assertTrue(is_memory_request("remember that briefings should be blunt"))
        self.assertTrue(is_memory_request("note that morning workouts help"))
        self.assertFalse(is_memory_request("today I remembered to work out"))


class MemoryStorageTests(TestCase):
    def test_learns_and_upserts_memory_items(self) -> None:
        with TemporaryDirectory() as directory:
            service = MemoryService(LifeDatabase(Path(directory) / "life.sqlite3"))

            first = service.learn_from_message(
                "Remember that briefings should be direct and concise."
            )
            second = service.learn_from_message(
                "Remember that briefings should be direct and concise."
            )
            items = service.list_items(category="briefing_style")

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["times_seen"], 2)

    def test_briefing_context_groups_active_memory(self) -> None:
        with TemporaryDirectory() as directory:
            service = MemoryService(LifeDatabase(Path(directory) / "life.sqlite3"))
            service.learn_from_message(
                "I like Swiss minimalist plots. Training early works for me."
            )

            context = service.briefing_context()

            self.assertIn("preference", context)
            self.assertIn("strategy", context)
            self.assertEqual(context["strategy"][0]["value"], "training early")
