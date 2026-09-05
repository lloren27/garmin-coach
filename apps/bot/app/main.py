from __future__ import annotations

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from .coach import (
    format_adjust,
    format_bike,
    format_checkin_help,
    format_checkin_saved,
    format_fatigue,
    format_feedback,
    format_help,
    format_health,
    format_latest,
    format_load,
    format_malaga,
    format_next,
    format_profile,
    format_profile_help,
    format_profile_saved,
    format_sync_requested,
    format_syncinfo,
    format_status,
    format_strength,
    format_today,
    format_trend,
    merge_profile,
    format_week,
    parse_checkin,
    parse_profile,
)
from .config import settings
from .store import (
    complete_sync_request,
    load_checkins,
    load_profile,
    load_sync,
    load_sync_history,
    load_sync_request,
    save_checkin,
    save_profile,
    save_sync_request,
    save_sync,
)


app = FastAPI(title="Garmin Coach")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sync")
async def sync(payload: dict, x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    document = save_sync(payload)
    request_state = load_sync_request()
    if request_state and request_state.get("status") == "pending":
        complete_sync_request(status="completed")
    return {"ok": True, "received_at": document["received_at"]}


@app.post("/sync/request")
async def request_sync(payload: dict | None = None, x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    payload = payload or {}
    document = save_sync_request(str(payload.get("requested_by")) if payload.get("requested_by") else None)
    return {"ok": True, "request": document}


@app.get("/sync/request")
def sync_request(x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    document = load_sync_request()
    return {"request": document, "pending": bool(document and document.get("status") == "pending")}


@app.post("/sync/request/complete")
async def sync_request_complete(payload: dict | None = None, x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    payload = payload or {}
    status = str(payload.get("status") or "completed")
    if status not in {"completed", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    error = str(payload.get("error"))[:500] if payload.get("error") else None
    document = complete_sync_request(status=status, error=error)
    return {"ok": True, "request": document}


@app.get("/status")
def status(x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    return {"sync": load_sync()}


@app.get("/history")
def history(x_sync_secret: str | None = Header(default=None), limit: int = 10) -> dict:
    require_sync_secret(x_sync_secret)
    return {"history": load_sync_history(min(max(limit, 1), 50))}


@app.get("/checkins")
def checkins(x_sync_secret: str | None = Header(default=None), limit: int = 10) -> dict:
    require_sync_secret(x_sync_secret)
    return {"checkins": load_checkins(min(max(limit, 1), 50))}


@app.get("/profile")
def profile(x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    return {"profile": load_profile()}


def require_sync_secret(x_sync_secret: str | None) -> None:
    if settings.sync_secret and x_sync_secret != settings.sync_secret:
        raise HTTPException(status_code=401, detail="Invalid sync secret")


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    update = await request.json()
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    text = (message.get("text") or "").strip()

    if settings.telegram_allowed_user_id:
        if str(user.get("id")) != settings.telegram_allowed_user_id:
            return {"ok": True}

    chat_id = chat.get("id")
    if not chat_id:
        return {"ok": True}

    response = route_message(text, str(user.get("id")) if user.get("id") else None)
    await send_telegram_message(chat_id, response)
    return {"ok": True}


def route_message(text: str, user_id: str | None = None) -> str:
    sync = load_sync()
    profile = load_profile()
    command = text.split(maxsplit=1)[0].lower().split("@", 1)[0] if text else ""
    args = text.split(maxsplit=1)[1].strip() if text and len(text.split(maxsplit=1)) > 1 else ""
    if command in {"/start", "/help"}:
        return format_help()
    if command == "/hoy":
        return format_today(sync)
    if command == "/semana":
        return format_week(sync)
    if command == "/ultima":
        return format_latest(sync)
    if command == "/proximo":
        return format_next(sync)
    if command == "/fatiga":
        return format_fatigue(sync)
    if command == "/salud":
        return format_health(sync)
    if command == "/carga":
        return format_load(sync, profile)
    if command == "/tendencia":
        return format_trend(sync, load_sync_history())
    if command == "/feedback":
        return format_feedback(sync, load_checkins(), profile)
    if command == "/sync":
        document = save_sync_request(user_id)
        return format_sync_requested(document, sync)
    if command == "/perfil":
        if not args:
            return format_profile(profile)
        update = parse_profile(args, user_id)
        recognized = any(key not in {"user_id", "raw"} for key in update)
        if not recognized:
            return format_profile_help()
        document = save_profile(merge_profile(profile, update, user_id))
        return format_profile_saved(document)
    if command == "/checkin":
        if not args:
            return format_checkin_help()
        document = save_checkin(parse_checkin(args, user_id))
        return format_checkin_saved(document)
    if command == "/ajustar":
        return format_adjust(sync, load_checkins(), args, profile)
    if command == "/bici":
        return format_bike(sync, profile)
    if command == "/fuerza":
        return format_strength(sync)
    if command == "/malaga":
        return format_malaga(sync, profile)
    if command == "/status":
        return format_status(sync)
    if command == "/syncinfo":
        return format_syncinfo(sync, load_sync_request())
    return "Te leo. Usa /help para ver los comandos disponibles."


async def send_telegram_message(chat_id: int | str, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})
