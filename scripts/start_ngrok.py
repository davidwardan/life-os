from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(ROOT_DIR / ".env")
    authtoken = os.getenv("NGROK_AUTHTOKEN")
    if not authtoken:
        print("NGROK_AUTHTOKEN is missing in .env", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["NGROK_AUTHTOKEN"] = authtoken
    command = [
        "ngrok",
        "http",
        "8000",
        "--log",
        "stdout",
        "--log-format",
        "json",
    ]

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    assert process.stdout is not None

    public_url = None
    try:
        for line in process.stdout:
            print(line, end="")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = event.get("url")
            if isinstance(url, str) and url.startswith("https://"):
                public_url = url
                print(f"\nPublic URL: {public_url}")
                print(f"Telegram webhook URL: {public_url}/api/telegram/webhook")
    except KeyboardInterrupt:
        process.terminate()
        return 0

    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
