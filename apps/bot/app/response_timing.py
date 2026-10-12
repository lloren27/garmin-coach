from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


MADRID = ZoneInfo("Europe/Madrid")
LATE_AFTER = timedelta(hours=6)
LOCAL_DATE_CHANGE_GRACE = timedelta(minutes=30)
FUTURE_CLOCK_TOLERANCE = timedelta(seconds=120)
UNKNOWN_VALIDITY_PREFIX = (
    "Fecha de consulta no disponible; vigencia temporal no confirmada. "
)


def _aware_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def late_response_prefix(created_at: object, *, now: datetime) -> str | None:
    """Return the delivery note for a late or temporally unreliable job."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")

    created = _aware_datetime(created_at)
    if created is None:
        return UNKNOWN_VALIDITY_PREFIX

    elapsed = now.astimezone(timezone.utc) - created.astimezone(timezone.utc)
    if elapsed < timedelta(0):
        if -elapsed <= FUTURE_CLOCK_TOLERANCE:
            elapsed = timedelta(0)
        else:
            return UNKNOWN_VALIDITY_PREFIX

    local_date_changed = created.astimezone(MADRID).date() != now.astimezone(MADRID).date()
    if elapsed >= LATE_AFTER or (
        local_date_changed and elapsed > LOCAL_DATE_CHANGE_GRACE
    ):
        created_local = created.astimezone(MADRID)
        timestamp = created_local.strftime("%d/%m/%Y %H:%M")
        return (
            f"Respuesta tardía a tu consulta del {timestamp}. "
            "Se refiere al contexto temporal de esa consulta; no es una recomendación "
            "actualizada para hoy. Si todavía la necesitas, vuelve a preguntar. "
        )

    return None


def format_late_delivery(answer: str, created_at: object, *, now: datetime) -> str:
    prefix = late_response_prefix(created_at, now=now)
    return f"{prefix}{answer}" if prefix else answer
