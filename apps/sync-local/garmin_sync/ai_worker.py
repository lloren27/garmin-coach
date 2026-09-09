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
from .wattwise_context import fetch_wattwise_context


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
PIPER_LENGTH_SCALE = os.getenv("PIPER_LENGTH_SCALE", "1.12")
PIPER_NOISE_SCALE = os.getenv("PIPER_NOISE_SCALE", "0.45")
PIPER_NOISE_W_SCALE = os.getenv("PIPER_NOISE_W_SCALE", "0.55")
PIPER_SENTENCE_SILENCE = os.getenv("PIPER_SENTENCE_SILENCE", "0.25")
PIPER_VOLUME = os.getenv("PIPER_VOLUME", "1.0")
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
        enriched.get("wattwise"),
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
    _append_piper_option(command, "--length-scale", PIPER_LENGTH_SCALE)
    _append_piper_option(command, "--noise-scale", PIPER_NOISE_SCALE)
    _append_piper_option(command, "--noise-w-scale", PIPER_NOISE_W_SCALE)
    _append_piper_option(command, "--sentence-silence", PIPER_SENTENCE_SILENCE)
    _append_piper_option(command, "--volume", PIPER_VOLUME)
    subprocess.run(command, input=prepare_text_for_tts(text), text=True, capture_output=True, check=True, timeout=90)

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


