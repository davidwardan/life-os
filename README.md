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
export LIFE_OS_LLM_MODEL="openai/gpt-4o-mini"
uvicorn backend.app.main:app --reload
```

Use `LIFE_OS_EXTRACTOR=auto` to use OpenRouter when configured and deterministic extraction otherwise.

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
- Message confirmations

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
