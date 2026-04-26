# Deployment

This guide deploys Life OS with automatic deploys from `main` while keeping the database persistent on a free SQLite-compatible service.

## Recommended Free Stack

Use:

- Koyeb Free Instance for the FastAPI web service.
- Turso Free plan for SQLite-compatible persistence.
- OpenRouter for extraction.
- Telegram webhook for chat input.

Why this shape:

- Koyeb can build from GitHub and redeploy automatically whenever `main` changes.
- Koyeb Free Instances are useful for hobby web services, but their local filesystem is not persistent.
- Turso gives the app a persistent SQLite-compatible database without changing the data model to Postgres.

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

## 2. Deploy The Web Service On Koyeb

In Koyeb:

1. Create a new Web Service.
2. Select GitHub as the deployment method.
3. Select `davidwardan/life-os`.
4. Select branch `main`.
5. Select the Dockerfile builder.
6. Use the Free Instance.
7. Expose port `8000`.
8. Keep autodeploy enabled.

Koyeb will build the repository and run the `Dockerfile`.

## 3. Add Environment Variables

Set these in Koyeb. Do not commit real values.

```text
LIFE_OS_TIMEZONE=America/Toronto
LIFE_OS_EXTRACTOR=auto
LIFE_OS_LLM_TIMEOUT_SECONDS=60

OPENROUTER_API_KEY=
OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3-nano-30b-a3b:free

TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_SEND_CONFIRMATIONS=true

TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=
TURSO_REPLICA_PATH=/tmp/life-os-turso-replica.sqlite3
TURSO_SYNC_INTERVAL_SECONDS=60
```

The replica path can live in `/tmp` because Turso is the durable source of truth.

## 4. Register The Telegram Webhook

After Koyeb deploys, use the public Koyeb URL:

```bash
python scripts/set_telegram_webhook.py https://your-life-os.koyeb.app
```

The script reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` from your local `.env`.

## 5. Verify

Check:

```text
https://your-life-os.koyeb.app/health
https://your-life-os.koyeb.app/api/telegram/status
https://your-life-os.koyeb.app/api/plots/supported
```

Then send a Telegram message:

```text
Energy 7, stress 4. Worked 2h on Life OS.
```

And then:

```text
plot my energy
```

## Notes

- Free instances can sleep. Telegram requests may have cold-start latency.
- Keep the Telegram allowlist enabled before exposing the webhook.
- Treat the cloud deployment as less private than your local machine. This is still sensitive life data.
- If you want maximum privacy later, move back to a local machine with Tailscale and use the same app.
