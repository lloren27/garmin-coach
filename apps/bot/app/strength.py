from __future__ import annotations

import re
import unicodedata
import uuid
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any


CircuitExercise = dict[str, Any]

LOWER_BODY_GROUPS = {"cuadriceps/gluteo", "isquios/gluteo", "gluteo", "gemelo/soleo"}
POSTERIOR_GROUPS = {"isquios/gluteo", "gluteo"}
GROUP_LOAD_WEIGHT = {
    "cuadriceps/gluteo": 1.4,
    "isquios/gluteo": 1.35,
    "gluteo": 1.25,
    "gemelo/soleo": 1.1,
    "core": 0.65,
    "espalda": 0.8,
    "empuje": 0.75,
    "personalizado": 1.0,
}

CIRCUITS: dict[str, list[CircuitExercise]] = {
    "A": [
        {
            "id": "sentadilla",
            "name": "sentadilla",
            "aliases": ("sentadilla", "squat"),
            "group": "cuadriceps/gluteo",
        },
        {
            "id": "peso_muerto_rumano",
            "name": "peso muerto rumano",
            "aliases": ("peso muerto rumano", "rumano", "rdl"),
            "group": "isquios/gluteo",
        },
        {
            "id": "remo",
            "name": "remo",
            "aliases": ("remo",),
            "group": "espalda",
        },
        {
            "id": "press_flexiones",
            "name": "press o flexiones",
            "aliases": ("press banca", "press", "flexiones", "flexion"),
            "group": "empuje",
        },
        {
            "id": "gemelo",
            "name": "gemelo",
            "aliases": ("gemelo", "gemelos", "calf raise"),
            "group": "gemelo/soleo",
        },
        {
            "id": "pallof_press",
            "name": "Pallof press",
            "aliases": ("pallof", "pallof press"),
            "group": "core",
        },
    ],
    "B": [
        {
            "id": "zancada_split_squat",
            "name": "zancada o split squat",
            "aliases": ("zancada", "zancadas", "split squat", "bulgara", "bulgaras"),
            "group": "cuadriceps/gluteo",
        },
        {
            "id": "hip_thrust",
            "name": "hip thrust",
            "aliases": ("hip thrust", "puente gluteo", "puente gluteos"),
            "group": "gluteo",
        },
        {
            "id": "jalon",
            "name": "jalon",
            "aliases": ("jalon", "jalon al pecho", "dominadas", "dominada"),
            "group": "espalda",
        },
        {
            "id": "press_vertical",
            "name": "press vertical",
            "aliases": ("press vertical", "press militar", "hombro", "hombros"),
            "group": "empuje",
        },
        {
            "id": "soleo",
            "name": "soleo",
            "aliases": ("soleo", "soleos"),
            "group": "gemelo/soleo",
        },
        {
            "id": "plancha_lateral",
            "name": "plancha lateral",
            "aliases": ("plancha lateral", "side plank"),
            "group": "core",
        },
    ],
}


def empty_strength_state() -> dict[str, Any]:
    return {"active_sessions": {}, "sessions": []}


