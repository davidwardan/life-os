from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Register the Life OS Telegram webhook.")
    parser.add_argument("public_url", help="Public HTTPS base URL, for example https://example.trycloudflare.com")
    args = parser.parse_args()

    load_dotenv(ROOT_DIR / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not token:
        print("TELEGRAM_BOT_TOKEN is missing in .env", file=sys.stderr)
        return 1
    if not secret:
        print("TELEGRAM_WEBHOOK_SECRET is missing in .env", file=sys.stderr)
        return 1

    base_url = args.public_url.rstrip("/")
    if not base_url.startswith("https://"):
        print("Telegram requires an HTTPS public URL.", file=sys.stderr)
        return 1

    webhook_url = f"{base_url}/api/telegram/webhook"
    payload = urllib.parse.urlencode(
        {
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": json.dumps(["message", "edited_message"]),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data=payload,
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        print("Telegram rejected webhook registration.", file=sys.stderr)
        print(result, file=sys.stderr)
        return 1

    print(f"Webhook registered for {webhook_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

