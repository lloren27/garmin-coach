"""Typed, deterministic intent-resolution contracts for coach requests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
import re
import unicodedata
from zoneinfo import ZoneInfo


class CoachIntent(str, Enum):
    ANALYZE_ACTIVITY = "analyze_activity"
    ANALYZE_DAY = "analyze_day"
    CONSULT_PLAN = "consult_plan"
    RECOMMEND_NEXT = "recommend_next"
    REQUEST_CHANGE = "request_change"
    MIXED = "mixed"
    CLARIFY = "clarify"


class DateSelector(str, Enum):
    BY_DATE = "by_date"
    LATEST_ACTIVITY = "latest_activity"
    LATEST_TRAINING_DAY = "latest_training_day"


class ClarificationCode(str, Enum):
    NO_SCOPE = "no_scope"
    CONTRADICTORY_OPERATION = "contradictory_operation"
    UNSUPPORTED_PARAPHRASE = "unsupported_paraphrase"
    INVALID_DATE = "invalid_date"
    MISSING_ADVICE_DATE = "missing_advice_date"


class DateResolutionScope(str, Enum):
    OBSERVED = "observed"
    ADVICE = "advice"
    PLAN = "plan"


class InvalidDateError(ValueError):
    """Raised when a date explicitly written by the user is impossible."""


_MADRID = ZoneInfo("Europe/Madrid")
_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
    "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}


def _normalize(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(char)
    )


def _checked_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise InvalidDateError("invalid explicit date") from exc


def _month_occurrence(day: int, month: int, today: date, scope: DateResolutionScope) -> date:
    if scope is DateResolutionScope.OBSERVED:
        years = range(today.year, today.year - 9, -1)
    else:
        years = range(today.year, today.year + 9)
    for year in years:
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if scope is DateResolutionScope.OBSERVED and candidate <= today:
            return candidate
        if scope is not DateResolutionScope.OBSERVED and candidate > today:
            return candidate
    raise InvalidDateError("invalid or unresolvable month/day")


def resolve_dates(
    text: str,
    *,
    now: datetime,
    scope: DateResolutionScope,
) -> tuple[date, ...]:
    """Resolve Spanish date expressions into Madrid-local civil dates.

    `OBSERVED` selects the latest past occurrence (including today) for an
    unqualified weekday/month-day. `ADVICE` and `PLAN` select the next future
    occurrence. Explicit ISO and DD/MM/YYYY dates keep their written year.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(scope, DateResolutionScope):
        raise TypeError("scope must be a DateResolutionScope")

    today = now.astimezone(_MADRID).date()
    normalized = _normalize(text)
    remaining = list(normalized)
    found: list[date] = []

    def consume(pattern: str, convert) -> None:
        nonlocal remaining
        current = "".join(remaining)
        for match in re.finditer(pattern, current):
            found.extend(convert(match))
            remaining[match.start():match.end()] = " " * (match.end() - match.start())

    def explicit_numeric(match):
        value = match.group(0)
        try:
            if "-" in value:
                return [date.fromisoformat(value)]
            day, month, year = map(int, value.split("/"))
            return [_checked_date(year, month, day)]
        except ValueError as exc:
            raise InvalidDateError("invalid explicit date") from exc

    consume(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b", explicit_numeric)

    month_pattern = r"\b(?:el\s+)?(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)(?:\s+de\s+(\d{4}))?\b"

    def named_month(match):
        day = int(match.group(1))
        month = _MONTHS[match.group(2)]
        year = int(match.group(3)) if match.group(3) else None
        return [_checked_date(year, month, day)] if year else [_month_occurrence(day, month, today, scope)]

    consume(month_pattern, named_month)

    def week_dates(match):
        phrase = match.group(0)
        monday = today - timedelta(days=today.weekday())
        if phrase in {"esta semana", "esta semana"}:
            if scope is DateResolutionScope.OBSERVED:
                start, end = monday, today
            elif scope is DateResolutionScope.ADVICE:
                start, end = today, monday + timedelta(days=6)
            else:
                start, end = monday, monday + timedelta(days=6)
        elif phrase == "semana pasada":
            start = monday - timedelta(days=7)
            end = start + timedelta(days=6)
        else:  # próxima semana
            start = monday + timedelta(days=7)
            end = start + timedelta(days=6)
        return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

    consume(r"\b(?:esta semana|semana pasada|proxima semana)\b", week_dates)

    def relative_day(match):
        token = match.group(1)
        if token == "manana":
            prefix = "".join(remaining[max(0, match.start() - 12):match.start()])
            if re.search(r"(?:esta\s+|por\s+la\s+)$", prefix):
                return []
            return [today + timedelta(days=1)]
        if token == "ayer":
            return [today - timedelta(days=1)]
        return [today]

    consume(r"\b(hoy|ayer|manana)\b", relative_day)

    weekday_pattern = r"\b(?:(?:el\s+)?(pasado|proximo|ultimo|ultima)\s+)?(?:el\s+)?(lunes|martes|miercoles|jueves|viernes|sabado|domingo)(?:\s+(pasado|proximo))?\b"

    def weekday_date(match):
        prefix, name, suffix = match.groups()
        modifier = suffix or prefix
        target_weekday = _WEEKDAYS[name]
        if modifier == "pasado":
            delta = (today.weekday() - target_weekday) % 7 or 7
            return [today - timedelta(days=delta)]
        if modifier in ("proximo", "ultima", "ultimo"):
            if modifier == "proximo":
                delta = (target_weekday - today.weekday()) % 7 or 7
                return [today + timedelta(days=delta)]
        if scope is DateResolutionScope.OBSERVED:
            delta = (today.weekday() - target_weekday) % 7
            return [today - timedelta(days=delta)]
        delta = (target_weekday - today.weekday()) % 7 or 7
        return [today + timedelta(days=delta)]

    consume(weekday_pattern, weekday_date)
    return tuple(sorted(set(found)))


@dataclass(frozen=True)
class IntentComponent:
    intent: CoachIntent
    selector: DateSelector = DateSelector.BY_DATE
    observed_dates: tuple[date, ...] = ()
    advice_dates: tuple[date, ...] = ()
    clarification_code: ClarificationCode | None = None

    def __post_init__(self) -> None:
        if (self.intent is CoachIntent.CLARIFY) != (self.clarification_code is not None):
            raise ValueError("CLARIFY components require exactly one clarification code")
        if self.selector in (DateSelector.LATEST_ACTIVITY, DateSelector.LATEST_TRAINING_DAY):
            if self.observed_dates or self.advice_dates:
                raise ValueError("latest selectors cannot carry explicit dates")
        for dates in (self.observed_dates, self.advice_dates):
            if not isinstance(dates, tuple) or any(type(value) is not date for value in dates):
                raise TypeError("intent component dates must be tuples of datetime.date values")

    @property
    def clarification_template_key(self) -> str | None:
        return self.clarification_code.value if self.clarification_code else None


@dataclass(frozen=True)
class IntentResolution:
    components: tuple[IntentComponent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.components, tuple) or not self.components:
            raise ValueError("intent resolution requires a non-empty tuple of components")
        if any(not isinstance(component, IntentComponent) for component in self.components):
            raise TypeError("intent resolution components must be IntentComponent values")

    @property
    def primary_intent(self) -> CoachIntent:
        intents = {component.intent for component in self.components}
        if len(intents) == 1:
            return next(iter(intents))
        return CoachIntent.MIXED

    @property
    def selector(self) -> DateSelector | None:
        selectors = {component.selector for component in self.components}
        return next(iter(selectors)) if len(selectors) == 1 else None

    @property
    def observed_dates(self) -> tuple[date, ...]:
        return tuple(sorted({day for item in self.components for day in item.observed_dates}))

    @property
    def advice_dates(self) -> tuple[date, ...]:
        return tuple(sorted({day for item in self.components for day in item.advice_dates}))

    @property
    def change_requested(self) -> bool:
        return any(component.intent is CoachIntent.REQUEST_CHANGE for component in self.components)
