from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .sync import API_URL, SYNC_SECRET


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:2b")
MAX_JOBS = int(os.getenv("GARMIN_COACH_AI_MAX_JOBS", "3"))
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))


def headers() -> dict[str, str]:
    return {"X-Sync-Secret": SYNC_SECRET} if SYNC_SECRET else {}


def get_json(path: str) -> dict[str, Any]:
    response = httpx.get(f"{API_URL}{path}", headers=headers(), timeout=25)
    response.raise_for_status()
    return response.json()


def post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(f"{API_URL}{path}", json=payload, headers=headers(), timeout=25)
    response.raise_for_status()
    return response.json()


def check_ollama() -> None:
    response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    response.raise_for_status()


def call_ollama(question: str, context: dict[str, Any]) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Eres Garmin Coach, un entrenador de running, ciclismo y fuerza. "
                "Respondes en espanol claro, directo y cercano. "
                "Usa solo los datos del contexto; si falta un dato, dilo. "
                "No inventes metricas, actividades ni diagnosticos medicos. "
                "Da decisiones practicas para hoy o manana cuando sea posible. "
                "No muestres razonamiento interno. "
                "Limita la respuesta a 140 palabras."
            ),
        },
        {
            "role": "user",
            "content": (
                "/no_think\n"
                "Pregunta del deportista:\n"
                f"{question}\n\n"
                "Contexto Garmin compacto:\n"
                f"{json.dumps(compact_context(context), ensure_ascii=True)}"
            ),
        },
    ]
    response = httpx.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.25, "num_ctx": 4096, "num_predict": 220},
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    content = (data.get("message") or {}).get("content") or data.get("response") or ""
    return clean_answer(str(content))


def clean_answer(value: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL | re.IGNORECASE)
    value = value.strip()
    if len(value) > 3500:
        value = value[:3490].rstrip() + "..."
    return value or "No he podido generar una respuesta util con el contexto disponible."


def compact_context(context: dict[str, Any]) -> dict[str, Any]:
    sync = context.get("sync") or {}
    payload = sync.get("payload") or {}
    summary = payload.get("summary") or {}
    wellness = payload.get("wellness") or {}
    physiology = payload.get("physiology") or {}
    activities = summary.get("activities") or []

    return {
        "last_sync": sync.get("received_at"),
        "race": payload.get("race"),
        "profile": _profile_payload(context.get("profile")),
        "summary": {
            "runs_count_120d": summary.get("runs_count_120d"),
            "km_28d": summary.get("km_28d"),
            "km_56d": summary.get("km_56d"),
            "avg_weekly_km_8w": summary.get("avg_weekly_km_8w"),
            "longest_120d": summary.get("longest_120d"),
            "today": summary.get("today"),
            "week": summary.get("week"),
            "sports": summary.get("sports"),
            "fatigue": summary.get("fatigue"),
            "next_workout": summary.get("next_workout"),
        },
        "recent_activities": activities[-8:],
        "wellness": wellness,
        "physiology": physiology,
        "checkins": context.get("checkins") or [],
        "history": compact_history(context.get("history") or []),
    }


def compact_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in history[-4:]:
        payload = item.get("payload") or {}
        summary = payload.get("summary") or {}
        rows.append(
            {
                "received_at": item.get("received_at"),
                "generated_at": payload.get("generated_at"),
                "km_28d": summary.get("km_28d"),
                "avg_weekly_km_8w": summary.get("avg_weekly_km_8w"),
                "fatigue": summary.get("fatigue"),
            }
        )
    return rows


def _profile_payload(document: dict[str, Any] | None) -> dict[str, Any]:
    if not document:
        return {}
    profile = document.get("profile", document)
    return profile if isinstance(profile, dict) else {}


def process_job(job: dict[str, Any], context: dict[str, Any]) -> None:
    job_id = job["id"]
    try:
        check_ollama()
        answer = call_ollama(str(job.get("text") or ""), context)
        post_json(f"/ai/jobs/{job_id}/complete", {"status": "completed", "answer": answer})
        print(json.dumps({"ok": True, "job": job_id, "status": "completed"}))
    except Exception as exc:
        post_json(f"/ai/jobs/{job_id}/complete", {"status": "failed", "error": str(exc)[:500]})
        raise


def main() -> int:
    processed = 0
    for _ in range(MAX_JOBS):
        payload = get_json("/ai/jobs/next")
        job = payload.get("job")
        if not job:
            break
        process_job(job, payload.get("context") or {})
        processed += 1
    print(json.dumps({"ok": True, "processed": processed, "model": OLLAMA_MODEL}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
