from __future__ import annotations

from typing import Any


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
