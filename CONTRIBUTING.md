# Contributing

Life OS is early and intentionally local-first. Contributions should keep the core principle intact: the structured data system is the product, and the agent is only an interface to it.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m unittest discover -s tests
python -m uvicorn backend.app.main:app --reload
```

## Development Guidelines

- Keep personal data local by default.
- Do not commit `.env`, database files, generated local plots, or tokens.
- Prefer typed schemas and validation over free-form agent behavior.
- Preserve raw input alongside extracted records.
- Use deterministic analytics before asking an LLM to interpret trends.
- Keep the visual language minimal, crisp, and readable.
- Add focused tests when changing extraction, storage, Telegram, or plotting behavior.

## Good First Areas

- Improve dashboard review and edit flows.
- Add more plot types through safe query specifications.
- Add stronger extraction fixtures for messy real-world daily logs.
- Improve confirmation messages for multi-category logs.
- Add import/export tools for local backups.

## Planned Work

### Extraction

- Better multi-message context for follow-up answers.
- Field-level provenance: explicit, estimated, inferred, or user-corrected.
- Correction flow for editing a bad extraction from Telegram or the web UI.
- More robust meal, exercise, and career parsing.

### Analytics

- Weekly trend summaries.
- Habit and recovery heatmaps.
- Exercise history by movement.
- Nutrition completeness indicators.
- Project focus and deep work consistency views.

### Agent Behavior

- Morning briefing job.
- Bounded clarification strategy.
- User-configurable goals and constraints.
- Safe read-only query tools for the agent.
- Confirmation gates for destructive actions.

### Integrations

- WhatsApp support after Telegram stabilizes.
- Optional OpenClaw skill integration.
- Optional local embedding index for journal search.
- Tailscale or similar private-network deployment notes.

## Pull Request Checklist

- Tests pass with `python -m unittest discover -s tests`.
- No secrets are included.
- New behavior is documented if user-facing.
- Database changes include migration/backfill handling.
- Agent-facing tools do not expose arbitrary shell, filesystem, or SQL access.
