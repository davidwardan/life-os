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


DEFAULT_EXTRACTION_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"
DEFAULT_EXTRACTION_FALLBACK_MODELS = (
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-nano-9b-v2:free",
)
DEFAULT_PLANNER_MODEL = "nvidia/nemotron-nano-9b-v2:free"
DEFAULT_PLANNER_FALLBACK_MODELS = (
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
)
DEFAULT_CHAT_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"
DEFAULT_CHAT_FALLBACK_MODELS = (
    "nvidia/nemotron-nano-9b-v2:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
)
DEFAULT_BRIEFING_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_BRIEFING_FALLBACK_MODELS = (
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-nano-9b-v2:free",
)
DEFAULT_PLOTTING_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"
DEFAULT_PLOTTING_FALLBACK_MODELS = (
    "nvidia/nemotron-nano-9b-v2:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
)

LEGACY_OPENROUTER_MODEL = getenv("LIFE_OS_LLM_MODEL") or getenv("OPENROUTER_MODEL")
LEGACY_OPENROUTER_FALLBACK_MODELS = _split_csv(getenv("OPENROUTER_FALLBACK_MODELS", ""))


def _model_for_task(env_name: str, default: str) -> str:
    return getenv(env_name, LEGACY_OPENROUTER_MODEL or default)


def _fallbacks_for_task(env_name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    configured = getenv(env_name)
    if configured is not None:
        return _split_csv(configured)
    if LEGACY_OPENROUTER_FALLBACK_MODELS:
        return LEGACY_OPENROUTER_FALLBACK_MODELS
    return default


class Settings:
    timezone: str = getenv("LIFE_OS_TIMEZONE", "America/Toronto")
    web_username: str = getenv("LIFE_OS_WEB_USERNAME", "life-os")
    web_password: str | None = getenv("LIFE_OS_WEB_PASSWORD")
    require_web_auth: bool = _truthy(getenv("LIFE_OS_REQUIRE_WEB_AUTH")) or bool(getenv("RENDER"))
    extractor: str = getenv("LIFE_OS_EXTRACTOR", "deterministic").lower()
    openrouter_api_key: str | None = getenv("OPENROUTER_API_KEY")
    openrouter_base_url: str = getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model: str = LEGACY_OPENROUTER_MODEL or DEFAULT_EXTRACTION_MODEL
    openrouter_extraction_model: str = _model_for_task(
        "OPENROUTER_EXTRACTION_MODEL", DEFAULT_EXTRACTION_MODEL
    )
    openrouter_extraction_fallback_models: tuple[str, ...] = _fallbacks_for_task(
        "OPENROUTER_EXTRACTION_FALLBACK_MODELS", DEFAULT_EXTRACTION_FALLBACK_MODELS
    )
    openrouter_planner_model: str = _model_for_task(
        "OPENROUTER_PLANNER_MODEL", DEFAULT_PLANNER_MODEL
    )
    openrouter_planner_fallback_models: tuple[str, ...] = _fallbacks_for_task(
        "OPENROUTER_PLANNER_FALLBACK_MODELS", DEFAULT_PLANNER_FALLBACK_MODELS
    )
    openrouter_chat_model: str = _model_for_task("OPENROUTER_CHAT_MODEL", DEFAULT_CHAT_MODEL)
    openrouter_chat_fallback_models: tuple[str, ...] = _fallbacks_for_task(
        "OPENROUTER_CHAT_FALLBACK_MODELS", DEFAULT_CHAT_FALLBACK_MODELS
    )
    openrouter_briefing_model: str = _model_for_task(
        "OPENROUTER_BRIEFING_MODEL", DEFAULT_BRIEFING_MODEL
    )
    openrouter_briefing_fallback_models: tuple[str, ...] = _fallbacks_for_task(
        "OPENROUTER_BRIEFING_FALLBACK_MODELS", DEFAULT_BRIEFING_FALLBACK_MODELS
    )
    openrouter_plotting_model: str = _model_for_task(
        "OPENROUTER_PLOTTING_MODEL", DEFAULT_PLOTTING_MODEL
    )
    openrouter_plotting_fallback_models: tuple[str, ...] = _fallbacks_for_task(
        "OPENROUTER_PLOTTING_FALLBACK_MODELS", DEFAULT_PLOTTING_FALLBACK_MODELS
    )
    langextract_enabled: bool = _truthy(getenv("LIFE_OS_ENABLE_LANGEXTRACT"))
    langextract_model: str = getenv(
        "LIFE_OS_LANGEXTRACT_MODEL",
        LEGACY_OPENROUTER_MODEL or DEFAULT_EXTRACTION_MODEL,
    )
    openrouter_fallback_models: tuple[str, ...] = LEGACY_OPENROUTER_FALLBACK_MODELS
    llm_timeout_seconds: float = float(getenv("LIFE_OS_LLM_TIMEOUT_SECONDS", "60"))
    telegram_bot_token: str | None = getenv("TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str | None = getenv("TELEGRAM_WEBHOOK_SECRET")
    telegram_allowed_user_ids: frozenset[int] = frozenset(
        int(value.strip())
        for value in getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",")
        if value.strip()
    )
    telegram_send_confirmations: bool = _truthy(getenv("TELEGRAM_SEND_CONFIRMATIONS", "true"))
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
    todoist_api_token: str | None = getenv("TODOIST_API_TOKEN")
    todoist_base_url: str = getenv("TODOIST_BASE_URL", "https://api.todoist.com/api/v1")
    google_calendar_access_token: str | None = getenv("GOOGLE_CALENDAR_ACCESS_TOKEN")
    google_oauth_client_id: str | None = getenv("GOOGLE_OAUTH_CLIENT_ID") or getenv(
        "GOOGLE_CLIENT_ID"
    )
    google_oauth_client_secret: str | None = getenv("GOOGLE_OAUTH_CLIENT_SECRET") or getenv(
        "GOOGLE_CLIENT_SECRET"
    )
    google_oauth_refresh_token: str | None = getenv("GOOGLE_OAUTH_REFRESH_TOKEN")
    google_oauth_token_url: str = getenv(
        "GOOGLE_OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token"
    )
    google_calendar_base_url: str = getenv(
        "GOOGLE_CALENDAR_BASE_URL", "https://www.googleapis.com/calendar/v3"
    )
    google_calendar_ids: tuple[str, ...] = _split_csv(getenv("GOOGLE_CALENDAR_IDS", "primary"))
    integration_sync_lookahead_days: int = int(getenv("INTEGRATION_SYNC_LOOKAHEAD_DAYS", "7"))


settings = Settings()
