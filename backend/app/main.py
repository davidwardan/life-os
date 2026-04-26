from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.app.briefing import BriefingService
from backend.app.config import STATIC_DIR
from backend.app.config import settings
from backend.app.db import LifeDatabase
from backend.app.llm_extraction import ExtractionService
from backend.app.memory import MemoryService
from backend.app.plotting import PlotRequest, PlotService, supported_plots
from backend.app.schemas import ExtractionStatus, LoggedMessage, MessageIn, TelegramStatus
from backend.app.telegram import make_telegram_service, verify_telegram_secret


app = FastAPI(title="Life OS", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
db = LifeDatabase()
extractor = ExtractionService()
plotter = PlotService(db)
memory_service = MemoryService(db)
briefing_service = BriefingService(db, memory_service=memory_service)
telegram_service = make_telegram_service(db, extractor)


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


@app.get("/api/telegram/status", response_model=TelegramStatus)
def telegram_status() -> TelegramStatus:
    return TelegramStatus(
        configured=bool(settings.telegram_bot_token),
        allowlist_enabled=bool(settings.telegram_allowed_user_ids),
        confirmations_enabled=settings.telegram_send_confirmations,
        webhook_secret_enabled=bool(settings.telegram_webhook_secret),
    )


@app.post("/api/messages", response_model=LoggedMessage)
async def create_message(message: MessageIn) -> LoggedMessage:
    parsed, method, error = await extractor.extract(message.text, message.entry_date)
    saved = db.save_message(message, parsed)
    memory_service.learn_from_message(message.text, parsed, saved["raw_message_id"])
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


@app.post("/api/plots")
def create_plot(request: PlotRequest) -> dict[str, str]:
    result = plotter.generate(request)
    return {"path": str(result.path), "title": result.title, "detail": result.detail}


@app.get("/api/plots/supported")
def list_supported_plots() -> dict[str, object]:
    return {"plots": supported_plots()}


@app.get("/api/briefing")
async def create_briefing(
    include_features: bool = False,
    x_life_os_cron_secret: str | None = Header(default=None),
) -> dict[str, object]:
    briefing = await briefing_service.generate()
    response: dict[str, object] = {
        "date": briefing.date.isoformat(),
        "text": briefing.text,
        "method": briefing.method,
        "error": briefing.error,
    }
    if include_features:
        if settings.briefing_cron_secret and x_life_os_cron_secret != settings.briefing_cron_secret:
            raise HTTPException(status_code=403, detail="Invalid briefing feature access secret")
        response["features"] = briefing.features
    return response


@app.get("/api/memory")
def list_memory(
    category: str | None = None,
    query: str | None = None,
    limit: int = 25,
    x_life_os_cron_secret: str | None = Header(default=None),
) -> dict[str, object]:
    if settings.briefing_cron_secret and x_life_os_cron_secret != settings.briefing_cron_secret:
        raise HTTPException(status_code=403, detail="Invalid memory access secret")
    return {"memory": memory_service.list_items(category=category, query=query, limit=limit)}


@app.post("/api/memory/backfill")
def backfill_memory(
    x_life_os_cron_secret: str | None = Header(default=None),
    limit: int = 200,
) -> dict[str, int]:
    if settings.briefing_cron_secret and x_life_os_cron_secret != settings.briefing_cron_secret:
        raise HTTPException(status_code=403, detail="Invalid memory backfill secret")
    return memory_service.backfill_from_raw_messages(limit)


@app.post("/api/briefing/send")
async def send_telegram_briefing(
    x_life_os_cron_secret: str | None = Header(default=None),
) -> dict[str, object]:
    if not settings.briefing_cron_secret:
        raise HTTPException(status_code=403, detail="BRIEFING_CRON_SECRET is not configured")
    if x_life_os_cron_secret != settings.briefing_cron_secret:
        raise HTTPException(status_code=403, detail="Invalid briefing cron secret")
    if not settings.telegram_briefing_chat_id:
        raise HTTPException(status_code=400, detail="TELEGRAM_BRIEFING_CHAT_ID is not configured")
    if telegram_service.client is None:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN is not configured")

    briefing = await briefing_service.generate()
    await telegram_service.client.send_message(settings.telegram_briefing_chat_id, briefing.text)
    return {
        "sent": True,
        "date": briefing.date.isoformat(),
        "method": briefing.method,
        "error": briefing.error,
    }


@app.post("/api/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, object]:
    if not verify_telegram_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    update = await request.json()
    result = await telegram_service.handle_update(update)
    if not result.ok and result.status == "unauthorized_user":
        raise HTTPException(status_code=403, detail="Telegram user is not allowed")

    return {
        "ok": result.ok,
        "status": result.status,
        "raw_message_id": result.raw_message_id,
        "extraction_method": result.extraction_method,
        "extraction_error": result.extraction_error,
        "plot_path": result.plot_path,
        "briefing_method": result.briefing_method,
        "briefing_error": result.briefing_error,
    }
