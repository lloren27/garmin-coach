from __future__ import annotations

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


def format_load(sync: dict[str, Any] | None) -> str:
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

    return (
        "Carga semanal\n"
        f"Total semana: {week.get('hours', 0)} h, {week.get('km', 0)} km\n"
        f"Running 7d: {running.get('sessions_7d', 0)} sesiones, {running.get('km_7d', 0)} km, {running.get('hours_7d', 0)} h\n"
        f"Bici 7d: {cycling.get('sessions_7d', 0)} sesiones, {cycling.get('km_7d', 0)} km, {cycling.get('hours_7d', 0)} h\n"
        f"Fuerza 7d: {strength.get('sessions_7d', 0)} sesiones, {strength.get('hours_7d', 0)} h\n"
        f"Carga equivalente aprox: {equivalent_hours} h running\n"
        f"Ratio agudo/cronico: {fatigue.get('acute_chronic_ratio', 'n/a')}\n"
        f"Lectura: {_load_reading(fatigue, equivalent_hours)}"
    )


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


def format_bike(sync: dict[str, Any] | None) -> str:
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


def format_malaga(sync: dict[str, Any] | None) -> str:
    if not sync:
        return "Necesito una sincronizacion Garmin antes de evaluar Malaga."

    payload = sync.get("payload", {})
    plan_level = payload.get("plan_level", {})
    summary = payload.get("summary", {})

    verdict = (
        "Puedes pelear el sub-3:40 si construimos la tirada larga sin molestias. "
        "La velocidad aparece, falta resistencia especifica."
    )
    return (
        "Maraton de Malaga\n"
        f"{verdict}\n"
        f"Nivel actual: {plan_level.get('level', 'n/a')}\n"
        f"Objetivo: {plan_level.get('goal', 'n/a')}\n"
        f"Km 28 dias: {summary.get('km_28d', 'n/a')}\n"
        f"Tirada larga reciente: {_longest_run(summary)}\n"
        "Ritmo objetivo 3:40: 5:13/km. Salida recomendada: 5:15-5:18/km."
    )


def _longest_run(summary: dict[str, Any]) -> str:
    runs = summary.get("longest_120d") or []
    if not runs:
        return "n/a"
    run = runs[0]
    return f"{run.get('km', 'n/a')} km a {run.get('pace', 'n/a')}"


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
