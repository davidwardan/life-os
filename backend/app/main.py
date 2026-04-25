from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import STATIC_DIR
from backend.app.config import settings
from backend.app.db import LifeDatabase
from backend.app.llm_extraction import ExtractionService
from backend.app.schemas import ExtractionStatus, LoggedMessage, MessageIn


app = FastAPI(title="Life OS", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
db = LifeDatabase()
extractor = ExtractionService()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/extraction/status", response_model=ExtractionStatus)
def extraction_status() -> ExtractionStatus:
    return ExtractionStatus(
        mode=settings.extractor,
        configured=bool(settings.openrouter_api_key) if settings.extractor in {"llm", "auto"} else True,
        model=settings.openrouter_model if settings.extractor in {"llm", "auto"} else None,
    )


@app.post("/api/messages", response_model=LoggedMessage)
async def create_message(message: MessageIn) -> LoggedMessage:
    parsed, method, error = await extractor.extract(message.text, message.entry_date)
    saved = db.save_message(message, parsed)
    return LoggedMessage(
        raw_message_id=saved["raw_message_id"],
        parsed=parsed,
        records=saved["records"],
        extraction_method=method,
        extraction_error=error,
    )


@app.get("/api/logs")
def list_logs(limit: int = 25) -> dict[str, object]:
    bounded_limit = max(1, min(limit, 100))
    return {"logs": db.recent_logs(bounded_limit)}
