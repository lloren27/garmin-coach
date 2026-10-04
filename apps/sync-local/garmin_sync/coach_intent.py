"""Typed, deterministic intent-resolution contracts for coach requests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
import os
import re
import unicodedata
from types import MappingProxyType
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
    PAST_CHANGE_DATE = "past_change_date"
    CONFLICTING_SCOPE = "conflicting_scope"
    CHANGE_NOT_AUTHORIZED = "change_not_authorized"


CLARIFICATION_TEMPLATES = MappingProxyType({
    ClarificationCode.NO_SCOPE: "¿Qué día o actividad quieres consultar?",
    ClarificationCode.CONTRADICTORY_OPERATION: "¿Quieres analizar la sesión o solicitar un cambio?",
    ClarificationCode.UNSUPPORTED_PARAPHRASE: "No he identificado qué quieres consultar. ¿Puedes concretarlo?",
    ClarificationCode.INVALID_DATE: "No reconozco esa fecha. ¿Puedes indicar una fecha válida?",
    ClarificationCode.MISSING_ADVICE_DATE: "¿Para qué día quieres una recomendación?",
    ClarificationCode.PAST_CHANGE_DATE: "Esa sesión ya pasó. ¿Quieres consultar esa fecha o pedir un cambio futuro?",
    ClarificationCode.CONFLICTING_SCOPE: "¿Quieres consultar la última actividad o las actividades de una fecha concreta?",
    ClarificationCode.CHANGE_NOT_AUTHORIZED: "Para cambiar el plan hace falta autorización. No se ha aplicado ningún cambio.",
})


def clarification_prompt(code: ClarificationCode) -> str:
    """Return a fixed clarification prompt without reflecting user text."""
    if not isinstance(code, ClarificationCode):
        raise TypeError("code must be a ClarificationCode")
    return CLARIFICATION_TEMPLATES[code]


class DateResolutionScope(str, Enum):
    OBSERVED = "observed"
    ADVICE = "advice"
    PLAN = "plan"


class InvalidDateError(ValueError):
    """Raised when a date explicitly written by the user is impossible."""


def intent_enforcement_enabled() -> bool:
    return os.getenv("COACH_INTENT_ENFORCEMENT", "").strip().lower() in {"1", "true", "on"}


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

    def next_seven_days(_match):
        return [today + timedelta(days=offset) for offset in range(7)]

    consume(r"\b(?:(?:los\s+)?proximos?\s+)?(?:siete|7)\s+dias\b", next_seven_days)

    def week_dates(match):
        phrase = match.group(0)
        monday = today - timedelta(days=today.weekday())
        if phrase == "esta semana":
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
            if re.search(r"por\s+la\s+$", prefix):
                return []
            if re.search(r"esta\s+$", prefix):
                return [today]
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


# Ordered, reviewable language signals. These provide intent hints; unknown
# phrasings deliberately flow to clarification instead of widening permission.
_INTENT_SIGNAL_PATTERNS = (
    ("explicit_change", r"\b(?:cambia|modifica|mueve|quita|anade|cancela|reprograma)\b"),
    ("analysis_command", r"\b(?:analiza|analizar|analices|revisa|revisar|repasa|repasar|valora|valorar)\b"),
    ("retrospective_question", r"\b(?:como\s+(?:fue|me\s+fue|salio|me\s+salio)|que\s+tal|que\s+hice|he\s+completado|estoy\s+(?:mejor|peor)\s+recuperado)\b"),
    ("plan_question", r"\bque\s+(?:me\s+)?(?:toca|tocaba|tocara|corresponde)\b|\bsesion\s+prevista\b"),
    ("recommendation", r"\b(?:que\s+hago|que\s+(?:debo\s+|deberia\s+|puedo\s+)?hacer|dime\s+que\s+(?:hacer|hago)|como\s+entreno|que\s+me\s+recomiendas|deberia\s+cambiar|que\s+implica)\b"),
)
_PLAN_OBJECT = re.compile(r"\b(?:plan|sesion|entrenamiento|entreno|tirada|carrera)\b")
_NEGATED_CHANGE = re.compile(r"\bno\s+(?:cambies|modifiques|muevas|quites|anadas|canceles|reprogrames)\b")
_NEGATED_ANALYSIS = re.compile(r"\bno\s+(?:analices|revises|repases)\b")
_POSITIVE_CHANGE = re.compile(
    r"\b(?:cambia|modifica|mueve|quita|anade|cancela|reprograma)\b|"
    r"\b(?:quiero|necesito)\s+(?:cambiar|modificar|mover|quitar|anadir|cancelar|reprogramar)\b"
)
_ADVICE_MODAL = re.compile(r"\b(?:deberia|debo|conviene)\b")
_ANALYSIS_VERB = re.compile(r"\b(?:analiza|analizar|revisa|revisar|repasa|repasar|valora|valorar)\b")
_RETROSPECTIVE_QUESTION = re.compile(_INTENT_SIGNAL_PATTERNS[2][1])
_PLAN_QUESTION = re.compile(_INTENT_SIGNAL_PATTERNS[3][1])
_RECOMMENDATION = re.compile(_INTENT_SIGNAL_PATTERNS[4][1])
_LATEST_ACTIVITY = re.compile(r"\b(?:ultima\s+actividad|actividad\s+mas\s+reciente)\b")
_LATEST_TRAINING_DAY = re.compile(r"\b(?:ultimo\s+dia\s+de\s+entrenamiento|ultimo\s+dia\s+que\s+entrene)\b")
_CHANGE_START = re.compile(r"^(?:no\s+)?(?:cambia|modifica|mueve|quita|anade|cancela|reprograma)\b")
_RECOGNIZED_CLAUSE_STARTS = (
    re.compile(r"^(?:no\s+)?(?:analiza|analizar|analices|revisa|revisar|repasa|repasar|valora|valorar)\b"),
    re.compile(r"^(?:no\s+)?(?:dime|consulta|revisa)\b"),
    re.compile(r"^(?:no\s+)?que\s+(?:me\s+)?(?:toca|tocaba|tocara|debo|deberia|puedo)\b"),
    re.compile(r"^(?:no\s+)?que\s+hago\b"),
    re.compile(r"^(?:no\s+)?(?:como\s+(?:fue|me\s+fue)|que\s+tal|que\s+hice)\b"),
    re.compile(r"^(?:no\s+)?(?:que\s+implica|he\s+completado|estoy\s+(?:mejor|peor)\s+recuperado)\b"),
    re.compile(r"^(?:deberia|debo|conviene)\b"),
    _CHANGE_START,
)


def _starts_recognized_clause(text: str) -> bool:
    return any(pattern.search(text.lstrip(" \t¿¡\"'")) for pattern in _RECOGNIZED_CLAUSE_STARTS)


def _contains_intent_signal(text: str) -> bool:
    normalized = _normalize(text)
    return any((
        _ANALYSIS_VERB.search(normalized),
        _NEGATED_ANALYSIS.search(normalized),
        _POSITIVE_CHANGE.search(normalized),
        _NEGATED_CHANGE.search(normalized),
        _PLAN_QUESTION.search(normalized),
        _RECOMMENDATION.search(normalized),
        _RETROSPECTIVE_QUESTION.search(normalized),
        _LATEST_ACTIVITY.search(normalized),
        _LATEST_TRAINING_DAY.search(normalized),
    ))


def _split_intent_clauses(text: str) -> tuple[str, ...]:
    """Split at `y` on a new intent cue; split comma only between intent clauses."""
    separators = list(re.finditer(r",|\by\b", text))
    clauses: list[str] = []
    start = 0
    for separator in separators:
        right = text[separator.end():].strip()
        left = text[start:separator.start()].strip()
        comma_has_two_intents = separator.group(0) != "," or _contains_intent_signal(left)
        if right and comma_has_two_intents and _starts_recognized_clause(right):
            if left:
                clauses.append(left)
            start = separator.end()
    tail = text[start:].strip()
    if tail:
        clauses.append(tail)
    return tuple(clauses or (text.strip(),))


def _clarify(code: ClarificationCode) -> IntentComponent:
    return IntentComponent(CoachIntent.CLARIFY, DateSelector.BY_DATE, clarification_code=code)


def _make_component(intent: CoachIntent, clause: str, now: datetime, selector: DateSelector = DateSelector.BY_DATE) -> IntentComponent:
    if selector in (DateSelector.LATEST_ACTIVITY, DateSelector.LATEST_TRAINING_DAY):
        return IntentComponent(intent, selector)

    normalized = _normalize(clause)
    has_past_cue = bool(re.search(r"\b(?:ayer|pasado|pasada|semana pasada|tocaba)\b", normalized))
    if intent in (CoachIntent.ANALYZE_ACTIVITY, CoachIntent.ANALYZE_DAY):
        scope = DateResolutionScope.OBSERVED
    elif intent is CoachIntent.CONSULT_PLAN and has_past_cue:
        scope = DateResolutionScope.OBSERVED
    elif intent is CoachIntent.CONSULT_PLAN and re.search(r"\besta semana\b", normalized):
        scope = DateResolutionScope.PLAN
    elif intent in (CoachIntent.CONSULT_PLAN, CoachIntent.RECOMMEND_NEXT, CoachIntent.REQUEST_CHANGE):
        scope = DateResolutionScope.ADVICE
    else:
        scope = DateResolutionScope.OBSERVED

    try:
        dates = resolve_dates(clause, now=now, scope=scope)
    except InvalidDateError:
        return _clarify(ClarificationCode.INVALID_DATE)

    if intent in (CoachIntent.ANALYZE_ACTIVITY, CoachIntent.ANALYZE_DAY):
        if not dates:
            return _clarify(ClarificationCode.NO_SCOPE)
        return IntentComponent(intent, selector, observed_dates=dates)

    if intent is CoachIntent.RECOMMEND_NEXT and not dates:
        return _clarify(ClarificationCode.MISSING_ADVICE_DATE)
    if intent is CoachIntent.CONSULT_PLAN and not dates:
        return _clarify(ClarificationCode.NO_SCOPE)
    if intent is CoachIntent.REQUEST_CHANGE and any(day < now.astimezone(_MADRID).date() for day in dates):
        return _clarify(ClarificationCode.PAST_CHANGE_DATE)

    today = now.astimezone(_MADRID).date()
    observed = tuple(day for day in dates if day < today)
    advice = tuple(day for day in dates if day >= today)
    return IntentComponent(intent, selector, observed_dates=observed, advice_dates=advice)


def _classify_clause(clause: str, now: datetime) -> IntentComponent | None:
    normalized = _normalize(clause)
    negative_change = bool(_NEGATED_CHANGE.search(normalized))
    positive_change = bool(_POSITIVE_CHANGE.search(normalized))
    has_plan_object = bool(_PLAN_OBJECT.search(normalized))

    if negative_change and positive_change and has_plan_object:
        return _clarify(ClarificationCode.CONTRADICTORY_OPERATION)

    if _NEGATED_ANALYSIS.search(normalized) and not _ANALYSIS_VERB.search(normalized):
        return None

    if negative_change and not positive_change:
        # A local negation cancels the mutation signal only in this clause.
        if not _ANALYSIS_VERB.search(normalized) and not _PLAN_QUESTION.search(normalized):
            return None

    selector = DateSelector.BY_DATE
    if _LATEST_ACTIVITY.search(normalized):
        selector = DateSelector.LATEST_ACTIVITY
    elif _LATEST_TRAINING_DAY.search(normalized):
        selector = DateSelector.LATEST_TRAINING_DAY
    if selector in (DateSelector.LATEST_ACTIVITY, DateSelector.LATEST_TRAINING_DAY):
        try:
            explicit_scope = resolve_dates(clause, now=now, scope=DateResolutionScope.OBSERVED)
        except InvalidDateError:
            return _clarify(ClarificationCode.INVALID_DATE)
        if explicit_scope:
            return _clarify(ClarificationCode.CONFLICTING_SCOPE)
        latest_intent = (
            CoachIntent.ANALYZE_ACTIVITY
            if selector is DateSelector.LATEST_ACTIVITY
            else CoachIntent.ANALYZE_DAY
        )
        return _make_component(latest_intent, clause, now, selector)

    if positive_change and has_plan_object and not _ADVICE_MODAL.search(normalized):
        return _make_component(CoachIntent.REQUEST_CHANGE, clause, now)

    try:
        dates_for_hint = resolve_dates(clause, now=now, scope=DateResolutionScope.OBSERVED)
    except InvalidDateError:
        return _clarify(ClarificationCode.INVALID_DATE)
    today = now.astimezone(_MADRID).date()
    retrospective_dates = any(day <= today for day in dates_for_hint)
    analysis_signal = _ANALYSIS_VERB.search(normalized) or (_RETROSPECTIVE_QUESTION.search(normalized) and retrospective_dates)
    if analysis_signal:
        if has_plan_object and any(day > today for day in dates_for_hint):
            return _make_component(CoachIntent.CONSULT_PLAN, clause, now)
        return _make_component(CoachIntent.ANALYZE_DAY, clause, now)
    if _PLAN_QUESTION.search(normalized) or re.search(r"\b(?:plan|sesion\s+prevista)\b", normalized):
        return _make_component(CoachIntent.CONSULT_PLAN, clause, now)
    if _RECOMMENDATION.search(normalized) or (_ADVICE_MODAL.search(normalized) and positive_change):
        return _make_component(CoachIntent.RECOMMEND_NEXT, clause, now)

    if dates_for_hint:
        return _clarify(ClarificationCode.UNSUPPORTED_PARAPHRASE)
    if normalized:
        return _clarify(ClarificationCode.UNSUPPORTED_PARAPHRASE)
    return _clarify(ClarificationCode.NO_SCOPE)


def resolve_intent(question: str, *, now: datetime) -> IntentResolution:
    """Resolve date scope and conservative permission signals for a question."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    normalized = _normalize(question)
    components = []
    for clause in _split_intent_clauses(normalized):
        component = _classify_clause(clause, now)
        if component is not None:
            components.append(component)
    if not components:
        components = [_clarify(ClarificationCode.NO_SCOPE)]
    return IntentResolution(tuple(components))


@dataclass(frozen=True)
class IntentComponent:
    intent: CoachIntent
    selector: DateSelector = DateSelector.BY_DATE
    observed_dates: tuple[date, ...] = ()
    advice_dates: tuple[date, ...] = ()
    clarification_code: ClarificationCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.intent, CoachIntent) or self.intent is CoachIntent.MIXED:
            raise ValueError("components require one atomic CoachIntent")
        if not isinstance(self.selector, DateSelector):
            raise TypeError("selector must be a DateSelector")
        if self.clarification_code is not None and not isinstance(self.clarification_code, ClarificationCode):
            raise TypeError("clarification_code must be a ClarificationCode")
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
