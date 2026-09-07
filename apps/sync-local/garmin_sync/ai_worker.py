from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import httpx

from .lab_tests import parse_lab_test
from .sync import API_URL, SYNC_SECRET


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BOT_APP_DIR = PROJECT_ROOT / "apps" / "bot"
if str(BOT_APP_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_APP_DIR))

try:
    from app.coach import build_ai_brief, format_natural_coach
except Exception:
    build_ai_brief = None
    format_natural_coach = None

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:2b")
MAX_JOBS = int(os.getenv("GARMIN_COACH_AI_MAX_JOBS", "3"))
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
PIPER_BIN = os.getenv("PIPER_BIN", str(Path(sys.executable).resolve().parent / "piper"))
PIPER_VOICE_MODEL = os.getenv("PIPER_VOICE_MODEL", "")
PIPER_SPEAKER = os.getenv("PIPER_SPEAKER", "")
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
VOICE_DIR = Path(os.getenv("GARMIN_COACH_VOICE_DIR", "~/Library/Application Support/Garmin Coach/voice")).expanduser()
ANSWER_MAX_CHARS = int(os.getenv("GARMIN_COACH_ANSWER_MAX_CHARS", "1100"))
VOICE_ANSWER_MAX_CHARS = int(os.getenv("GARMIN_COACH_VOICE_ANSWER_MAX_CHARS", "850"))


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


