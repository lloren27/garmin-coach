from __future__ import annotations

import re
import unicodedata
from typing import Any


def format_help() -> str:
    return (
        "Comandos Garmin Coach\n"
        "/hoy - estado del dia\n"
        "/semana - carga de la semana\n"
        "/ultima - ultima actividad\n"
        "/proximo - entreno recomendado\n"
        "/fatiga - riesgo de fatiga\n"
        "/carga - carga running/bici/fuerza\n"
        "/tendencia - evolucion semanal\n"
        "/feedback - analiza la ultima actividad\n"
        "/sync - solicita sincronizacion desde el Mac\n"
        "/perfil - guarda sexo, edad, peso, altura, FC, FTP y objetivos\n"
        "/checkin - guarda sensaciones: rpe, sueno, energia, molestias\n"
        "/ajustar - adapta el proximo entreno con tus sensaciones\n"
        "/bici - resumen de ciclismo\n"
        "/fuerza - resumen de fuerza\n"
        "/malaga - foco Maraton de Malaga\n"
        "/syncinfo - ultima sincronizacion"
    )


def format_status(sync: dict[str, Any] | None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    payload = sync.get("payload", {})
    summary = payload.get("summary", {})
    generated_at = payload.get("generated_at") or sync.get("received_at")

    return (
        "Estado Garmin Coach\n"
        f"Ultima sincronizacion: {generated_at}\n"
        f"Carreras 120 dias: {summary.get('runs_count_120d', 'n/a')}\n"
        f"Km ultimos 28 dias: {summary.get('km_28d', 'n/a')}\n"
        f"Media semanal 8 semanas: {summary.get('avg_weekly_km_8w', 'n/a')}\n"
        f"Tirada mas larga: {_longest_run(summary)}"
    )


def format_syncinfo(sync: dict[str, Any] | None, sync_request: dict[str, Any] | None = None) -> str:
    lines = []
    if not sync:
        lines.append("Sin sincronizaciones todavia.")
    else:
        lines.append(f"Ultima sincronizacion recibida: {sync.get('received_at')}")
    if sync_request:
        status = sync_request.get("status", "n/a")
        requested_at = sync_request.get("requested_at", "n/a")
        lines.append(f"Ultima peticion /sync: {status} ({requested_at})")
        if sync_request.get("completed_at"):
            lines.append(f"Procesada: {sync_request.get('completed_at')}")
        if sync_request.get("last_error"):
            lines.append(f"Error: {str(sync_request.get('last_error'))[:160]}")
    return "\n".join(lines)


def format_sync_requested(document: dict[str, Any], sync: dict[str, Any] | None = None) -> str:
    lines = [
        "Sincronizacion solicitada",
        f"Peticion: {document.get('requested_at')}",
    ]
    if sync:
        lines.append(f"Ultimos datos actuales: {sync.get('received_at')}")
    lines.append("El Mac la ejecutara en cuanto este despierto y el watcher local la detecte.")
    return "\n".join(lines)


def format_today(sync: dict[str, Any] | None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    payload = sync.get("payload", {})
    summary = payload.get("summary", {})
    today = summary.get("today", {})
    wellness = payload.get("wellness", {})
    daily = _clean_dict(wellness.get("daily"))
    sleep = _clean_dict(wellness.get("sleep"))
    hrv = _clean_dict(wellness.get("hrv"))
    readiness = wellness.get("training_readiness")
    fatigue = summary.get("fatigue", {})

    lines = [
        f"Hoy ({today.get('date', 'n/a')})",
        f"Actividades: {len(today.get('activities') or [])}",
        f"Entreno: {today.get('training_minutes', 0)} min, {today.get('km', 0)} km",
    ]
    if daily:
        lines.append(f"Pasos: {daily.get('steps', 'n/a')}")
        lines.append(f"Pulso reposo: {daily.get('resting_hr', 'n/a')}")
    if sleep and sleep.get("sleep_seconds"):
        lines.append(f"Sueno: {_format_duration(sleep.get('sleep_seconds'))}")
        if sleep.get("score"):
            lines.append(f"Sleep score: {sleep.get('score')}")
    if hrv:
        lines.append(f"HRV: {hrv.get('last_night_avg') or hrv.get('weekly_avg') or hrv.get('status') or 'disponible'}")
    score = _readiness_score(readiness)
    if score:
        lines.append(f"Training readiness: {score}")
    lines.append(f"Fatiga estimada: {fatigue.get('level', 'n/a')}")
    lines.append(f"Recomendacion: {summary.get('next_workout', {}).get('title', 'rodaje facil')}")
    return "\n".join(lines)


def format_week(sync: dict[str, Any] | None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    summary = sync.get("payload", {}).get("summary", {})
    week = summary.get("week", {})
    sports = week.get("by_sport", {})
    running = sports.get("running", {})
    cycling = sports.get("cycling", {})
    strength = sports.get("strength", {})

    return (
        f"Semana desde {week.get('start', 'n/a')}\n"
        f"Total: {week.get('activities', 0)} actividades, {week.get('hours', 0)} h, {week.get('km', 0)} km\n"
        f"Running: {running.get('sessions', 0)} sesiones, {running.get('km', 0)} km\n"
        f"Ciclismo: {cycling.get('sessions', 0)} sesiones, {cycling.get('km', 0)} km, {cycling.get('hours', 0)} h\n"
        f"Fuerza: {strength.get('sessions', 0)} sesiones, {strength.get('hours', 0)} h\n"
        f"Lectura: {_week_reading(summary)}"
    )


def format_latest(sync: dict[str, Any] | None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    activities = sync.get("payload", {}).get("summary", {}).get("activities") or []
    if not activities:
        return "No encuentro actividades recientes en la ultima sincronizacion."

    activity = activities[-1]
    lines = [
        "Ultima actividad",
        f"{activity.get('date', 'n/a')} - {activity.get('name', 'Actividad')}",
        f"Tipo: {activity.get('sport', 'n/a')}",
        f"Duracion: {_format_duration(activity.get('duration_s'))}",
    ]
    if activity.get("km"):
        lines.append(f"Distancia: {activity.get('km')} km")
    if activity.get("pace"):
        lines.append(f"Ritmo: {activity.get('pace')}")
    if activity.get("avg_speed_kmh") and activity.get("sport") == "cycling":
        lines.append(f"Velocidad media: {activity.get('avg_speed_kmh')} km/h")
    if activity.get("avg_hr"):
        lines.append(f"Pulso medio: {activity.get('avg_hr')}")
    if activity.get("training_effect"):
        lines.append(f"Training effect: {activity.get('training_effect')}")
    lines.append(f"Feedback: {_latest_feedback(activity)}")
    return "\n".join(lines)


def format_feedback(
    sync: dict[str, Any] | None,
    checkins: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    activity = _latest_activity(sync)
    if not activity:
        return "No encuentro actividades recientes para analizar."

    summary = sync.get("payload", {}).get("summary", {})
    fatigue = summary.get("fatigue", {})
    latest_checkin = _latest_checkin(checkins)
    sport = activity.get("sport", "other")
    lines = [
        "Feedback ultima actividad",
        f"{activity.get('date', 'n/a')} - {activity.get('name', 'Actividad')}",
        f"Tipo: {sport}",
        f"Duracion: {_format_duration(activity.get('duration_s'))}",
    ]
    if activity.get("km"):
        lines.append(f"Distancia: {activity.get('km')} km")
    if sport == "cycling" and activity.get("avg_speed_kmh"):
        lines.append(f"Velocidad: {activity.get('avg_speed_kmh')} km/h")
    elif activity.get("pace"):
        lines.append(f"Ritmo: {activity.get('pace')}")
    if activity.get("avg_hr"):
        lines.append(f"Pulso medio: {activity.get('avg_hr')}")
        hr_context = _relative_hr_line(activity.get("avg_hr"), profile)
        if hr_context:
            lines.append(hr_context)
    if activity.get("avg_power") or activity.get("normalized_power"):
        lines.append(f"Potencia: media {activity.get('avg_power', 'n/a')} W, NP {activity.get('normalized_power', 'n/a')} W")
        power_context = _power_context_line(activity, profile)
        if power_context:
            lines.append(power_context)
    if activity.get("training_effect"):
        lines.append(f"Training effect: {activity.get('training_effect')}")

    lines.append(f"Lectura: {_activity_coach_reading(activity, fatigue)}")
    lines.append(f"Impacto en plan: {_activity_plan_impact(activity, summary)}")
    if latest_checkin:
        lines.append(f"Con tu check-in: {_checkin_reading(latest_checkin)}")
    lines.append(f"Siguiente paso: {_next_step_after_activity(activity, fatigue, latest_checkin)}")
    return "\n".join(lines)


def format_next(sync: dict[str, Any] | None) -> str:
    if not sync:
        return "Necesito una sincronizacion Garmin antes de recomendar el proximo entreno."

    next_workout = sync.get("payload", {}).get("summary", {}).get("next_workout", {})
    return (
        "Proximo entreno\n"
        f"{next_workout.get('title', 'Rodaje facil')}\n"
        f"{next_workout.get('details', '45-60 min suave.')}\n"
        f"Motivo: {next_workout.get('reason', 'Mantener continuidad sin acumular fatiga extra.')}"
    )


def format_checkin_help() -> str:
    return (
        "Check-in\n"
        "Escribe algo asi:\n"
        "/checkin rpe 6 sueno 7 energia 6 molestia gemelo nota piernas cargadas\n"
        "Campos utiles: rpe 1-10, sueno 1-10, energia 1-10, molestias/no molestias, nota libre."
    )


def parse_checkin(text: str, user_id: str | None = None) -> dict[str, Any]:
    note = text.strip()
    lowered = _normalize_text(note)
    checkin = {
        "user_id": user_id,
        "raw": note,
        "rpe": _extract_score(lowered, ("rpe", "esfuerzo")),
        "sleep": _extract_score(lowered, ("sueno", "dormir", "sleep")),
        "energy": _extract_score(lowered, ("energia", "energy")),
        "mood": _extract_score(lowered, ("animo", "mood")),
        "soreness": _extract_soreness(lowered),
        "pain": _extract_pain(lowered),
    }
    return {key: value for key, value in checkin.items() if value not in (None, "")}


def format_checkin_saved(document: dict[str, Any]) -> str:
    checkin = document.get("checkin", {})
    parts = []
    for label, key in (("RPE", "rpe"), ("Sueno", "sleep"), ("Energia", "energy"), ("Animo", "mood")):
        if key in checkin:
            parts.append(f"{label}: {checkin[key]}/10")
    if checkin.get("soreness"):
        parts.append(f"Molestias: {checkin['soreness']}")
    if checkin.get("pain"):
        parts.append(f"Dolor: {checkin['pain']}")
    if not parts and checkin.get("raw"):
        parts.append("Nota libre guardada")
    details = "\n".join(parts) if parts else "Guardado."
    return f"Check-in guardado\n{details}\nLo usare en /ajustar y /feedback."


def format_profile_help() -> str:
    return (
        "Perfil deportivo\n"
        "Guarda datos asi:\n"
        "/perfil sexo hombre edad 44 altura 176 peso 72 fcmax 178 fcreposo 52 fcumbral 162 ftp 230 ritmo_umbral 4:50 objetivo_maraton 3:40 marca_maraton 3:40\n"
        "Puedes actualizar solo un campo: /perfil peso 71.5 ftp 235\n"
        "Campos: sexo, edad, altura, peso, fcmax, fcreposo, fcumbral, ftp, ritmo_umbral, objetivo_maraton, marca_maraton, nota."
    )


def parse_profile(text: str, user_id: str | None = None) -> dict[str, Any]:
    raw = text.strip()
    normalized = _normalize_text(raw)
    profile: dict[str, Any] = {"user_id": user_id, "raw": raw}

    sex = _extract_sex(normalized)
    if sex:
        profile["sex"] = sex

    age = _bounded_number(_extract_float_after(normalized, ("edad", "age")), 12, 90)
    if age is not None:
        profile["age"] = int(age)

    height = _extract_float_after(normalized, ("altura", "height", "talla"))
    if height is not None and height <= 3:
        height *= 100
    height = _bounded_number(height, 100, 230)
    if height is not None:
        profile["height_cm"] = round(height, 1)

    weight = _bounded_number(_extract_float_after(normalized, ("peso", "weight")), 35, 200)
    if weight is not None:
        profile["weight_kg"] = round(weight, 1)

    max_hr = _bounded_number(_extract_float_after(normalized, ("fcmax", "maxhr", "max_hr")), 90, 230)
    if max_hr is not None:
        profile["max_hr"] = int(max_hr)

    resting_hr = _bounded_number(
        _extract_float_after(normalized, ("fcreposo", "fc_reposo", "reposo", "restinghr", "resting_hr")),
        30,
        100,
    )
    if resting_hr is not None:
        profile["resting_hr"] = int(resting_hr)

    lactate_hr = _bounded_number(
        _extract_float_after(normalized, ("fcumbral", "fc_umbral", "umbral", "lactatehr", "lactate_hr")),
        90,
        220,
    )
    if lactate_hr is not None:
        profile["lactate_hr"] = int(lactate_hr)

    ftp = _bounded_number(_extract_float_after(normalized, ("ftp",)), 50, 600)
    if ftp is not None:
        profile["ftp"] = int(ftp)

    threshold_pace = _extract_time_after(normalized, ("ritmo_umbral", "pace_umbral", "threshold_pace"))
    if threshold_pace:
        profile["running_threshold_pace"] = threshold_pace

    marathon_goal = _extract_time_after(normalized, ("objetivo_maraton", "objetivo", "marathon_goal"))
    if marathon_goal:
        profile["marathon_goal"] = marathon_goal

    marathon_pb = _extract_time_after(normalized, ("marca_maraton", "marca", "pb", "marathon_pb"))
    if marathon_pb:
        profile["marathon_pb"] = marathon_pb

    note = _extract_note(raw)
    if note:
        profile["notes"] = note

    return {key: value for key, value in profile.items() if value not in (None, "")}


def merge_profile(
    existing_document: dict[str, Any] | None,
    update: dict[str, Any],
    user_id: str | None = None,
) -> dict[str, Any]:
    existing = _profile_payload(existing_document).copy()
    if user_id and "user_id" not in existing:
        existing["user_id"] = user_id
    existing.update({key: value for key, value in update.items() if value not in (None, "")})
    return existing


def format_profile(document: dict[str, Any] | None) -> str:
    if not document:
        return format_profile_help()

    profile = _profile_payload(document)
    if not profile:
        return format_profile_help()

    lines = ["Perfil deportivo"]
    if document.get("updated_at"):
        lines.append(f"Actualizado: {document.get('updated_at')}")
    context = _profile_context_line(profile)
    if context:
        lines.append(f"Datos: {context}")
    if profile.get("max_hr") or profile.get("resting_hr") or profile.get("lactate_hr"):
        lines.append(
            "Pulso: "
            f"FCmax {profile.get('max_hr', 'n/a')}, "
            f"reposo {profile.get('resting_hr', 'n/a')}, "
            f"umbral {profile.get('lactate_hr', 'n/a')}"
        )
    if profile.get("ftp") or profile.get("weight_kg"):
        lines.append(f"Bici: FTP {profile.get('ftp', 'n/a')} W, peso {profile.get('weight_kg', 'n/a')} kg")
    if profile.get("running_threshold_pace"):
        lines.append(f"Ritmo umbral running: {profile.get('running_threshold_pace')}/km")
    if profile.get("marathon_goal") or profile.get("marathon_pb"):
        lines.append(
            "Maraton: "
            f"objetivo {profile.get('marathon_goal', 'n/a')}, "
            f"marca {profile.get('marathon_pb', 'n/a')}"
        )
    if profile.get("notes"):
        lines.append(f"Nota: {profile.get('notes')}")
    missing = _missing_profile_fields(profile)
    if missing:
        lines.append("Para afinar mas faltan: " + ", ".join(missing))
    lines.append("Actualizar: /perfil peso 71.5 ftp 235")
    return "\n".join(lines)


def format_profile_saved(document: dict[str, Any]) -> str:
    return "Perfil actualizado\n" + format_profile(document)


def format_adjust(
    sync: dict[str, Any] | None,
    checkins: list[dict[str, Any]] | None = None,
    note: str = "",
    profile: dict[str, Any] | None = None,
) -> str:
    if not sync:
        return "Necesito una sincronizacion Garmin antes de ajustar el plan."

    summary = sync.get("payload", {}).get("summary", {})
    fatigue = summary.get("fatigue", {})
    activity = _latest_activity(sync)
    transient = parse_checkin(note) if note.strip() else {}
    latest = transient or _latest_checkin(checkins)
    risk = _adjustment_risk(fatigue, activity, latest)

    if risk >= 5:
        recommendation = "cambia el proximo entreno por descanso o 30-40 min muy facil."
        details = "Nada de intensidad. Movilidad, comida y dormir mandan."
    elif risk >= 3:
        recommendation = "reduce el entreno: 40-55 min facil o bici Z2 suave."
        details = "Mantienes continuidad, pero sin meter mas carga dura."
    else:
        next_workout = summary.get("next_workout", {})
        recommendation = next_workout.get("title", "mantener rodaje facil")
        details = next_workout.get("details", "45-60 min suave.")

    lines = [
        "Ajuste del plan",
        f"Riesgo estimado: {_risk_label(risk)} ({risk}/7)",
        f"Decision: {recommendation}",
        f"Detalle: {details}",
        f"Por que: {_adjustment_reason(fatigue, activity, latest)}",
    ]
    if latest:
        lines.append(f"Sensaciones usadas: {_checkin_reading(latest)}")
    else:
        lines.append("Tip: anade sensaciones con /checkin para afinar mas.")
    context = _profile_context_line(_profile_payload(profile))
    if context:
        lines.append(f"Perfil usado: {context}")
    return "\n".join(lines)


def format_fatigue(sync: dict[str, Any] | None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    fatigue = sync.get("payload", {}).get("summary", {}).get("fatigue", {})
    level = fatigue.get("level", "n/a")
    if level == "alta":
        advice = "baja intensidad 24-48 h y prioriza dormir."
    elif level == "media":
        advice = "manten el plan, pero no conviertas los rodajes en tempo."
    else:
        advice = "puedes entrenar normal si las sensaciones acompanan."

    return (
        "Fatiga\n"
        f"Nivel: {level}\n"
        f"Horas ultimos 7 dias: {fatigue.get('hours_7d', 'n/a')}\n"
        f"Media semanal 28 dias: {fatigue.get('weekly_avg_hours_28d', 'n/a')}\n"
        f"Ratio agudo/cronico: {fatigue.get('acute_chronic_ratio', 'n/a')}\n"
        f"Sesiones duras 7 dias: {fatigue.get('hard_sessions_7d', 'n/a')}\n"
        f"Dias seguidos con actividad: {fatigue.get('days_since_rest', 'n/a')}\n"
        f"Consejo: {advice}"
    )


def format_load(sync: dict[str, Any] | None, profile: dict[str, Any] | None = None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    summary = sync.get("payload", {}).get("summary", {})
    week = summary.get("week", {})
    sports = summary.get("sports", {})
    fatigue = summary.get("fatigue", {})
    running = sports.get("running", {})
    cycling = sports.get("cycling", {})
    strength = sports.get("strength", {})

    running_weight = _safe_float(running.get("hours_7d")) * 1.0
    cycling_weight = _safe_float(cycling.get("hours_7d")) * 0.65
    strength_weight = _safe_float(strength.get("hours_7d")) * 0.45
    equivalent_hours = round(running_weight + cycling_weight + strength_weight, 1)

    lines = [
        "Carga semanal",
        f"Total semana: {week.get('hours', 0)} h, {week.get('km', 0)} km",
        f"Running 7d: {running.get('sessions_7d', 0)} sesiones, {running.get('km_7d', 0)} km, {running.get('hours_7d', 0)} h",
        f"Bici 7d: {cycling.get('sessions_7d', 0)} sesiones, {cycling.get('km_7d', 0)} km, {cycling.get('hours_7d', 0)} h",
        f"Fuerza 7d: {strength.get('sessions_7d', 0)} sesiones, {strength.get('hours_7d', 0)} h",
        f"Carga equivalente aprox: {equivalent_hours} h running",
        f"Ratio agudo/cronico: {fatigue.get('acute_chronic_ratio', 'n/a')}",
    ]
    athlete = _profile_payload(profile)
    if athlete.get("weight_kg") or athlete.get("ftp"):
        lines.append(f"Contexto perfil: peso {athlete.get('weight_kg', 'n/a')} kg, FTP {athlete.get('ftp', 'n/a')} W")
    lines.append(f"Lectura: {_load_reading(fatigue, equivalent_hours)}")
    return "\n".join(lines)


def format_trend(sync: dict[str, Any] | None, history: list[dict[str, Any]] | None = None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    summary = sync.get("payload", {}).get("summary", {})
    weekly = summary.get("weekly") or []
    if not weekly:
        return "Todavia no tengo semanas suficientes para calcular tendencia."

    last_4 = weekly[-4:]
    prev_4 = weekly[-8:-4]
    last_4_km = round(sum(_safe_float(week.get("km")) for week in last_4), 1)
    prev_4_km = round(sum(_safe_float(week.get("km")) for week in prev_4), 1)
    delta = round(last_4_km - prev_4_km, 1) if prev_4 else None
    avg_last = round(last_4_km / len(last_4), 1)
    longest_now = max(last_4, key=lambda week: _safe_float(week.get("long_run_km")))
    snapshots = len(history or [])

    lines = [
        "Tendencia",
        f"Media running ultimas 4 semanas: {avg_last} km/semana",
        f"Total ultimas 4 semanas: {last_4_km} km",
    ]
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        lines.append(f"Vs 4 semanas previas: {sign}{delta} km")
    lines.extend(
        [
            f"Tirada larga reciente en el bloque: {longest_now.get('long_run_km', 'n/a')} km",
            f"Sincronizaciones en historico: {snapshots}",
            f"Lectura: {_trend_reading(avg_last, _safe_float(longest_now.get('long_run_km')), delta)}",
        ]
    )
    return "\n".join(lines)


def format_bike(sync: dict[str, Any] | None, profile: dict[str, Any] | None = None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    cycling = _sport_summary(sync, "cycling")
    latest = cycling.get("latest") or {}
    longest = cycling.get("longest") or {}
    if cycling.get("sessions_120d", 0) == 0:
        return "No encuentro entrenos de ciclismo en la ultima sincronizacion."

    lines = [
        "Ciclismo",
        f"Sesiones 28 dias: {cycling.get('sessions_28d', 0)}",
        f"Volumen 28 dias: {cycling.get('km_28d', 0)} km, {cycling.get('hours_28d', 0)} h",
        f"Ultima bici: {_activity_line(latest)}",
        f"Salida mas larga: {_activity_line(longest)}",
    ]
    if latest.get("avg_power") or latest.get("normalized_power"):
        lines.append(f"Potencia ultima: media {latest.get('avg_power', 'n/a')} W, NP {latest.get('normalized_power', 'n/a')} W")
        power_context = _power_context_line(latest, profile)
        if power_context:
            lines.append(power_context)
    lines.append("Lectura: la bici suma base aerobica con menos impacto, pero las salidas intensas cuentan como carga dura para las series de running.")
    return "\n".join(lines)


def format_strength(sync: dict[str, Any] | None) -> str:
    if not sync:
        return "Todavia no tengo datos sincronizados desde Garmin."

    strength = _sport_summary(sync, "strength")
    latest = strength.get("latest") or {}
    if strength.get("sessions_120d", 0) == 0:
        return "No encuentro sesiones de fuerza en la ultima sincronizacion."

    return (
        "Fuerza\n"
        f"Sesiones 28 dias: {strength.get('sessions_28d', 0)}\n"
        f"Tiempo 28 dias: {strength.get('hours_28d', 0)} h\n"
        f"Ultima sesion: {_activity_line(latest)}\n"
        "Consejo: manten 2 sesiones semanales cortas. Pierna pesada lejos de series y tirada larga; core, gluteo y gemelo ayudan mucho a running y bici."
    )


def format_malaga(sync: dict[str, Any] | None, profile: dict[str, Any] | None = None) -> str:
    if not sync:
        return "Necesito una sincronizacion Garmin antes de evaluar Malaga."

    payload = sync.get("payload", {})
    plan_level = payload.get("plan_level", {})
    summary = payload.get("summary", {})
    athlete = _profile_payload(profile)
    goal = athlete.get("marathon_goal") or "3:40"
    pb = athlete.get("marathon_pb") or "3:40"
    target_pace = _marathon_pace_from_time(str(goal)) or "5:13/km"

    verdict = (
        "Puedes pelear el sub-3:40 si construimos la tirada larga sin molestias. "
        "La velocidad aparece, falta resistencia especifica."
    )
    lines = [
        "Maraton de Malaga",
        verdict,
        f"Nivel actual: {plan_level.get('level', 'n/a')}",
        f"Objetivo plan: {plan_level.get('goal', 'n/a')}",
        f"Marca/objetivo perfil: PB {pb}, objetivo {goal}",
        f"Km 28 dias: {summary.get('km_28d', 'n/a')}",
        f"Tirada larga reciente: {_longest_run(summary)}",
        f"Ritmo objetivo {goal}: {target_pace}. Salida recomendada: 3-5 s/km mas suave los primeros 8-10 km.",
    ]
    context = _profile_context_line(athlete)
    if context:
        lines.append(f"Perfil usado: {context}")
    return "\n".join(lines)


def _longest_run(summary: dict[str, Any]) -> str:
    runs = summary.get("longest_120d") or []
    if not runs:
        return "n/a"
    run = runs[0]
    return f"{run.get('km', 'n/a')} km a {run.get('pace', 'n/a')}"


def _latest_activity(sync: dict[str, Any]) -> dict[str, Any] | None:
    activities = sync.get("payload", {}).get("summary", {}).get("activities") or []
    return activities[-1] if activities else None


def _latest_checkin(checkins: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not checkins:
        return {}
    document = checkins[-1]
    return document.get("checkin", document)


def _clean_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and "_unavailable" not in value:
        return value
    return {}


def _readiness_score(value: Any) -> Any:
    if isinstance(value, list) and value:
        item = value[0]
        if isinstance(item, dict):
            return item.get("score") or item.get("trainingReadinessScore")
    if isinstance(value, dict) and "_unavailable" not in value:
        return value.get("score") or value.get("trainingReadinessScore")
    return None


def _sport_summary(sync: dict[str, Any], sport: str) -> dict[str, Any]:
    return sync.get("payload", {}).get("summary", {}).get("sports", {}).get(sport, {})


def _format_duration(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)):
        return "n/a"
    minutes = round(seconds / 60)
    hours, mins = divmod(minutes, 60)
    if hours:
        return f"{hours} h {mins:02d} min"
    return f"{mins} min"


def _activity_line(activity: dict[str, Any]) -> str:
    if not activity:
        return "n/a"
    bits = [str(activity.get("date", "n/a"))]
    if activity.get("km"):
        bits.append(f"{activity.get('km')} km")
    if activity.get("sport") == "cycling" and activity.get("avg_speed_kmh"):
        bits.append(f"{activity.get('avg_speed_kmh')} km/h")
    elif activity.get("pace"):
        bits.append(str(activity.get("pace")))
    elif activity.get("avg_speed_kmh"):
        bits.append(f"{activity.get('avg_speed_kmh')} km/h")
    bits.append(_format_duration(activity.get("duration_s")))
    return ", ".join(bits)


def _week_reading(summary: dict[str, Any]) -> str:
    fatigue = summary.get("fatigue", {})
    running = summary.get("week", {}).get("by_sport", {}).get("running", {})
    km = running.get("km", 0)
    if fatigue.get("level") == "alta":
        return "semana exigente; conviene proteger recuperacion."
    if km and km < 25:
        return "todavia falta volumen especifico para Malaga."
    return "buena continuidad; conserva faciles los faciles."


def _latest_feedback(activity: dict[str, Any]) -> str:
    sport = activity.get("sport")
    training_effect = activity.get("training_effect")
    if isinstance(training_effect, (int, float)) and training_effect >= 3.5:
        return "sesion exigente; deja el siguiente entreno facil."
    if sport == "running" and activity.get("pace"):
        return "buena pieza para construir ritmo, pero el objetivo maraton depende de alargar tirada."
    if sport == "cycling":
        return "suma aerobica util; si fue intensa, no la ignores al planificar running."
    if sport == "strength":
        return "buena transferencia si no deja agujetas antes de calidad o tirada larga."
    return "cuenta como carga general; ajusta el siguiente dia segun sensaciones."


def _activity_coach_reading(activity: dict[str, Any], fatigue: dict[str, Any]) -> str:
    sport = activity.get("sport")
    te = _safe_float(activity.get("training_effect"))
    if te >= 3.5:
        return "sesion claramente exigente; cuenta como dia duro aunque las sensaciones fueran buenas."
    if sport == "running" and _safe_float(activity.get("km")) >= 14:
        return "pieza importante para resistencia especifica; vigila recuperacion las proximas 24-48 h."
    if sport == "cycling" and (_safe_float(activity.get("hours")) >= 2 or te >= 3):
        return "bici con carga real; ayuda aerobicamente, pero puede restar frescura para series corriendo."
    if sport == "strength":
        return "la fuerza suma mucho si no compromete calidad de carrera ni tirada larga."
    if fatigue.get("level") == "alta":
        return "actividad dentro de una semana cargada; el valor ahora esta en asimilar."
    return "sesion compatible con seguir construyendo base."


def _activity_plan_impact(activity: dict[str, Any], summary: dict[str, Any]) -> str:
    sport = activity.get("sport")
    if sport == "running":
        km = _safe_float(activity.get("km"))
        if km >= 20:
            return "muy buena senal para Malaga; acerca la tirada larga al rango necesario."
        if km >= 10:
            return "suma volumen util, pero aun falta una tirada mas larga semanal."
        return "sirve para continuidad, no cambia mucho el objetivo maraton."
    if sport == "cycling":
        return "cuenta como carga aerobica; evita juntar bici intensa con series o tirada larga sin descanso."
    if sport == "strength":
        return "buena proteccion para running/ciclismo si no deja agujetas fuertes."
    return "impacto general bajo-moderado."


def _next_step_after_activity(
    activity: dict[str, Any],
    fatigue: dict[str, Any],
    checkin: dict[str, Any],
) -> str:
    if checkin and (_safe_float(checkin.get("sleep")) <= 4 or checkin.get("pain")):
        return "descanso o regenerativo, porque las sensaciones pesan mas que el plan."
    if fatigue.get("level") == "alta":
        return "24-48 h faciles antes de otro estimulo fuerte."
    if _safe_float(activity.get("training_effect")) >= 3.5:
        return "siguiente dia facil; no encadenes calidad."
    if activity.get("sport") == "running":
        return "mantener el siguiente entreno en zona facil salvo que toque descanso."
    return "si manana corres, que sea facil y con pulso controlado."


def _checkin_reading(checkin: dict[str, Any]) -> str:
    bits = []
    if "rpe" in checkin:
        bits.append(f"RPE {checkin['rpe']}/10")
    if "sleep" in checkin:
        bits.append(f"sueno {checkin['sleep']}/10")
    if "energy" in checkin:
        bits.append(f"energia {checkin['energy']}/10")
    if checkin.get("soreness"):
        bits.append(f"molestias {checkin['soreness']}")
    if checkin.get("pain"):
        bits.append(f"dolor {checkin['pain']}")
    return ", ".join(bits) if bits else checkin.get("raw", "check-in guardado")


def _extract_score(text: str, labels: tuple[str, ...]) -> int | None:
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\s*[:=]?\s*(10|[1-9])\b", text)
        if match:
            return int(match.group(1))
    return None


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _extract_soreness(text: str) -> str | None:
    if "sin molestias" in text or "no molestias" in text:
        return "no"
    match = re.search(r"\b(?:molestia|molestias|cargado|cargada)\s+([^,.;]+)", text)
    if match:
        return match.group(1).strip()[:80]
    return None


def _extract_pain(text: str) -> str | None:
    if "sin dolor" in text or "no dolor" in text:
        return None
    match = re.search(r"\b(?:dolor|duele)\s+([^,.;]+)", text)
    if match:
        return match.group(1).strip()[:80]
    return None


def _adjustment_risk(
    fatigue: dict[str, Any],
    activity: dict[str, Any] | None,
    checkin: dict[str, Any],
) -> int:
    risk = 0
    if fatigue.get("level") == "alta":
        risk += 3
    elif fatigue.get("level") == "media":
        risk += 1
    if _safe_float(fatigue.get("acute_chronic_ratio")) > 1.3:
        risk += 1
    if activity and _safe_float(activity.get("training_effect")) >= 3.5:
        risk += 1
    if _safe_float(checkin.get("sleep")) and _safe_float(checkin.get("sleep")) <= 4:
        risk += 1
    if _safe_float(checkin.get("energy")) and _safe_float(checkin.get("energy")) <= 4:
        risk += 1
    if _safe_float(checkin.get("rpe")) >= 8:
        risk += 1
    if checkin.get("pain") or (checkin.get("soreness") and checkin.get("soreness") != "no"):
        risk += 2
    return min(risk, 7)


def _risk_label(risk: int) -> str:
    if risk >= 5:
        return "alto"
    if risk >= 3:
        return "medio"
    return "bajo"


def _adjustment_reason(
    fatigue: dict[str, Any],
    activity: dict[str, Any] | None,
    checkin: dict[str, Any],
) -> str:
    reasons = []
    if fatigue.get("level"):
        reasons.append(f"fatiga {fatigue.get('level')}")
    if activity:
        reasons.append(f"ultima actividad {activity.get('sport', 'n/a')}")
    if checkin.get("pain"):
        reasons.append("dolor reportado")
    elif checkin.get("soreness") and checkin.get("soreness") != "no":
        reasons.append("molestias reportadas")
    if _safe_float(checkin.get("sleep")) and _safe_float(checkin.get("sleep")) <= 4:
        reasons.append("sueno bajo")
    if _safe_float(checkin.get("energy")) and _safe_float(checkin.get("energy")) <= 4:
        reasons.append("energia baja")
    return ", ".join(reasons) if reasons else "no hay senales de alarma fuertes."


def _profile_payload(document: dict[str, Any] | None) -> dict[str, Any]:
    if not document:
        return {}
    profile = document.get("profile", document)
    return profile if isinstance(profile, dict) else {}


def _profile_context_line(profile: dict[str, Any]) -> str:
    if not profile:
        return ""
    bits = []
    if profile.get("sex"):
        bits.append(f"sexo {profile.get('sex')}")
    if profile.get("age"):
        bits.append(f"{profile.get('age')} anos")
    if profile.get("height_cm"):
        bits.append(f"{profile.get('height_cm')} cm")
    if profile.get("weight_kg"):
        bits.append(f"{profile.get('weight_kg')} kg")
    return ", ".join(bits) if bits else ""


def _relative_hr_line(avg_hr: Any, document: dict[str, Any] | None) -> str:
    profile = _profile_payload(document)
    avg = _safe_float(avg_hr)
    max_hr = _safe_float(profile.get("max_hr"))
    resting_hr = _safe_float(profile.get("resting_hr"))
    lactate_hr = _safe_float(profile.get("lactate_hr"))
    if not avg:
        return ""

    bits = []
    if max_hr:
        bits.append(f"{round(avg / max_hr * 100)}% FCmax")
    if max_hr and resting_hr and max_hr > resting_hr:
        reserve = (avg - resting_hr) / (max_hr - resting_hr)
        bits.append(f"{round(max(reserve, 0) * 100)}% reserva FC")
    if lactate_hr:
        bits.append(f"{round(avg / lactate_hr * 100)}% FC umbral")
    return "Pulso relativo: " + ", ".join(bits) if bits else ""


def _power_context_line(activity: dict[str, Any], document: dict[str, Any] | None) -> str:
    profile = _profile_payload(document)
    power = _safe_float(activity.get("normalized_power")) or _safe_float(activity.get("avg_power"))
    weight = _safe_float(profile.get("weight_kg"))
    ftp = _safe_float(profile.get("ftp"))
    if not power:
        return ""

    bits = []
    if weight:
        bits.append(f"{round(power / weight, 2)} W/kg")
    if ftp:
        bits.append(f"{round(power / ftp * 100)}% FTP")
    return "Potencia relativa: " + ", ".join(bits) if bits else ""


def _missing_profile_fields(profile: dict[str, Any]) -> list[str]:
    required = (
        ("sex", "sexo"),
        ("age", "edad"),
        ("height_cm", "altura"),
        ("weight_kg", "peso"),
        ("max_hr", "fcmax"),
        ("resting_hr", "fcreposo"),
        ("ftp", "ftp"),
    )
    return [label for key, label in required if not profile.get(key)]


def _extract_sex(text: str) -> str | None:
    match = re.search(r"\b(?:sexo|sex)\s*[:=]?\s*([a-z_ -]+)", text)
    value = match.group(1).split()[0] if match else ""
    if value in {"hombre", "masculino", "male", "m", "varon"}:
        return "hombre"
    if value in {"mujer", "femenino", "female", "f"}:
        return "mujer"
    if value in {"otro", "other", "no_binario", "nobinario"}:
        return "otro"
    return None


def _extract_float_after(text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\s*[:=]?\s*([0-9]+(?:[,.][0-9]+)?)", text)
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def _bounded_number(value: float | None, minimum: float, maximum: float) -> float | None:
    if value is None or value < minimum or value > maximum:
        return None
    return value


def _extract_time_after(text: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\s*[:=]?\s*([0-9]{{1,2}}:[0-9]{{2}}(?::[0-9]{{2}})?)\b", text)
        if match:
            return match.group(1)
    return None


def _extract_note(text: str) -> str | None:
    match = re.search(r"\b(?:nota|notas|note)\s+(.+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()[:240]
    return None


def _marathon_pace_from_time(value: str) -> str | None:
    parts = value.split(":")
    if len(parts) == 2:
        hours_value, minutes_value = parts
        seconds_value = "0"
    elif len(parts) == 3:
        hours_value, minutes_value, seconds_value = parts
    else:
        return None
    try:
        total_seconds = int(hours_value) * 3600 + int(minutes_value) * 60 + int(seconds_value)
    except ValueError:
        return None
    if total_seconds <= 0:
        return None
    pace_seconds = round(total_seconds / 42.195)
    minutes, seconds = divmod(pace_seconds, 60)
    return f"{minutes}:{seconds:02d}/km"


def _safe_float(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _load_reading(fatigue: dict[str, Any], equivalent_hours: float) -> str:
    level = fatigue.get("level")
    ratio = _safe_float(fatigue.get("acute_chronic_ratio"))
    if level == "alta" or ratio > 1.35:
        return "carga alta; conviene absorber antes de meter otra sesion dura."
    if equivalent_hours < 4:
        return "carga baja-moderada; buen momento para construir volumen facil."
    if equivalent_hours > 8:
        return "semana completa; protege sueno, comida y rodajes faciles."
    return "carga razonable; puedes mantener el plan si las piernas responden."


def _trend_reading(avg_last: float, long_run_km: float, delta: float | None) -> str:
    if long_run_km < 18:
        return "para Malaga falta llevar la tirada larga por encima de 24 km."
    if avg_last < 35:
        return "la tendencia mejora, pero aun falta volumen especifico de maraton."
    if delta is not None and delta > 20:
        return "subida rapida; vigila molestias y fatiga residual."
    return "bloque consistente; siguiente mejora: sostener ritmo maraton dentro de tiradas largas."
