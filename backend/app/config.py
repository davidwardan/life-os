from pathlib import Path
from os import getenv

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "life.sqlite3"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


class Settings:
    timezone: str = getenv("LIFE_OS_TIMEZONE", "America/Toronto")
    extractor: str = getenv("LIFE_OS_EXTRACTOR", "deterministic").lower()
    openrouter_api_key: str | None = getenv("OPENROUTER_API_KEY")
    openrouter_base_url: str = getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model: str = getenv(
        "LIFE_OS_LLM_MODEL",
        getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    )
    openrouter_fallback_models: tuple[str, ...] = _split_csv(
        getenv("OPENROUTER_FALLBACK_MODELS", "")
    )
    llm_timeout_seconds: float = float(getenv("LIFE_OS_LLM_TIMEOUT_SECONDS", "30"))
    telegram_bot_token: str | None = getenv("TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str | None = getenv("TELEGRAM_WEBHOOK_SECRET")
    telegram_allowed_user_ids: frozenset[int] = frozenset(
        int(value.strip())
        for value in getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
        if value.strip()
    )
    telegram_send_confirmations: bool = getenv("TELEGRAM_SEND_CONFIRMATIONS", "true").lower() in {
        "1",
        "true",
        "yes",
    }


settings = Settings()
