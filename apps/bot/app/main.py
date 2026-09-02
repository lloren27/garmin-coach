from __future__ import annotations

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from .coach import format_malaga, format_status
from .config import settings
from .store import load_sync, save_sync


app = FastAPI(title="Garmin Coach")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/sync")
async def sync(payload: dict, x_sync_secret: str | None = Header(default=None)) -> dict:
    if settings.sync_secret and x_sync_secret != settings.sync_secret:
        raise HTTPException(status_code=401, detail="Invalid sync secret")
    document = save_sync(payload)
    return {"ok": True, "received_at": document["received_at"]}


@app.get("/status")
def status() -> dict:
    return {"sync": load_sync()}


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

    response = route_message(text)
    await send_telegram_message(chat_id, response)
    return {"ok": True}


def route_message(text: str) -> str:
    sync = load_sync()
    command = text.split(maxsplit=1)[0].lower() if text else ""
    if command in {"/start", "/help"}:
        return "Comandos: /status, /malaga, /syncinfo"
    if command == "/malaga":
        return format_malaga(sync)
    if command in {"/status", "/semana", "/ultima"}:
        return format_status(sync)
    if command == "/syncinfo":
        if not sync:
            return "Sin sincronizaciones todavia."
        return f"Ultima sincronizacion recibida: {sync.get('received_at')}"
    return "Te leo. Por ahora usa /status o /malaga mientras activo el coach conversacional."


async def send_telegram_message(chat_id: int | str, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})