def prepare_text_for_tts(text: str) -> str:
    value = clean_answer(text)
    value = re.sub(r"\b(\d{1,2}):(\d{2})\s*/\s*(?:km|kilometros?)\b", _pace_to_tts, value, flags=re.IGNORECASE)
    value = re.sub(r"\b(\d{1,2}):(\d{2})\b", _time_to_tts, value)
    value = re.sub(r"\b(\d+(?:[.,]\d+)?)\s*h\s+(\d{1,2})\s*min\b", _duration_to_tts, value, flags=re.IGNORECASE)
    value = re.sub(r"\b(\d+)[.,](\d+)\s*h\b", _decimal_hours_to_tts, value, flags=re.IGNORECASE)
    value = re.sub(r"\b(\d+(?:[.,]\d+)?)\s*-\s*(\d+(?:[.,]\d+)?)\s*(min|km|h|W|ppm|bpm)\b", _range_unit_to_tts, value, flags=re.IGNORECASE)
    unit_patterns = (
        (r"\b(\d+(?:[.,]\d+)?)\s*km/h\b", "kilometros por hora"),
        (r"\b(\d+(?:[.,]\d+)?)\s*W/kg\b", "vatios por kilo"),
        (r"\b(\d+(?:[.,]\d+)?)\s*(?:ppm|bpm)\b", "pulsaciones por minuto"),
        (r"\b(\d+(?:[.,]\d+)?)\s*W\b", "vatios"),
        (r"\b(\d+(?:[.,]\d+)?)\s*kcal\b", "kilocalorias"),
        (r"\b(\d+(?:[.,]\d+)?)\s*km\b", "kilometros"),
        (r"\b(\d+(?:[.,]\d+)?)\s*min\b", "minutos"),
        (r"\b(\d+(?:[.,]\d+)?)\s*h\b", "horas"),
        (r"\b(\d+(?:[.,]\d+)?)\s*kg\b", "kilos"),
        (r"\b(\d+(?:[.,]\d+)?)\s*cm\b", "centimetros"),
        (r"\b(\d+(?:[.,]\d+)?)\s*%\b", "por ciento"),
    )
    for pattern, unit in unit_patterns:
        value = re.sub(pattern, lambda match: f"{_number_text(match.group(1))} {unit}", value, flags=re.IGNORECASE)
    replacements = (
        (r"\bBody battery\b", "energia corporal Garmin"),
        (r"\bTraining readiness\b", "preparacion Garmin"),
        (r"\bTraining effect\b", "efecto de entrenamiento"),
        (r"\bHRV\b", "variabilidad de pulso"),
        (r"\bVO2\s*max\b", "uve o dos maximo"),
        (r"\bFCmax\b", "frecuencia cardiaca maxima"),
        (r"\bFC reposo\b", "frecuencia cardiaca en reposo"),
        (r"\bFC umbral\b", "frecuencia cardiaca de umbral"),
        (r"\bFC\b", "frecuencia cardiaca"),
        (r"\bFTP\b", "efe te pe"),
        (r"\bVT1\b", "umbral ventilatorio uno"),
        (r"\bVT2\b", "umbral ventilatorio dos"),
        (r"\bZ\s*1\b", "zona uno"),
        (r"\bZ\s*2\b", "zona dos"),
        (r"\bZ\s*3\b", "zona tres"),
        (r"\bZ\s*4\b", "zona cuatro"),
        (r"\bZ\s*5\b", "zona cinco"),
        (r"\bppm\b", "pulsaciones por minuto"),
        (r"\bbpm\b", "pulsaciones por minuto"),
        (r"\bW/kg\b", "vatios por kilo"),
        (r"\bW\b", "vatios"),
        (r"\bkm/h\b", "kilometros por hora"),
        (r"\bkm\b", "kilometros"),
        (r"\bkcal\b", "kilocalorias"),
        (r"\bmin\b", "minutos"),
        (r"\bh\b", "horas"),
        (r"\bREM\b", "fase REM"),
        (r"\bBMR\b", "metabolismo basal"),
        (r"\bIMC\b", "indice de masa corporal"),
        (r"\bSpO2\b", "saturacion de oxigeno"),
        (r"\b10K\b", "diez kilometros"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = re.sub(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)", lambda match: f"{_number_text(match.group(1))} sobre {_number_text(match.group(2))}", value)
    value = re.sub(r"\b\d+(?:[.,]\d+)?\b", lambda match: _number_text(match.group(0)), value)
    value = value.replace("/", " por ")
    value = value.replace(" - ", ". ")
    value = value.replace(":", ". ")
    value = re.sub(r"\(([^)]*)\)", r", \1,", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _append_piper_option(command: list[str], option: str, value: str) -> None:
    if value.strip():
        command.extend([option, value.strip()])


def _pace_to_tts(match: re.Match[str]) -> str:
    minutes = int(match.group(1))
    seconds = int(match.group(2))
    return f"{_number_to_spanish(minutes)} {_number_to_spanish(seconds)} por kilometro"


def _time_to_tts(match: re.Match[str]) -> str:
    hours = int(match.group(1))
    minutes = int(match.group(2))
    return f"{_number_to_spanish(hours)} horas {_number_to_spanish(minutes)}"


def _duration_to_tts(match: re.Match[str]) -> str:
    hours = _number_text(match.group(1))
    minutes = _number_text(match.group(2))
    return f"{hours} horas y {minutes} minutos"


def _decimal_hours_to_tts(match: re.Match[str]) -> str:
    hours = int(match.group(1))
    decimal = match.group(2)
    minutes = round(float(f"0.{decimal}") * 60)
    if minutes == 0:
        return f"{_hours_text(hours)}"
    return f"{_hours_text(hours)} y {_minutes_text(minutes)}"


def _range_unit_to_tts(match: re.Match[str]) -> str:
    start = _number_text(match.group(1))
    end = _number_text(match.group(2))
    unit = match.group(3).lower()
    unit_labels = {
        "min": "minutos",
        "km": "kilometros",
        "h": "horas",
        "w": "vatios",
        "ppm": "pulsaciones por minuto",
        "bpm": "pulsaciones por minuto",
    }
    return f"{start} a {end} {unit_labels.get(unit, unit)}"


def _hours_text(value: int) -> str:
    if value == 1:
        return "una hora"
    return f"{_number_to_spanish(value)} horas"


def _minutes_text(value: int) -> str:
    if value == 1:
        return "un minuto"
    return f"{_number_to_spanish(value)} minutos"


def _number_text(raw: str) -> str:
    value = raw.strip().replace(",", ".")
    try:
        number = float(value)
    except ValueError:
        return raw
    if number.is_integer():
        return _number_to_spanish(int(number))
    integer, decimal = value.split(".", 1)
    decimal = decimal.rstrip("0") or "0"
    decimal_text = _number_to_spanish(int(decimal)) if len(decimal) <= 2 else " ".join(_number_to_spanish(int(digit)) for digit in decimal)
    return f"{_number_to_spanish(int(integer))} coma {decimal_text}"


def _number_to_spanish(value: int) -> str:
    if value < 0:
        return f"menos {_number_to_spanish(abs(value))}"
    units = {
        0: "cero",
        1: "uno",
        2: "dos",
        3: "tres",
        4: "cuatro",
        5: "cinco",
        6: "seis",
        7: "siete",
        8: "ocho",
        9: "nueve",
        10: "diez",
        11: "once",
        12: "doce",
        13: "trece",
        14: "catorce",
        15: "quince",
        16: "dieciseis",
        17: "diecisiete",
        18: "dieciocho",
        19: "diecinueve",
        20: "veinte",
        21: "veintiuno",
        22: "veintidos",
        23: "veintitres",
        24: "veinticuatro",
        25: "veinticinco",
        26: "veintiseis",
        27: "veintisiete",
        28: "veintiocho",
        29: "veintinueve",
    }
    tens_words = {
        30: "treinta",
        40: "cuarenta",
        50: "cincuenta",
        60: "sesenta",
        70: "setenta",
        80: "ochenta",
        90: "noventa",
    }
    hundreds_words = {
        100: "cien",
        200: "doscientos",
        300: "trescientos",
        400: "cuatrocientos",
        500: "quinientos",
        600: "seiscientos",
        700: "setecientos",
        800: "ochocientos",
        900: "novecientos",
    }
    if value in units:
        return units[value]
    if value < 100:
        tens = value - value % 10
        units = value % 10
        if units == 0:
            return tens_words[tens]
        return f"{tens_words[tens]} y {_number_to_spanish(units)}"
    if value < 200:
        return f"ciento {_number_to_spanish(value - 100)}"
    if value < 1000:
        hundreds = value - value % 100
        remainder = value % 100
        if remainder == 0:
            return hundreds_words[hundreds]
        return f"{hundreds_words[hundreds]} {_number_to_spanish(remainder)}"
    if value < 2000:
        remainder = value - 1000
        if remainder == 0:
            return "mil"
        return f"mil {_number_to_spanish(remainder)}"
    if value < 1_000_000:
        thousands = value // 1000
        remainder = value % 1000
        prefix = f"{_number_to_spanish(thousands)} mil"
        if remainder == 0:
            return prefix
        return f"{prefix} {_number_to_spanish(remainder)}"
    return str(value)


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
                "Para feedback agrega todas las actividades de la misma fecha y cruza la carga total con la recuperacion Garmin. "
                "Sueno, energia y recuperacion salen de Garmin; de los check-ins usa solo dolor o molestias. "
                "Si hay contexto Wattwise, usalo sobre todo para ciclismo, potencia, IF, TSS, VI y carga; "
                "para running prioriza Garmin Coach si Wattwise no trae distancia, ritmo o FC. "
                "Para carga de running usa running_load, distingue Garmin de TRIMP estimado y no presentes ACWR como riesgo medico. "
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
        context.get("wattwise"),
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
    wattwise = fetch_wattwise_context()

    extra_context = {
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
            "running_load": summary.get("running_load"),
            "next_workout": summary.get("next_workout"),
        },
        "recent_activities": activities[-8:],
        "wellness": wellness,
        "physiology": physiology,
        "checkins": _compact_injury_checkins(context.get("checkins")),
        "history": compact_history(context.get("history") or []),
    }
    if wattwise:
        extra_context["wattwise"] = wattwise

    return {
        "coach_brief": context.get("coach_brief") or {},
        "extra_context": extra_context,
    }


def _compact_injury_checkins(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compact = []
    for document in value:
        if not isinstance(document, dict):
            continue
        checkin = document.get("checkin", document)
        if not isinstance(checkin, dict):
            continue
        soreness = checkin.get("soreness")
        pain = checkin.get("pain")
        if not pain and (not soreness or str(soreness).lower() == "no"):
            continue
        compact.append(
            {
                "created_at": document.get("created_at"),
                "pain": pain,
                "soreness": soreness,
                "note": checkin.get("note"),
            }
        )
    return compact[-3:]


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
