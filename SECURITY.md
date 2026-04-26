# Security

Life OS stores sensitive personal information: health, mood, nutrition, workouts, career progress, and journal notes. Treat the local machine and Telegram bot as private infrastructure.

## Secrets

Never commit:

- `.env`
- `OPENROUTER_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `NGROK_AUTHTOKEN`
- SQLite databases
- Generated local plots from real data

The repository ignores `.env`, `.env.*`, `data/`, `*.sqlite`, and `*.sqlite3`.

## Telegram Safety

- Keep `TELEGRAM_ALLOWED_USER_IDS` set.
- Keep `TELEGRAM_WEBHOOK_SECRET` set.
- Do not expose the webhook without authentication controls.
- Use ngrok for development only.
- Prefer Tailscale or another private access layer for longer-running personal deployments.

## Agent Permissions

The agent should be allowed to:

- Create log entries
- Read summarized data
- Generate safe predefined plots
- Ask bounded clarification questions

The agent should not be allowed to:

- Run shell commands
- Execute arbitrary SQL
- Read arbitrary files
- Delete records without confirmation
- Send messages to other people
- Access email, calendars, or financial accounts without a separate permission design

## Reporting Issues

If this project becomes public and you find a security issue, open a private disclosure channel before posting exploit details publicly.
