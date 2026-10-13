"""Small, allowlisted adapter from Telegram aliases to coach questions."""

from __future__ import annotations

import re
from datetime import datetime
from typing import TypedDict
from zoneinfo import ZoneInfo


MADRID = ZoneInfo("Europe/Madrid")


class AdaptedCoachAlias(TypedDict):
    alias: str
    question: str
    scope: str


ALIASES: dict[str, tuple[str, str]] = {
    "/hoy": ("Analiza mi entrenamiento de hoy.", "today"),
    "/feedback": ("Analiza mi último día de entrenamiento.", "latest_training_day"),
}
_COMMAND = re.compile(r"^(?P<command>/[^\s@]+)(?:@[^\s]+)?(?:\s+(?P<args>.*))?$", re.DOTALL)


def adapt_coach_alias(text: str, *, now: datetime) -> AdaptedCoachAlias | None:
    """Translate an allowlisted command without parsing its argument semantics."""
    if not isinstance(text, str) or not isinstance(now, datetime) or now.tzinfo is None:
        return None
    match = _COMMAND.fullmatch(text.strip())
    if match is None:
        return None
    alias = match.group("command").lower()
    spec = ALIASES.get(alias)
    if spec is None:
        return None
    args = match.group("args")
    if args:
        question = text.strip()
        scope = "latest_available"
    else:
        question, scope = spec
    return {"alias": alias, "question": question, "scope": scope}


def parse_alias_routing_enabled(raw: str | None) -> bool | None:
    """Parse the opt-in switch; None represents an invalid value."""
    if raw is None or raw.strip().lower() in {"", "0", "false", "off"}:
        return False
    if raw.strip().lower() in {"1", "true", "on"}:
        return True
    return None
