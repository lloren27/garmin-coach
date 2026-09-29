#!/usr/bin/env python3
"""Authorize Garmin Coach to read the owner's Strava activities."""

from __future__ import annotations

import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "sync-local"))

from garmin_sync.strava_activity_provider import StravaTokenStore  # noqa: E402
from garmin_sync.strava_oauth import (  # noqa: E402
    StravaOAuthError,
    authorization_url,
    callback_code,
    exchange_authorization_code,
)


CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/strava/callback"
DEFAULT_TOKEN_FILE = Path("~/Library/Application Support/Garmin Coach/strava-tokens.json").expanduser()


def main() -> int:
    load_dotenv(ROOT / ".env")
    client_id = os.getenv("STRAVA_CLIENT_ID", "").strip()
    client_secret = os.getenv("STRAVA_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit("Faltan STRAVA_CLIENT_ID y STRAVA_CLIENT_SECRET en el .env raiz.")

    token_file = Path(os.getenv("STRAVA_TOKEN_FILE", str(DEFAULT_TOKEN_FILE))).expanduser()
    state = secrets.token_urlsafe(24)
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            code = callback_code(self.path, state)
            result["code"] = code or ""
            status = 200 if code else 400
            message = (
                "Autorizacion completada. Ya puedes cerrar esta pestaña."
                if code
                else "La autorizacion no es valida. Vuelve al Terminal e intentalo de nuevo."
            )
            body = f"<html><body><h2>{message}</h2></body></html>".encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    url = authorization_url(client_id, REDIRECT_URI, state)
    print("Antes de continuar, configura 'localhost' como dominio de callback en Strava.")
    print("Se abrira Strava para solicitar lectura de actividades, incluidas las privadas.")
    with HTTPServer((CALLBACK_HOST, CALLBACK_PORT), CallbackHandler) as server:
        server.timeout = 300
        if not webbrowser.open(url):
            print(f"Abre manualmente esta URL:\n{url}")
        server.handle_request()

    code = result.get("code")
    if not code:
        raise SystemExit("No se recibio una autorizacion valida; no se modificaron los tokens.")
    try:
        exchange = exchange_authorization_code(
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=REDIRECT_URI,
            token_store=StravaTokenStore(token_file),
        )
    except StravaOAuthError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"Strava autorizado para el atleta {exchange.get('athlete_id') or 'actual'}.")
    print(f"Tokens guardados de forma local en {token_file} con permisos 600.")
    print("Ya puedes ejecutar /sync cmf desde Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
