import base64
from unittest import TestCase

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.main import app


class WebAuthTests(TestCase):
    def setUp(self) -> None:
        self.original_username = settings.web_username
        self.original_password = settings.web_password
        self.original_require_web_auth = settings.require_web_auth
        settings.web_username = "life-os"
        settings.web_password = "correct-password"
        settings.require_web_auth = True
        self.client = TestClient(app)

    def tearDown(self) -> None:
        settings.web_username = self.original_username
        settings.web_password = self.original_password
        settings.require_web_auth = self.original_require_web_auth

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

    def test_fails_closed_when_auth_required_but_password_is_missing(self) -> None:
        settings.web_password = None

        response = self.client.get("/")

        self.assertEqual(response.status_code, 503)
        self.assertIn("LIFE_OS_WEB_PASSWORD", response.text)

    def test_auth_can_be_disabled_locally_when_password_is_missing(self) -> None:
        settings.web_password = None
        settings.require_web_auth = False

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)


def _auth_header(username: str, password: str) -> dict[str, str]:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}"}
