#!/usr/bin/env python3
"""Register the Telegram webhook once the Railway URL exists."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def telegram_api(token: str, method: str, params: dict[str, str] | None = None) -> dict:
    data = urllib.parse.urlencode(params or {}).encode("utf-8")
    url = f"https://api.telegram.org/bot{token}/{method}"
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    values = load_env(ENV_FILE)
    token = values.get("TELEGRAM_BOT_TOKEN")
    base_url = values.get("PUBLIC_BASE_URL")

    if not token:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en .env")
    if not base_url:
        base_url = input("Railway public URL, por ejemplo https://app.up.railway.app: ").strip()
    if not base_url.startswith("https://"):
        raise SystemExit("Telegram exige una URL publica HTTPS para webhooks.")

    webhook_url = f"{base_url.rstrip('/')}/telegram/webhook"
    try:
        result = telegram_api(token, "setWebhook", {"url": webhook_url})
        info = telegram_api(token, "getWebhookInfo")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Telegram rechazo la peticion: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se pudo conectar con Telegram: {exc}") from exc

    print(json.dumps({"setWebhook": result, "webhookInfo": info}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
