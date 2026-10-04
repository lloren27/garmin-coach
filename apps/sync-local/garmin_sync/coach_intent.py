"""Typed, deterministic intent-resolution contracts for coach requests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


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
