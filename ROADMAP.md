# Roadmap

Life OS is being built phase by phase. Each phase should be validated before the next one expands the system.

## Phase 1: Local Logging Core

Status: complete.

- Raw message storage
- SQLite source of truth
- Structured logs for wellbeing, nutrition, workouts, career, and journal
- Minimal local web surface
- Validation tests

## Phase 2: LLM Extraction

Status: active.

- OpenRouter extraction
- Fallback model support
- Deterministic fallback parser
- Typed Pydantic validation
- Bounded clarification questions

Next:

- Improve extraction fixtures with realistic daily notes
- Track explicit vs estimated values at the field level
- Add correction workflows

## Phase 3: Telegram

Status: active.

- Telegram webhook
- User allowlist
- Webhook secret validation
- Confirmation replies
- Multi-plot Telegram messages

Next:

- Better handling of follow-up answers
- Optional command hints
- Safer retry behavior for transient Telegram failures

## Phase 4: Analytics And Plots

Status: complete.

- Safe plot request parser
- Known SQL mappings
- Minimal chart images returned through Telegram
- `/api/plots` endpoint
- `/api/plots/supported` endpoint
- Multi-line Telegram plot batches
- Synthetic README plot example

Supported plot types:

- Sleep vs energy
- Stress vs workout load
- Workout frequency
- Exercise history
- Deep work by project
- Protein consistency
- Habit completion heatmap

## Phase 5: Morning Briefing

Status: planned.

- Scheduler
- Deterministic trend feature extraction
- Goal-aware daily guidance
- Telegram push notification
- Briefing archive for review

## Phase 6: Search And Memory

Status: planned.

- Journal search
- Optional local vector index
- Semantic retrieval over long reflections
- Memory references linked back to source messages

## Phase 7: Optional Gateways

Status: planned.

- WhatsApp integration
- OpenClaw skill integration
- Narrow tool permissions only
- No broad shell, browser, or filesystem access by default
