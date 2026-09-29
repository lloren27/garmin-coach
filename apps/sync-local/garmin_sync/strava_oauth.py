from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

from .strava_activity_provider import STRAVA_TOKEN_URL, StravaTokenStore


STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"


class StravaOAuthError(Exception):
    pass


def authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "force",
            "scope": "read,activity:read_all",
            "state": state,
        }
    )
    return f"{STRAVA_AUTHORIZE_URL}?{query}"


def callback_code(path: str, expected_state: str) -> str | None:
    query = parse_qs(urlsplit(path).query)
    state = (query.get("state") or [""])[0]
    code = (query.get("code") or [""])[0]
    if not code or state != expected_state:
        return None
    return code


def exchange_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    token_store: StravaTokenStore,
    token_url: str = STRAVA_TOKEN_URL,
) -> dict[str, Any]:
    try:
        response = requests.post(
            token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise StravaOAuthError("No se pudo conectar con Strava") from exc
    if response.status_code != 200:
        raise StravaOAuthError(f"Strava rechazo la autorizacion (HTTP {response.status_code})")
    try:
        payload = response.json()
    except ValueError as exc:
        raise StravaOAuthError("Strava devolvio una respuesta no valida") from exc
    if not isinstance(payload, dict):
        raise StravaOAuthError("Strava devolvio una respuesta no valida")
    access_token = _text(payload.get("access_token"))
    refresh_token = _text(payload.get("refresh_token"))
    expires_at = _integer(payload.get("expires_at"))
    if not access_token or not refresh_token or expires_at is None:
        raise StravaOAuthError("La respuesta de Strava no contiene todos los tokens")
    token_store.save(access_token, refresh_token, expires_at)
    athlete = payload.get("athlete") if isinstance(payload.get("athlete"), dict) else {}
    return {"ok": True, "athlete_id": _text(athlete.get("id"))}


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""
