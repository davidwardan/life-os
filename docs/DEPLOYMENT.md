# Deployment

This guide deploys Life OS on Render with automatic deploys from `main`, while keeping the database persistent on a free SQLite-compatible service.

## Recommended Free Stack

Use:

- Render Free Web Service for the FastAPI app.
- Turso Free plan for SQLite-compatible persistence.
- OpenRouter for extraction.
- Telegram webhook for chat input.

Why this shape:

- Render can deploy from GitHub and redeploy automatically whenever `main` changes.
- Render supports Docker builds from a repo `Dockerfile`.
- Render free web services have an ephemeral filesystem, so a local SQLite file inside the service is not durable.
- Turso keeps the current SQLite-style data model but stores the durable database outside the Render container.

## 1. Create A Turso Database

Install and log in to the Turso CLI, then create a database:

```bash
turso db create life-os
turso db show --url life-os
turso db tokens create life-os
```

Keep the URL and token. They become:

```text
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=
```

## 2. Deploy On Render

The repo includes `render.yaml`, so the cleanest path is Render Blueprints:

1. Open Render.
2. Click **New > Blueprint**.
3. Connect `davidwardan/life-os`.
4. Select branch `main`.
5. Confirm the `render.yaml` blueprint.
6. Enter the secret environment variables Render prompts for.
7. Deploy.

The blueprint creates one free Docker web service:

```text
name: life-os
runtime: docker
plan: free
branch: main
autoDeployTrigger: commit
healthCheckPath: /health
```

`autoDeployTrigger: commit` means Render deploys again when you push to `main`.

## 3. Add Environment Variables

The blueprint sets non-secret defaults and prompts for secrets with `sync: false`.

Required secrets:

```text
OPENROUTER_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_BRIEFING_CHAT_ID=
BRIEFING_CRON_SECRET=
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=
```

Non-secret defaults in `render.yaml`:

```text
LIFE_OS_TIMEZONE=America/Toronto
LIFE_OS_EXTRACTOR=auto
LIFE_OS_LLM_TIMEOUT_SECONDS=60
OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3-nano-30b-a3b:free
TELEGRAM_SEND_CONFIRMATIONS=true
TURSO_REPLICA_PATH=/tmp/life-os-turso-replica.sqlite3
TURSO_SYNC_INTERVAL_SECONDS=60
```

The replica path can live in `/tmp` because Turso is the durable source of truth.

## 4. Register The Telegram Webhook

After Render deploys, use the public Render URL:

```bash
python scripts/set_telegram_webhook.py https://your-life-os.onrender.com
```

The script reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` from your local `.env`.

## 5. Verify

Check:

```text
https://your-life-os.onrender.com/health
https://your-life-os.onrender.com/api/telegram/status
https://your-life-os.onrender.com/api/plots/supported
https://your-life-os.onrender.com/api/briefing
```

To inspect memory or detailed briefing features, include your cron secret:

```bash
curl -H "X-Life-Os-Cron-Secret: your-briefing-secret" \
  "https://your-life-os.onrender.com/api/memory"

curl -H "X-Life-Os-Cron-Secret: your-briefing-secret" \
  "https://your-life-os.onrender.com/api/briefing?include_features=true"
```

Then send a Telegram message:

```text
Energy 7, stress 4. Worked 2h on Life OS.
```

And then:

```text
plot my energy
```

For a manual briefing test:

```text
morning brief
```

For scheduled delivery, configure a free external cron service to send:

```text
POST https://your-life-os.onrender.com/api/briefing/send
X-Life-Os-Cron-Secret: your-briefing-secret
```

## Notes

- Render free services spin down when idle, so Telegram requests can have cold-start latency.
- Render Cron Jobs have a minimum monthly charge, so for a fully free morning briefing use a free external HTTP cron service that sends `POST /api/briefing/send` with the `X-Life-Os-Cron-Secret` header.
- Keep the Telegram allowlist enabled before exposing the webhook.
- Treat cloud deployment as less private than your local machine. This is sensitive life data.
- If you want maximum privacy later, move back to a local machine with Tailscale and use the same app.