def normalize_strength_state(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return empty_strength_state()
    normalized = {
        "active_sessions": state.get("active_sessions") if isinstance(state.get("active_sessions"), dict) else {},
        "sessions": state.get("sessions") if isinstance(state.get("sessions"), list) else [],
    }
    return normalized


def handle_strength_command(
    args: str,
    sync: dict[str, Any] | None,
    state: dict[str, Any] | None,
    owner_id: str,
) -> tuple[str, dict[str, Any], bool]:
    state = normalize_strength_state(deepcopy(state))
    args = args.strip()
    normalized_args = _normalize(args)

    if not args:
        return format_strength_home(sync, state, owner_id), state, False
    if normalized_args in {"help", "ayuda", "?"}:
        return format_strength_help(), state, False
    if normalized_args in {"actual", "estado", "resumen"}:
        return format_active_session(state, owner_id), state, False
    if normalized_args in {"historial", "ultimas", "ultimos"}:
        return format_strength_history(state, owner_id), state, False
    if normalized_args in {"fin", "finalizar", "terminar", "cerrar"}:
        return finish_strength_session(state, owner_id)

    circuit = _requested_circuit(normalized_args)
    if circuit:
        return start_strength_session(state, owner_id, circuit)

    return add_strength_entry(state, owner_id, args)


def format_strength_home(sync: dict[str, Any] | None, state: dict[str, Any], owner_id: str) -> str:
    current_sessions = 0
    weekly_target = "2 sesiones"
    if sync:
        summary = sync.get("payload", {}).get("summary", {})
        current_sessions = summary.get("week", {}).get("by_sport", {}).get("strength", {}).get("sessions", 0)
        mode = _weekly_strength_mode(summary, sync.get("payload", {}).get("wellness", {}))
        weekly_target = "1 sesion de mantenimiento" if mode != "normal" else "2 sesiones"

    active = state.get("active_sessions", {}).get(owner_id)
    active_line = ""
    if active:
        active_line = f"\nSesion activa: circuito {active.get('circuit')}, {len(active.get('entries') or [])} ejercicios registrados."

    return (
        "Fuerza full body\n"
        f"Objetivo actual: {weekly_target}. Esta semana Garmin detecta {current_sessions}.\n"
        "Elige circuito: /fuerza A o /fuerza B."
        f"{active_line}\n"
        "Registrar: /fuerza add sentadilla 60kg 8/8 rir2\n"
        "Ver sesion: /fuerza actual. Cerrar: /fuerza fin.\n"
        "A: sentadilla, peso muerto rumano, remo, press/flexiones, gemelo y Pallof press.\n"
        "B: zancada/split squat, hip thrust, jalon, press vertical, soleo y plancha lateral."
    )


def format_strength_help() -> str:
    return (
        "Registro de fuerza\n"
        "/fuerza A - empieza circuito A\n"
        "/fuerza B - empieza circuito B\n"
        "/fuerza add sentadilla 60kg 8/8 rir2 - guarda peso, reps y repeticiones en reserva\n"
        "/fuerza actual - muestra lo registrado\n"
        "/fuerza fin - cierra la sesion y resume el volumen\n"
        "/fuerza historial - ultimas sesiones cerradas"
    )


def start_strength_session(state: dict[str, Any], owner_id: str, circuit: str) -> tuple[str, dict[str, Any], bool]:
    active_sessions = state.setdefault("active_sessions", {})
    if active_sessions.get(owner_id):
        active = active_sessions[owner_id]
        return (
            f"Ya hay una sesion de fuerza activa: circuito {active.get('circuit')}. "
            "Usa /fuerza actual para verla o /fuerza fin para cerrarla.",
            state,
            False,
        )

    now = datetime.now(timezone.utc).isoformat()
    active_sessions[owner_id] = {
        "id": str(uuid.uuid4()),
        "owner_id": owner_id,
        "circuit": circuit,
        "status": "active",
        "started_at": now,
        "entries": [],
    }
    exercises = ", ".join(item["name"] for item in CIRCUITS[circuit])
    return (
        f"Sesion de fuerza iniciada: circuito {circuit}.\n"
        f"Ejercicios: {exercises}.\n"
        "Cuando termines una serie o ejercicio, manda algo como:\n"
        "/fuerza add sentadilla 60kg 8/8 rir2",
        state,
        True,
    )


def add_strength_entry(state: dict[str, Any], owner_id: str, text: str) -> tuple[str, dict[str, Any], bool]:
    active = state.get("active_sessions", {}).get(owner_id)
    if not active:
        return (
            "Primero elige circuito con /fuerza A o /fuerza B. "
            "Luego registra ejercicios con /fuerza add sentadilla 60kg 8/8 rir2.",
            state,
            False,
        )

    entry = parse_strength_entry(text, str(active.get("circuit") or "A"))
    if not entry:
        return (
            "No he podido leer ese ejercicio. Prueba con: /fuerza add sentadilla 60kg 8/8 rir2",
            state,
            False,
        )

    active.setdefault("entries", []).append(entry)
    active["updated_at"] = datetime.now(timezone.utc).isoformat()
    return f"Guardado: {_entry_line(entry)}\nSiguiente: registra otro ejercicio o usa /fuerza fin.", state, True


def finish_strength_session(state: dict[str, Any], owner_id: str) -> tuple[str, dict[str, Any], bool]:
    active = state.get("active_sessions", {}).pop(owner_id, None)
    if not active:
        return "No hay una sesion de fuerza activa. Empieza con /fuerza A o /fuerza B.", state, False

    active["status"] = "completed"
    active["completed_at"] = datetime.now(timezone.utc).isoformat()
    summary = summarize_strength_session(active)
    active["summary"] = summary
    sessions = state.setdefault("sessions", [])
    sessions.append(active)
    state["sessions"] = sessions[-50:]
    return format_completed_session(active), state, True


def parse_strength_entry(text: str, circuit: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"^\s*(add|anadir|guardar|registrar)\s+", "", text.strip(), flags=re.IGNORECASE)
    if not cleaned:
        return None

    normalized = _normalize(cleaned)
    exercise = _match_exercise(normalized, circuit)
    exercise_name = exercise["name"] if exercise else _infer_exercise_name(cleaned)
    if not exercise_name:
        return None

    weight = _extract_weight_kg(normalized)
    reps = _extract_reps(normalized)
    rir = _extract_metric(normalized, "rir")
    rpe = _extract_metric(normalized, "rpe")
    if not reps and weight is None and rir is None and rpe is None:
        return None

    reps = reps or []
    weight_for_volume = weight or 0
    volume = round(weight_for_volume * sum(reps), 1)
    return {
        "exercise_id": exercise.get("id") if exercise else None,
        "exercise_name": exercise_name,
        "group": exercise.get("group") if exercise else "personalizado",
        "weight_kg": weight,
        "reps": reps,
        "sets": len(reps) if reps else None,
        "rir": rir,
        "rpe": rpe,
        "volume_kg": volume,
        "raw": text.strip()[:240],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def summarize_strength_session(session: dict[str, Any]) -> dict[str, Any]:
    entries = session.get("entries") or []
    total_sets = sum(int(entry.get("sets") or 0) for entry in entries)
    total_reps = sum(sum(int(rep) for rep in (entry.get("reps") or [])) for entry in entries)
    total_volume = round(sum(float(entry.get("volume_kg") or 0) for entry in entries), 1)
    groups: dict[str, int] = {}
    for entry in entries:
        group = str(entry.get("group") or "personalizado")
        groups[group] = groups.get(group, 0) + int(entry.get("sets") or 0)
    return {
        "exercises": len(entries),
        "sets": total_sets,
        "reps": total_reps,
        "volume_kg": total_volume,
        "load_score": round(sum(_entry_load_score(entry) for entry in entries), 1),
        "sets_by_group": groups,
    }


def summarize_strength_load(
    state: dict[str, Any] | None,
    owner_id: str,
    reference: date | None = None,
) -> dict[str, Any]:
    state = normalize_strength_state(state)
    reference = reference or date.today()
    sessions = [
        _session_with_summary(session)
        for session in state.get("sessions", [])
        if session.get("owner_id") == owner_id and _session_date(session) is not None
    ]
    sessions_7d = [
        session
        for session in sessions
        if reference - timedelta(days=6) <= (_session_date(session) or reference) <= reference
    ]
    sessions_28d = [
        session
        for session in sessions
        if reference - timedelta(days=27) <= (_session_date(session) or reference) <= reference
    ]
    today_sessions = [session for session in sessions if _session_date(session) == reference]
    return _strength_load_summary(sessions_7d, sessions_28d, today_sessions, reference)


def strength_context_for_date(
    state: dict[str, Any] | None,
    owner_id: str,
    target_date: str | date,
) -> dict[str, Any]:
    state = normalize_strength_state(state)
    parsed = target_date if isinstance(target_date, date) else _parse_date(str(target_date))
    if not parsed:
        return _empty_strength_context()
    sessions = [
        _session_with_summary(session)
        for session in state.get("sessions", [])
        if session.get("owner_id") == owner_id and _session_date(session) == parsed
    ]
    return {
        "date": parsed.isoformat(),
        "sessions": sessions,
        "day": _aggregate_strength_sessions(sessions),
    }


def strength_load_reading(summary: dict[str, Any] | None) -> str:
    if not summary or summary.get("sessions_7d", 0) == 0:
        return "sin fuerza registrada manualmente en 7 dias."
    level = summary.get("level", "baja")
    lower_sets = summary.get("lower_sets_7d", 0)
    volume = _format_compact_number(summary.get("volume_kg_7d", 0))
    score = _format_compact_number(summary.get("load_score_7d", 0))
    if level == "alta":
        reading = "carga muscular alta; protege calidad de carrera y tirada larga."
    elif level == "moderada":
        reading = "carga muscular moderada; deja margen antes de series o cuestas."
    else:
        reading = "carga muscular baja/controlada."
    return f"{level}: {lower_sets} series de pierna, {volume} kg, score {score}; {reading}"


def strength_recovery_risk(summary: dict[str, Any] | None) -> int:
    if not summary:
        return 0
    score = float(summary.get("load_score_7d") or 0)
    today_score = float(summary.get("today_load_score") or 0)
    lower_sets = int(summary.get("lower_sets_7d") or 0)
    hard_lower_sets = int(summary.get("hard_lower_sets_7d") or 0)
    risk = 0
    if score >= 32 or lower_sets >= 18:
        risk += 2
    elif score >= 18 or lower_sets >= 10:
        risk += 1
    if hard_lower_sets >= 6 or today_score >= 18:
        risk += 1
    return min(risk, 3)


def format_active_session(state: dict[str, Any], owner_id: str) -> str:
    active = state.get("active_sessions", {}).get(owner_id)
    if not active:
        return "No hay una sesion de fuerza activa. Empieza con /fuerza A o /fuerza B."
    entries = active.get("entries") or []
    if not entries:
        return (
            f"Sesion activa: circuito {active.get('circuit')}.\n"
            "Aun no hay ejercicios registrados. Ejemplo: /fuerza add sentadilla 60kg 8/8 rir2"
        )
    lines = [f"Sesion activa: circuito {active.get('circuit')} ({len(entries)} ejercicios)"]
    lines.extend(_entry_line(entry) for entry in entries)
    lines.append("Cierra con /fuerza fin.")
    return "\n".join(lines)


def format_completed_session(session: dict[str, Any]) -> str:
    summary = session.get("summary") or summarize_strength_session(session)
    lines = [
        f"Sesion de fuerza cerrada: circuito {session.get('circuit')}",
        (
            f"Resumen: {summary.get('exercises', 0)} ejercicios, {summary.get('sets', 0)} series, "
            f"{summary.get('reps', 0)} reps, {_format_compact_number(summary.get('volume_kg', 0))} kg de volumen."
        ),
    ]
    groups = summary.get("sets_by_group") or {}
    if groups:
        groups_text = ", ".join(f"{group} {sets} series" for group, sets in sorted(groups.items()))
        lines.append(f"Por grupo: {groups_text}.")
    lines.append("Esto ya queda guardado para usarlo en la progresion de fuerza.")
    return "\n".join(lines)


def format_strength_history(state: dict[str, Any], owner_id: str) -> str:
    sessions = [item for item in state.get("sessions", []) if item.get("owner_id") == owner_id]
    if not sessions:
        return "Todavia no hay sesiones de fuerza cerradas."
    lines = ["Ultimas sesiones de fuerza"]
    for session in sessions[-5:]:
        summary = session.get("summary") or summarize_strength_session(session)
        completed = str(session.get("completed_at") or session.get("started_at") or "")[:10]
        lines.append(
            f"{completed}: circuito {session.get('circuit')}, {summary.get('sets', 0)} series, "
            f"{_format_compact_number(summary.get('volume_kg', 0))} kg"
        )
    return "\n".join(lines)


def _entry_line(entry: dict[str, Any]) -> str:
    reps = "/".join(str(rep) for rep in (entry.get("reps") or [])) or "sin reps"
    weight = f"{_format_compact_number(entry.get('weight_kg'))} kg" if entry.get("weight_kg") is not None else "sin peso"
    effort = ""
    if entry.get("rir") is not None:
        effort = f", RIR {entry.get('rir')}"
    elif entry.get("rpe") is not None:
        effort = f", RPE {entry.get('rpe')}"
    volume = f", volumen {_format_compact_number(entry.get('volume_kg'))} kg" if entry.get("volume_kg") else ""
    return f"- {entry.get('exercise_name')}: {weight}, reps {reps}{effort}{volume}"


def _session_with_summary(session: dict[str, Any]) -> dict[str, Any]:
    item = dict(session)
    item["summary"] = item.get("summary") or summarize_strength_session(item)
    return item


def _strength_load_summary(
    sessions_7d: list[dict[str, Any]],
    sessions_28d: list[dict[str, Any]],
    today_sessions: list[dict[str, Any]],
    reference: date,
) -> dict[str, Any]:
    aggregate_7d = _aggregate_strength_sessions(sessions_7d)
    aggregate_28d = _aggregate_strength_sessions(sessions_28d)
    today = _aggregate_strength_sessions(today_sessions)
    score = float(aggregate_7d.get("load_score") or 0)
    lower_sets = int(aggregate_7d.get("lower_sets") or 0)
    hard_lower_sets = int(aggregate_7d.get("hard_lower_sets") or 0)
    if score >= 32 or lower_sets >= 18 or hard_lower_sets >= 8:
        level = "alta"
    elif score >= 16 or lower_sets >= 10 or hard_lower_sets >= 4:
        level = "moderada"
    else:
        level = "baja"

    return {
        "reference_date": reference.isoformat(),
        "sessions_7d": len(sessions_7d),
        "sessions_28d": len(sessions_28d),
        "sets_7d": aggregate_7d.get("sets", 0),
        "reps_7d": aggregate_7d.get("reps", 0),
        "volume_kg_7d": aggregate_7d.get("volume_kg", 0),
        "load_score_7d": aggregate_7d.get("load_score", 0),
        "sets_by_group_7d": aggregate_7d.get("sets_by_group", {}),
        "lower_sets_7d": lower_sets,
        "posterior_sets_7d": aggregate_7d.get("posterior_sets", 0),
        "hard_lower_sets_7d": hard_lower_sets,
        "volume_kg_28d": aggregate_28d.get("volume_kg", 0),
        "load_score_28d": aggregate_28d.get("load_score", 0),
        "today_sessions": len(today_sessions),
        "today_sets": today.get("sets", 0),
        "today_lower_sets": today.get("lower_sets", 0),
        "today_load_score": today.get("load_score", 0),
        "level": level,
    }


def _aggregate_strength_sessions(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "sets": 0,
        "reps": 0,
        "volume_kg": 0.0,
        "load_score": 0.0,
        "sets_by_group": {},
        "lower_sets": 0,
        "posterior_sets": 0,
        "hard_lower_sets": 0,
    }
    for session in sessions:
        summary = session.get("summary") or summarize_strength_session(session)
        totals["sets"] += int(summary.get("sets") or 0)
        totals["reps"] += int(summary.get("reps") or 0)
        totals["volume_kg"] += float(summary.get("volume_kg") or 0)
        totals["load_score"] += float(summary.get("load_score") or 0)
        for group, sets in (summary.get("sets_by_group") or {}).items():
            totals["sets_by_group"][group] = totals["sets_by_group"].get(group, 0) + int(sets or 0)
        for entry in session.get("entries") or []:
            group = str(entry.get("group") or "personalizado")
            sets = int(entry.get("sets") or 0)
            if group in LOWER_BODY_GROUPS:
                totals["lower_sets"] += sets
                if _is_hard_entry(entry):
                    totals["hard_lower_sets"] += sets
            if group in POSTERIOR_GROUPS:
                totals["posterior_sets"] += sets
    totals["volume_kg"] = round(float(totals["volume_kg"]), 1)
    totals["load_score"] = round(float(totals["load_score"]), 1)
    return totals


def _entry_load_score(entry: dict[str, Any]) -> float:
    sets = int(entry.get("sets") or 0)
    if sets <= 0:
        return 0
    group = str(entry.get("group") or "personalizado")
    group_weight = GROUP_LOAD_WEIGHT.get(group, GROUP_LOAD_WEIGHT["personalizado"])
    effort_weight = _effort_weight(entry)
    volume_bonus = min(float(entry.get("volume_kg") or 0) / 1200, 2.5)
    return sets * group_weight * effort_weight + volume_bonus


def _effort_weight(entry: dict[str, Any]) -> float:
    rir = entry.get("rir")
    rpe = entry.get("rpe")
    if rir is not None:
        rir_value = float(rir)
        if rir_value <= 1:
            return 1.35
        if rir_value <= 2:
            return 1.18
        if rir_value <= 3:
            return 1.05
        return 0.9
    if rpe is not None:
        rpe_value = float(rpe)
        if rpe_value >= 9:
            return 1.3
        if rpe_value >= 8:
            return 1.15
        if rpe_value <= 6:
            return 0.9
    return 1.0


def _is_hard_entry(entry: dict[str, Any]) -> bool:
    rir = entry.get("rir")
    rpe = entry.get("rpe")
    if rir is not None:
        return float(rir) <= 2
    if rpe is not None:
        return float(rpe) >= 8
    return False


def _session_date(session: dict[str, Any]) -> date | None:
    return _parse_date(str(session.get("completed_at") or session.get("started_at") or ""))


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _empty_strength_context() -> dict[str, Any]:
    return {"date": None, "sessions": [], "day": _aggregate_strength_sessions([])}


def _format_compact_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(number)) if number.is_integer() else str(round(number, 1))


def _requested_circuit(normalized_args: str) -> str | None:
    if normalized_args in {"a", "b"}:
        return normalized_args.upper()
    match = re.search(r"\b(?:circuito|sesion|empezar|iniciar)\s+([ab])\b", normalized_args)
    return match.group(1).upper() if match else None


def _match_exercise(normalized_text: str, circuit: str) -> CircuitExercise | None:
    candidates = CIRCUITS.get(circuit, []) + [item for key, items in CIRCUITS.items() if key != circuit for item in items]
    best: CircuitExercise | None = None
    best_len = 0
    for exercise in candidates:
        for alias in exercise["aliases"]:
            normalized_alias = _normalize(alias)
            if re.search(rf"\b{re.escape(normalized_alias)}\b", normalized_text) and len(normalized_alias) > best_len:
                best = exercise
                best_len = len(normalized_alias)
    return best


def _infer_exercise_name(text: str) -> str:
    without_metrics = re.sub(r"\b\d+(?:[,.]\d+)?\s*(?:kg|kilos?|reps?|repeticiones|rir|rpe|x|/)\b", " ", text, flags=re.IGNORECASE)
    without_metrics = re.sub(r"\b(?:add|anadir|guardar|registrar|kg|kilos?|rir\d+|rpe\d+)\b", " ", without_metrics, flags=re.IGNORECASE)
    without_metrics = re.sub(r"\d+(?:[,.]\d+)?", " ", without_metrics)
    return re.sub(r"\s+", " ", without_metrics).strip()[:60]


def _extract_weight_kg(normalized_text: str) -> float | None:
    match = re.search(r"\b(\d+(?:[,.]\d+)?)\s*(?:kg|kilo|kilos)\b", normalized_text)
    if not match:
        return None
    return _number(match.group(1))


def _extract_reps(normalized_text: str) -> list[int]:
    match = re.search(r"\b(\d{1,2})\s*x\s*(\d{1,2})\b", normalized_text)
    if match:
        sets = int(match.group(1))
        reps = int(match.group(2))
        return [reps] * min(sets, 10)

    slash = re.search(r"\b(\d{1,2}(?:\s*/\s*\d{1,2})+)\b", normalized_text)
    if slash:
        return [int(item) for item in re.split(r"\s*/\s*", slash.group(1)) if item]

    text = re.sub(r"\b\d+(?:[,.]\d+)?\s*(?:kg|kilo|kilos)\b", " ", normalized_text)
    text = re.sub(r"\b(?:rir|rpe)\s*\d+(?:[,.]\d+)?\b", " ", text)
    match = re.search(r"\b(\d{1,2})\s*(?:rep|reps|repeticiones)\b", text)
    if match:
        return [int(match.group(1))]

    match = re.search(r"\b(\d{1,2})\b", text)
    if match:
        return [int(match.group(1))]
    return []


def _extract_metric(normalized_text: str, metric: str) -> float | None:
    match = re.search(rf"\b{metric}\s*(\d+(?:[,.]\d+)?)\b", normalized_text)
    if not match:
        return None
    return _number(match.group(1))


def _number(value: str) -> float:
    number = float(value.replace(",", "."))
    return int(number) if number.is_integer() else number


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.lower())
    ascii_value = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", ascii_value).strip()


def _weekly_strength_mode(summary: dict[str, Any], wellness: dict[str, Any]) -> str:
    fatigue = summary.get("fatigue", {})
    if fatigue.get("level") == "alta":
        return "maintenance"
    body_battery = wellness.get("body_battery", {})
    if isinstance(body_battery, dict) and body_battery.get("drained", 0) and body_battery.get("drained", 0) >= 80:
        return "maintenance"
    return "normal"
