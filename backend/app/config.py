from pathlib import Path
from os import getenv


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
DEFAULT_DB_PATH = DATA_DIR / "life.sqlite3"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class Settings:
    extractor: str = getenv("LIFE_OS_EXTRACTOR", "deterministic").lower()
    openrouter_api_key: str | None = getenv("OPENROUTER_API_KEY")
    openrouter_base_url: str = getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model: str = getenv(
        "LIFE_OS_LLM_MODEL",
        getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    )
    llm_timeout_seconds: float = float(getenv("LIFE_OS_LLM_TIMEOUT_SECONDS", "30"))


settings = Settings()
