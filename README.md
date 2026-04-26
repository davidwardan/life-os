# Life OS

Local-first personal logging and briefing system.

Phase 1 focuses on the core data loop:

1. Write a messy daily note.
2. Store the raw message.
3. Extract structured life logs.
4. Save everything locally in SQLite.
5. Review the result in a minimal web interface.

The agent and messaging integrations will sit on top of this core instead of owning the data.

## Stack

- FastAPI backend
- SQLite local database
- Standard-library SQLite persistence
- Deterministic extractor for phase 1 validation
- Minimal Swiss-style web surface served by FastAPI

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn backend.app.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000
```

## Optional OpenRouter Extraction

Phase 2 supports OpenRouter for schema-validated LLM extraction. By default, the app uses the deterministic local extractor.

```bash
export OPENROUTER_API_KEY="..."
export LIFE_OS_EXTRACTOR=llm
export OPENROUTER_MODEL="nvidia/nemotron-3-super-120b-a12b:free"
export OPENROUTER_FALLBACK_MODELS="nvidia/nemotron-3-nano-30b-a3b:free"
uvicorn backend.app.main:app --reload
```

Use `LIFE_OS_EXTRACTOR=auto` to use OpenRouter when configured and deterministic extraction otherwise.

## Telegram Setup

Phase 3 adds a Telegram webhook endpoint:

```text
POST /api/telegram/webhook
```

Credentials needed from you:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_WEBHOOK_SECRET=
```

Place these in the ignored local `.env` file, not in source code.

Create the bot token with BotFather. Get your numeric Telegram user ID from a bot such as `@userinfobot`, then put it in `TELEGRAM_ALLOWED_USER_IDS`. Keep the allowlist enabled before exposing the webhook.

For local development, keep confirmations disabled if you do not want the app to call Telegram:

```bash
export TELEGRAM_SEND_CONFIRMATIONS=false
```

When the app is reachable through a secure public URL, set the Telegram webhook with:

```bash
python scripts/set_telegram_webhook.py https://your-public-url.example
```

Do not put real tokens in the repository.

### Free ngrok Tunnel

ngrok free is enough for development webhook testing. Add your free ngrok authtoken to the ignored `.env` file:

```text
NGROK_AUTHTOKEN=
```

Start the local app:

```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

In another terminal, start ngrok:

```bash
python scripts/start_ngrok.py
```

The script prints the public HTTPS URL. Register that URL with Telegram:

```bash
python scripts/set_telegram_webhook.py https://your-ngrok-url.ngrok-free.app
```

## Test

```bash
python -m unittest discover -s tests
```

## Phase Plan

### Phase 1: Local Logging Core

- Raw message archive
- Structured logs for nutrition, workout, wellbeing, career, and journal
- Local SQLite storage
- Minimal local dashboard
- Validation tests

### Phase 2: LLM Extraction

- Add typed LLM JSON extraction through OpenRouter
- Add confidence thresholds and clarification prompts
- Keep deterministic validation before database writes

### Phase 3: Telegram

- Telegram webhook
- User allowlist
- Optional message confirmations

### Phase 4: Analytics And Plots

- Safe plot specifications
- Known SQL query mappings
- Chart images for chat and dashboard charts

### Phase 5: Morning Briefing

- Scheduled local job
- Deterministic trend features
- Agent-written daily guidance

### Phase 6: OpenClaw / WhatsApp

- Optional gateway integration
- Narrow Life OS tools only
- No broad filesystem, shell, or arbitrary SQL access
