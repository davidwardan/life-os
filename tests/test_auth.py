import base64
from unittest import TestCase

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.main import app


class WebAuthTests(TestCase):
    def setUp(self) -> None:
        self.original_username = settings.web_username
        self.original_password = settings.web_password
        settings.web_username = "life-os"
        settings.web_password = "correct-password"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        settings.web_username = self.original_username
        settings.web_password = self.original_password

    def test_blocks_dashboard_without_credentials(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response.headers["www-authenticate"])

    def test_allows_dashboard_with_basic_auth(self) -> None:
        response = self.client.get("/", headers=_auth_header("life-os", "correct-password"))

        self.assertEqual(response.status_code, 200)

    def test_rejects_wrong_basic_auth(self) -> None:
        response = self.client.get("/", headers=_auth_header("life-os", "wrong-password"))

        self.assertEqual(response.status_code, 401)

    def test_leaves_health_public_for_render(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)

    def test_leaves_telegram_webhook_public_to_telegram_secret_check(self) -> None:
        response = self.client.post("/api/telegram/webhook", json={})

        self.assertNotEqual(response.status_code, 401)

    def test_auth_is_disabled_when_password_is_missing(self) -> None:
        settings.web_password = None

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)


def _auth_header(username: str, password: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}
