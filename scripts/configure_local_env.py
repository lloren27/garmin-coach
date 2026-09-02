#!/usr/bin/env python3
"""Create a local .env for Garmin Coach without exposing secrets in chat."""

from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from getpass import getpass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


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


def write_env(values: dict[str, str]) -> None:
    ordered_keys = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_ID",
        "SYNC_SECRET",
        "PUBLIC_BASE_URL",
        "OPENAI_API_KEY",
        "GARMINTOKENS",
        "GARMIN_COACH_API_URL",
    ]
    lines = []
    for key in ordered_keys:
        value = values.get(key, "")
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV_FILE.chmod(0o600)


def telegram_api(token: str, method: str, params: dict[str, str] | None = None) -> dict:
    query = urllib.parse.urlencode(params or {})
    url = f"https://api.telegram.org/bot{token}/{method}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def validate_bot(token: str) -> dict:
    try:
        payload = telegram_api(token, "getMe")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Telegram rechazo el token: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se pudo conectar con Telegram: {exc}") from exc
    if not payload.get("ok"):
        raise SystemExit(f"Telegram devolvio error: {payload}")
    return payload["result"]


def discover_user_id(token: str) -> str:
    print()
    print("Para restringir el bot a tu usuario:")
    print("1. Abre Telegram y envia /start a tu bot.")
    print("2. Pulsa Enter aqui para buscar tu ultimo mensaje con getUpdates.")
    input("Pulsa Enter cuando ya hayas escrito al bot...")

    payload = telegram_api(token, "getUpdates", {"limit": "10", "timeout": "5"})
    updates = payload.get("result") or []
    user_ids: list[tuple[str, str]] = []
    for update in updates:
        message = update.get("message") or update.get("edited_message") or {}
        user = message.get("from") or {}
        if user.get("id"):
            label = " ".join(
                part
                for part in [user.get("first_name"), user.get("last_name"), user.get("username")]
                if part
            )
            user_ids.append((str(user["id"]), label or "sin nombre"))

    if not user_ids:
        print("No encontre mensajes todavia. Puedes rellenar TELEGRAM_ALLOWED_USER_ID despues.")
        return ""

    print()
    print("Usuarios encontrados:")
    for index, (user_id, label) in enumerate(user_ids, start=1):
        print(f"{index}. {label}: {user_id}")
    choice = input("Elige numero, o deja vacio para usar el primero: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(user_ids):
        return user_ids[int(choice) - 1][0]
    return user_ids[0][0]


def main() -> int:
    values = load_env(EXAMPLE_FILE)
    values.update(load_env(ENV_FILE))

    token = getpass("Pega el TELEGRAM_BOT_TOKEN de BotFather: ").strip()
    if not token:
        raise SystemExit("Token vacio; no se ha modificado .env")

    bot = validate_bot(token)
    print(f"Bot verificado: @{bot.get('username')} ({bot.get('first_name')})")

    values["TELEGRAM_BOT_TOKEN"] = token
    values["SYNC_SECRET"] = values.get("SYNC_SECRET") or secrets.token_urlsafe(32)
    values["GARMINTOKENS"] = values.get("GARMINTOKENS") or "~/.garminconnect"
    values["GARMIN_COACH_API_URL"] = values.get("GARMIN_COACH_API_URL") or "http://127.0.0.1:8000"

    if not values.get("TELEGRAM_ALLOWED_USER_ID"):
        values["TELEGRAM_ALLOWED_USER_ID"] = discover_user_id(token)

    write_env(values)
    print()
    print(f"Configuracion guardada en {ENV_FILE}")
    print("Permisos aplicados: 600")
    print("Siguiente paso: desplegar apps/bot en Railway y configurar el webhook.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