def telegram_api(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for voice jobs")
    response = httpx.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        data=payload or {},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")
    return data


def check_ollama() -> None:
    response = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    response.raise_for_status()


def download_telegram_audio(file_id: str, output_dir: Path) -> Path:
    file_data = telegram_api("getFile", {"file_id": file_id})
    file_path = (file_data.get("result") or {}).get("file_path")
    if not file_path:
        raise RuntimeError("Telegram did not return an audio file path")

    suffix = Path(str(file_path)).suffix or ".oga"
    output_path = output_dir / f"telegram_audio{suffix}"
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    response = httpx.get(url, timeout=60)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    return output_path


def download_telegram_document(job: dict[str, Any], output_dir: Path) -> Path:
    file_id = str(job.get("document_file_id") or "")
    if not file_id:
        raise RuntimeError("Missing Telegram document file_id")
    file_data = telegram_api("getFile", {"file_id": file_id})
    file_path = (file_data.get("result") or {}).get("file_path")
    if not file_path:
        raise RuntimeError("Telegram did not return a document file path")

    filename = str(job.get("document_name") or Path(str(file_path)).name or "lab-test")
    suffix = Path(filename).suffix or Path(str(file_path)).suffix
    if suffix.lower() not in {".pdf", ".docx"}:
        raise RuntimeError("Solo puedo procesar pruebas de esfuerzo en PDF o DOCX")
    output_path = output_dir / f"lab_test{suffix.lower()}"
    url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    response = httpx.get(url, timeout=90)
    response.raise_for_status()
    output_path.write_bytes(response.content)
    return output_path


def transcribe_audio(audio_path: Path) -> str:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed in the local sync venv") from exc

    model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    segments, _info = model.transcribe(str(audio_path), language="es", vad_filter=True)
    transcript = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
    return re.sub(r"\s+", " ", transcript).strip()


def enrich_context_for_question(question: str, context: dict[str, Any]) -> dict[str, Any]:
    if not question or build_ai_brief is None:
        return context
    enriched = dict(context)
    enriched["coach_brief"] = build_ai_brief(
        question,
        enriched.get("sync"),
        enriched.get("profile"),
        enriched.get("checkins"),
        enriched.get("history"),
    )
    return enriched


def synthesize_voice(text: str, output_dir: Path) -> Path | None:
    if not PIPER_VOICE_MODEL:
        return None
    model_path = Path(PIPER_VOICE_MODEL).expanduser()
    if not model_path.exists():
        raise RuntimeError(f"Piper voice model not found: {model_path}")
    piper_path = shutil.which(PIPER_BIN) or PIPER_BIN
    wav_path = output_dir / "coach_response.wav"
    command = [piper_path, "--model", str(model_path), "--output_file", str(wav_path)]
    if PIPER_SPEAKER:
        command.extend(["--speaker", PIPER_SPEAKER])
    subprocess.run(command, input=text, text=True, capture_output=True, check=True, timeout=90)

    ffmpeg_path = shutil.which(FFMPEG_BIN)
    if not ffmpeg_path:
        return wav_path
    ogg_path = output_dir / "coach_response.ogg"
    subprocess.run(
        [ffmpeg_path, "-y", "-i", str(wav_path), "-c:a", "libopus", "-b:a", "32k", str(ogg_path)],
        capture_output=True,
        check=True,
        timeout=90,
    )
    return ogg_path if ogg_path.exists() else wav_path


def send_telegram_voice(chat_id: str, audio_path: Path, caption: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required to send voice responses")
    method = "sendVoice" if audio_path.suffix == ".ogg" else "sendAudio"
    field = "voice" if method == "sendVoice" else "audio"
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    with audio_path.open("rb") as file:
        response = httpx.post(
            url,
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={field: (audio_path.name, file, "audio/ogg" if audio_path.suffix == ".ogg" else "audio/wav")},
            timeout=90,
        )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")


def call_ollama(question: str, context: dict[str, Any]) -> str:
    compact = compact_context(context)
    messages = [
        {
            "role": "system",
            "content": (
                "Eres Garmin Coach, un entrenador de running, ciclismo y fuerza. "
                "Tu respuesta final debe estar SIEMPRE en espanol de Espana. "
                "No uses ingles, no uses Markdown, no uses encabezados ###, no uses negritas y no uses emojis. "
                "No saludes y no hagas introducciones genericas. "
                "Usa principalmente las lecturas calculadas en coach_brief. "
                "Usa solo los datos del contexto; si falta un dato, dilo con naturalidad. "
                "No inventes metricas, actividades ni diagnosticos medicos. "
                "Usa unidades coherentes: distancia en km con 1 decimal, running en min/km, ciclismo en km/h y W. "
                "Nunca expreses ciclismo como min/km ni conviertas km a metros salvo distancias menores de 1 km. "
                "Si una metrica no esta clara, omitela. "
                "Empieza por la decision o lectura principal. "
                "Cuando la pregunta sea sobre que hacer manana, responde con una recomendacion concreta primero. "
                "Cuando pregunte por Malaga, evalua running/maraton aunque la ultima actividad sea bici. "
                "No muestres razonamiento interno. "
                "Responde en 4-7 lineas y menos de 90 palabras."
            ),
        },
        {
            "role": "user",
            "content": (
                "/no_think\n"
                "Pregunta del deportista:\n"
                f"{question}\n\n"
                "Lecturas calculadas por el backend:\n"
                f"{json.dumps(compact.get('coach_brief', {}), ensure_ascii=True)}\n\n"
                "Contexto Garmin adicional, solo para desempatar:\n"
                f"{json.dumps(compact.get('extra_context', {}), ensure_ascii=True)}\n\n"
                "Recuerda: respuesta final solo en espanol natural, sin Markdown, breve y accionable."
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
            "options": {"temperature": 0.1, "num_ctx": 4096, "num_predict": 160},
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    content = (data.get("message") or {}).get("content") or data.get("response") or ""
    answer = clean_answer(str(content))
    if is_bad_answer(answer):
        return polish_coach_answer(fallback_answer(question, compact))
    return polish_coach_answer(answer)


def deterministic_answer(question: str, context: dict[str, Any]) -> str | None:
    if format_natural_coach is None:
        return None
    answer = format_natural_coach(
        question,
        context.get("sync"),
        context.get("profile"),
        context.get("checkins"),
        context.get("history"),
    )
    return polish_coach_answer(answer) if answer else None


def polish_coach_answer(value: str, max_chars: int = ANSWER_MAX_CHARS) -> str:
    value = clean_answer(value)
    banned_starts = (
        "hola",
        "he analizado",
        "based on",
        "here is",
        "te ofrezco",
        "a continuacion",
    )
    lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip(" -\t")
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        normalized = _normalize(line)
        if any(normalized.startswith(prefix) for prefix in banned_starts):
            continue
        line = _fix_unit_language(line)
        lines.append(line)
        if len([item for item in lines if item]) >= 10:
            break
    polished = "\n".join(lines).strip()
    if not polished:
        polished = "No tengo contexto suficiente para afinar; lanza /sync y repite la pregunta."
    return trim_answer(polished, max_chars=max_chars)


def trim_answer(value: str, max_chars: int = ANSWER_MAX_CHARS) -> str:
    if len(value) <= max_chars:
        return value
    snippet = value[: max_chars - 1].rstrip()
    sentence_cut = max(snippet.rfind("."), snippet.rfind("\n"))
    if sentence_cut >= max_chars * 0.55:
        snippet = snippet[: sentence_cut + 1].rstrip()
    return snippet.rstrip(" ,;:") + "."


def _fix_unit_language(value: str) -> str:
    value = re.sub(r"\bHR promedio\b", "pulso medio", value, flags=re.IGNORECASE)
    value = re.sub(r"\bHR media\b", "pulso medio", value, flags=re.IGNORECASE)
    value = re.sub(r"\bpace\b", "ritmo", value, flags=re.IGNORECASE)
    if "cicl" in _normalize(value) or "bici" in _normalize(value):
        value = re.sub(r"\britmo\s+(?:medio\s+)?(?:de\s+)?\d{1,2}:\d{2}\s*/\s*km\b", "velocidad media no disponible", value, flags=re.IGNORECASE)
        value = re.sub(r"\b\d{1,2}:\d{2}\s*/\s*km\b", "velocidad media no disponible", value)
    return value


def clean_answer(value: str) -> str:
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.DOTALL | re.IGNORECASE)
    value = value.replace("###", "")
    value = value.replace("**", "")
    value = value.replace("* ", "- ")
    value = re.sub(r"[\U0001F300-\U0001FAFF]", "", value)
    value = value.strip()
    if len(value) > 3500:
        value = value[:3490].rstrip() + "..."
    return value or "No he podido generar una respuesta util con el contexto disponible."


def is_bad_answer(value: str) -> bool:
    lowered = value.lower()
    english_markers = (
        "based on the data",
        "cycling performance",
        "training effectiveness",
        "current session",
        "provided",
        "here is",
        "wellness profile",
    )
    if any(marker in lowered for marker in english_markers):
        return True
    spanish_markers = ("que", "con", "para", "hoy", "manana", "entreno", "si", "no", "ritmo", "carga")
    return sum(1 for marker in spanish_markers if marker in lowered) < 2


def fallback_answer(question: str, compact: dict[str, Any]) -> str:
    brief = compact.get("coach_brief") or {}
    sections = brief.get("sections") or []
    lines = ["Voy con lo importante:"]
    for section in sections[:3]:
        content = str(section.get("content") or "")
        for line in content.splitlines()[1:6]:
            line = line.strip()
            if line:
                lines.append(line)
        if len(lines) >= 12:
            break
    if len(lines) == 1:
        lines.append("No tengo contexto suficiente para afinar; lanza /sync y repite la pregunta.")
    if "malaga" in _normalize(question) or "maraton" in _normalize(question):
        lines.append("Para Malaga, la prioridad es no confundir bici fuerte con descanso: suma aerobica, pero tambien carga.")
    return "\n".join(lines[:14])


def compact_context(context: dict[str, Any]) -> dict[str, Any]:
    sync = context.get("sync") or {}
    payload = sync.get("payload") or {}
    summary = payload.get("summary") or {}
    wellness = payload.get("wellness") or {}
    physiology = payload.get("physiology") or {}
    activities = summary.get("activities") or []

    return {
        "coach_brief": context.get("coach_brief") or {},
        "extra_context": {
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
        },
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


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def process_job(job: dict[str, Any], context: dict[str, Any]) -> None:
    job_id = job["id"]
    transcript = None
    try:
        question = str(job.get("text") or "").strip()
        if job.get("document_file_id"):
            with tempfile.TemporaryDirectory(prefix="garmin-coach-lab-") as tmp:
                document_path = download_telegram_document(job, Path(tmp))
                result = parse_lab_test(document_path)
            result["source"] = {
                "name": job.get("document_name") or "prueba_esfuerzo",
                "mime_type": job.get("document_mime_type"),
                "telegram_file_id": job.get("document_file_id"),
                "telegram_unique_id": job.get("document_unique_id"),
                "caption": question,
            }
            saved = post_json("/lab-tests", result)
            answer = saved.get("message") or "Prueba de esfuerzo procesada. Revisa /ver_prueba."
            post_json(f"/ai/jobs/{job_id}/complete", {"status": "completed", "answer": answer})
            print(json.dumps({"ok": True, "job": job_id, "status": "completed", "type": "lab_test"}))
            return

        if job.get("audio_file_id"):
            with tempfile.TemporaryDirectory(prefix="garmin-coach-voice-") as tmp:
                audio_path = download_telegram_audio(str(job["audio_file_id"]), Path(tmp))
                transcript = transcribe_audio(audio_path)
            if not transcript:
                raise RuntimeError("No he podido transcribir la nota de voz")
            question = f"{question}\n{transcript}".strip()
            context = enrich_context_for_question(question, context)

        answer = deterministic_answer(question, context)
        if not answer:
            check_ollama()
            answer = call_ollama(question, context)
        payload: dict[str, Any] = {"status": "completed", "answer": answer}
        if transcript:
            payload["transcript"] = transcript

        if job.get("response_mode") == "voice" and job.get("chat_id"):
            try:
                VOICE_DIR.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix="garmin-coach-piper-", dir=str(VOICE_DIR)) as tmp:
                    answer = trim_answer(answer, VOICE_ANSWER_MAX_CHARS)
                    voice_path = synthesize_voice(answer, Path(tmp))
                    if voice_path:
                        send_telegram_voice(str(job["chat_id"]), voice_path, answer)
                        payload["answer"] = answer
                        payload["notify_telegram"] = False
                        payload["response_mode"] = "voice"
            except Exception as voice_exc:
                payload["answer"] = f"{answer}\n\n(Audio no disponible en el Mac: {str(voice_exc)[:180]})"
                payload["response_mode"] = "text"
        post_json(f"/ai/jobs/{job_id}/complete", payload)
        print(json.dumps({"ok": True, "job": job_id, "status": "completed"}))
    except Exception as exc:
        error_payload: dict[str, Any] = {"status": "failed", "error": str(exc)[:500]}
        if transcript:
            error_payload["transcript"] = transcript
        post_json(f"/ai/jobs/{job_id}/complete", error_payload)
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
