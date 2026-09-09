from __future__ import annotations

import httpx
from fastapi import FastAPI, Header, HTTPException, Request

from .coach import (
    build_ai_brief,
    format_ai_help,
    format_ai_queued,
    format_adjust,
    format_bike,
    format_checkin_help,
    format_checkin_saved,
    format_fatigue,
    format_feedback,
    format_help,
    format_health,
    format_lab_test,
    format_lab_test_applied,
    format_lab_test_corrected,
    format_lab_test_correction_help,
    format_lab_test_discarded,
    format_lab_test_help,
    format_lab_test_queued,
    format_lab_tests,
    format_latest,
    format_load,
    format_malaga,
    format_natural_coach,
    format_next,
    format_profile,
    format_profile_help,
    format_profile_saved,
    format_running,
    format_sync_requested,
    format_syncinfo,
    format_status,
    format_strength,
    format_today,
    format_trend,
    format_voice_queued,
    format_zones,
    merge_profile,
    format_week,
    format_wattwise,
    parse_lab_test_correction,
    parse_checkin,
    parse_profile,
)
from .config import settings
from .store import (
    claim_next_ai_job,
    complete_ai_job,
    complete_sync_request,
    create_ai_job,
    discard_lab_test,
    load_checkins,
    load_lab_tests,
    load_pending_lab_test,
    load_profile,
    load_sync,
    load_sync_history,
    load_sync_request,
    load_wattwise,
    save_checkin,
    save_lab_test,
    save_profile,
    save_sync_request,
    save_sync,
    save_wattwise,
    mark_lab_test_applied,
    update_lab_test,
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


@app.post("/wattwise")
async def wattwise_snapshot(payload: dict, x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    document = save_wattwise(payload)
    return {"ok": True, "received_at": document["received_at"]}


@app.get("/wattwise")
def wattwise_status(x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    return {"wattwise": load_wattwise()}


@app.get("/checkins")
def checkins(x_sync_secret: str | None = Header(default=None), limit: int = 10) -> dict:
    require_sync_secret(x_sync_secret)
    return {"checkins": load_checkins(min(max(limit, 1), 50))}


@app.get("/profile")
def profile(x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    return {"profile": load_profile()}


@app.post("/lab-tests")
async def lab_tests_endpoint(payload: dict | None = None, x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    document = save_lab_test(payload or {})
    return {"ok": True, "lab_test": document, "message": format_lab_test(document)}


@app.get("/ai/jobs/next")
def next_ai_job(x_sync_secret: str | None = Header(default=None)) -> dict:
    require_sync_secret(x_sync_secret)
    job = claim_next_ai_job()
    if not job:
        return {"job": None}
    sync = load_sync()
    profile = load_profile()
    checkins = load_checkins(5)
    history = load_sync_history(4)
    wattwise = load_wattwise()
    return {
        "job": job,
        "context": {
            "coach_brief": build_ai_brief(str(job.get("text") or ""), sync, profile, checkins, history, wattwise),
            "sync": sync,
            "profile": profile,
            "checkins": checkins,
            "history": history,
            "wattwise": wattwise,
        },
    }


@app.post("/ai/jobs/{job_id}/complete")
async def complete_ai_job_endpoint(
    job_id: str,
    payload: dict | None = None,
    x_sync_secret: str | None = Header(default=None),
) -> dict:
    require_sync_secret(x_sync_secret)
    payload = payload or {}
    status = str(payload.get("status") or "completed")
    if status not in {"completed", "failed"}:
        raise HTTPException(status_code=400, detail="Invalid status")
    answer = str(payload.get("answer"))[:3500] if payload.get("answer") else None
    error = str(payload.get("error"))[:500] if payload.get("error") else None
    transcript = str(payload.get("transcript"))[:3500] if payload.get("transcript") else None
    response_mode = str(payload.get("response_mode"))[:40] if payload.get("response_mode") else None
    notify_telegram = bool(payload.get("notify_telegram", True))
    document = complete_ai_job(
        job_id,
        status=status,
        answer=answer,
        error=error,
        transcript=transcript,
        response_mode=response_mode,
    )
    if not document:
        raise HTTPException(status_code=404, detail="Job not found")
    chat_id = document.get("chat_id")
    if chat_id and notify_telegram:
        if status == "completed" and answer:
            await send_telegram_message(chat_id, answer)
        elif status == "failed":
            await send_telegram_message(chat_id, "No he podido procesarlo con el coach local. Revisa que el Mac y Ollama esten activos.")
    return {"ok": True, "job": document}


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
    caption = (message.get("caption") or "").strip()
    voice = message.get("voice") or message.get("audio")
    telegram_document = message.get("document")

    if settings.telegram_allowed_user_id:
        if str(user.get("id")) != settings.telegram_allowed_user_id:
            return {"ok": True}

    chat_id = chat.get("id")
    if not chat_id:
        return {"ok": True}

    user_id = str(user.get("id")) if user.get("id") else None
    if telegram_document and telegram_document.get("file_id"):
        if not is_supported_lab_test_document(telegram_document):
            response = "Documento no soportado. Para pruebas de esfuerzo usa PDF o DOCX con /prueba_esfuerzo."
        else:
            document = create_ai_job(
                chat_id=str(chat_id),
                user_id=user_id,
                text=caption,
                document_file_id=str(telegram_document.get("file_id")),
                document_unique_id=str(telegram_document.get("file_unique_id")) if telegram_document.get("file_unique_id") else None,
                document_name=str(telegram_document.get("file_name")) if telegram_document.get("file_name") else None,
                document_mime_type=str(telegram_document.get("mime_type")) if telegram_document.get("mime_type") else None,
                document_size=int(telegram_document.get("file_size")) if telegram_document.get("file_size") else None,
                source_kind="lab_test",
                response_mode="text",
            )
            response = format_lab_test_queued(document)
    elif voice and voice.get("file_id"):
        document = create_ai_job(
            chat_id=str(chat_id),
            user_id=user_id,
            text=(message.get("caption") or "").strip(),
            audio_file_id=str(voice.get("file_id")),
            audio_unique_id=str(voice.get("file_unique_id")) if voice.get("file_unique_id") else None,
            audio_duration=int(voice.get("duration")) if voice.get("duration") else None,
            source_kind="voice" if message.get("voice") else "audio",
            response_mode="voice",
        )
        response = format_voice_queued(document)
    else:
        response = route_message(text, user_id, str(chat_id))
    await send_telegram_message(chat_id, response)
    return {"ok": True}


def route_message(text: str, user_id: str | None = None, chat_id: str | None = None) -> str:
    sync = load_sync()
    profile = load_profile()
    wattwise = load_wattwise()
    ai_chat_id = chat_id or user_id or "telegram"
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
        return format_fatigue(sync, wattwise)
    if command == "/salud":
        return format_health(sync)
    if command == "/carga":
        return format_load(sync, profile, wattwise)
    if command in {"/running", "/correr", "/carga_running"}:
        return format_running(sync)
    if command == "/tendencia":
        return format_trend(sync, load_sync_history())
    if command == "/feedback":
        return format_feedback(sync, load_checkins(), profile, wattwise=wattwise)
    if command == "/coach":
        if not args:
            return format_ai_help()
        direct = format_natural_coach(args, sync, profile, load_checkins(), load_sync_history(), wattwise)
        if direct:
            return direct
        document = create_ai_job(chat_id=ai_chat_id, user_id=user_id, text=args)
        return format_ai_queued(document)
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
    if command == "/prueba_esfuerzo":
        return format_lab_test_help()
    if command == "/pruebas":
        return format_lab_tests(load_lab_tests())
    if command == "/ver_prueba":
        return format_lab_test(load_pending_lab_test() or (load_lab_tests(1)[-1] if load_lab_tests(1) else None))
    if command == "/zonas":
        return format_zones(profile, load_pending_lab_test() or (load_lab_tests(1)[-1] if load_lab_tests(1) else None))
    if command == "/aplicar_prueba":
        lab_test = find_lab_test_for_apply(args.split()[0] if args else None)
        if not lab_test:
            return format_lab_test_applied(None, profile)
        update = lab_test.get("profile_update") or {}
        if not update:
            return "La prueba no tiene una propuesta aplicable al perfil."
        profile_update = dict(update)
        profile_update["lab_test_id"] = lab_test.get("id")
        document = save_profile(merge_profile(profile, profile_update, user_id))
        applied = mark_lab_test_applied(str(lab_test.get("id")) if lab_test.get("id") else None)
        return format_lab_test_applied(applied or lab_test, document)
    if command == "/corregir_prueba":
        if not args:
            return format_lab_test_correction_help()
        test_id, correction_text = split_optional_lab_test_id(args)
        correction = parse_lab_test_correction(correction_text)
        if not correction.get("extracted") and not correction.get("profile_update"):
            return format_lab_test_correction_help()
        document = update_lab_test(test_id, correction.get("extracted") or {}, correction.get("profile_update") or {})
        return format_lab_test_corrected(document)
    if command == "/descartar_prueba":
        test_id = args.split()[0] if args else None
        document = discard_lab_test(test_id)
        return format_lab_test_discarded(document)
    if command == "/checkin":
        if not args:
            return format_checkin_help()
        document = save_checkin(parse_checkin(args, user_id))
        return format_checkin_saved(document)
    if command == "/ajustar":
        return format_adjust(sync, load_checkins(), args, profile)
    if command == "/bici":
        return format_bike(sync, profile, wattwise)
    if command in {"/potencia", "/wattwise"}:
        return format_wattwise(wattwise, sync, profile)
    if command == "/fuerza":
        return format_strength(sync)
    if command == "/malaga":
        return format_malaga(sync, profile)
    if command == "/status":
        return format_status(sync)
    if command == "/syncinfo":
        return format_syncinfo(sync, load_sync_request())
    if text and not command.startswith("/"):
        direct = format_natural_coach(text, sync, profile, load_checkins(), load_sync_history(), wattwise)
        if direct:
            return direct
        document = create_ai_job(chat_id=ai_chat_id, user_id=user_id, text=text)
        return format_ai_queued(document)
    return "Te leo. Usa /help para ver los comandos disponibles."


async def send_telegram_message(chat_id: int | str, text: str) -> None:
    if not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})


def is_supported_lab_test_document(document: dict) -> bool:
    filename = str(document.get("file_name") or "").lower()
    mime_type = str(document.get("mime_type") or "").lower()
    return (
        filename.endswith(".pdf")
        or filename.endswith(".docx")
        or mime_type == "application/pdf"
        or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def find_lab_test_for_apply(test_id: str | None = None) -> dict | None:
    if not test_id:
        return load_pending_lab_test()
    for item in reversed(load_lab_tests(100)):
        full_id = str(item.get("id") or "")
        if full_id == test_id or full_id.startswith(test_id):
            return item
    return None


def split_optional_lab_test_id(args: str) -> tuple[str | None, str]:
    first = args.split(maxsplit=1)[0] if args else ""
    if first and len(first) >= 4:
        for item in reversed(load_lab_tests(100)):
            full_id = str(item.get("id") or "")
            if full_id == first or full_id.startswith(first):
                rest = args.split(maxsplit=1)[1] if len(args.split(maxsplit=1)) > 1 else ""
                return full_id, rest
    return None, args
