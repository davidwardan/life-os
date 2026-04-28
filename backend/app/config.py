from pathlib import Path
from os import getenv

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = ROOT_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "life.sqlite3"
TURSO_REPLICA_PATH = DATA_DIR / "turso-replica.sqlite3"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _truthy(value: str | None) -> bool:
    return (value or "").lower() in {"1", "true", "yes", "on"}


class Settings:
    timezone: str = getenv("LIFE_OS_TIMEZONE", "America/Toronto")
    web_username: str = getenv("LIFE_OS_WEB_USERNAME", "life-os")
    web_password: str | None = getenv("LIFE_OS_WEB_PASSWORD")
    require_web_auth: bool = _truthy(getenv("LIFE_OS_REQUIRE_WEB_AUTH")) or bool(getenv("RENDER"))
    extractor: str = getenv("LIFE_OS_EXTRACTOR", "deterministic").lower()
    openrouter_api_key: str | None = getenv("OPENROUTER_API_KEY")
    openrouter_base_url: str = getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model: str = getenv(
        "LIFE_OS_LLM_MODEL",
        getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    )
    langextract_enabled: bool = _truthy(getenv("LIFE_OS_ENABLE_LANGEXTRACT"))
    langextract_model: str = getenv(
        "LIFE_OS_LANGEXTRACT_MODEL",
        getenv("LIFE_OS_LLM_MODEL", getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")),
    )
    openrouter_fallback_models: tuple[str, ...] = _split_csv(
        getenv("OPENROUTER_FALLBACK_MODELS", "")
    )
    llm_timeout_seconds: float = float(getenv("LIFE_OS_LLM_TIMEOUT_SECONDS", "60"))
    telegram_bot_token: str | None = getenv("TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str | None = getenv("TELEGRAM_WEBHOOK_SECRET")
    telegram_allowed_user_ids: frozenset[int] = frozenset(
        int(value.strip())
        for value in getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
        if value.strip()
    )
    telegram_send_confirmations: bool = _truthy(getenv("TELEGRAM_SEND_CONFIRMATIONS", "true"))
    telegram_voice_notes_enabled: bool = _truthy(
        getenv("TELEGRAM_ENABLE_VOICE_NOTES", "true")
    )
    voice_transcription_backend: str = getenv(
        "TELEGRAM_VOICE_TRANSCRIPTION_BACKEND", "faster-whisper"
    ).lower()
    voice_transcription_api_key: str | None = getenv("TELEGRAM_VOICE_TRANSCRIPTION_API_KEY") or getenv(
        "OPENAI_API_KEY"
    )
    voice_transcription_base_url: str = getenv(
        "TELEGRAM_VOICE_TRANSCRIPTION_BASE_URL", "https://api.openai.com/v1"
    )
    voice_transcription_model: str = getenv("TELEGRAM_VOICE_TRANSCRIPTION_MODEL", "base")
    voice_transcription_device: str = getenv("TELEGRAM_VOICE_TRANSCRIPTION_DEVICE", "cpu")
    voice_transcription_compute_type: str = getenv(
        "TELEGRAM_VOICE_TRANSCRIPTION_COMPUTE_TYPE", "int8"
    )
    telegram_voice_max_bytes: int = int(getenv("TELEGRAM_VOICE_MAX_BYTES", str(20 * 1024 * 1024)))
    turso_database_url: str | None = getenv("TURSO_DATABASE_URL")
    turso_auth_token: str | None = getenv("TURSO_AUTH_TOKEN")
    turso_replica_path: Path = Path(getenv("TURSO_REPLICA_PATH", str(TURSO_REPLICA_PATH)))
    turso_sync_interval_seconds: int | None = (
        int(value) if (value := getenv("TURSO_SYNC_INTERVAL_SECONDS")) else None
    )
    briefing_cron_secret: str | None = getenv("BRIEFING_CRON_SECRET")
    telegram_briefing_chat_id: int | None = (
        int(value) if (value := getenv("TELEGRAM_BRIEFING_CHAT_ID")) else None
    )


settings = Settings()
