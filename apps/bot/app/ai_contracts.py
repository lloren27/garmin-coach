from __future__ import annotations

from datetime import date as Date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DecisionAction = Literal[
    "keep_plan",
    "modify_session",
    "rest",
    "recovery",
    "cross_training",
    "strength",
    "ask_user",
    "information_only",
]

Sport = Literal[
    "running",
    "cycling",
    "strength",
    "mobility",
    "recovery",
    "none",
]

Intensity = Literal[
    "rest",
    "recovery",
    "easy",
    "moderate",
    "tempo",
    "threshold",
    "vo2max",
    "hard",
    "very_easy",
    "Z1",
    "Z1-Z2",
    "Z2",
    "marathon_pace",
    "unknown",
]

DecisionSource = Literal["ollama", "training_plan", "deterministic"]

ResponseType = Literal[
    "analysis",
    "single_session",
    "weekly_plan",
    "recovery",
    "information",
]


class CoachDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DecisionAction
    source: DecisionSource = "ollama"
    sport: Sport = "none"
    component_index: int | None = Field(default=None, ge=0, le=6)

    date: Date | None = None
    session_type: str | None = Field(default=None, max_length=80)

    duration_min: int | None = Field(default=None, ge=0, le=600)
    duration_max_min: int | None = Field(default=None, ge=0, le=600)
    distance_km: float | None = Field(default=None, ge=0, le=350)

    intensity: Intensity = "unknown"

    target_pace: str | None = Field(default=None, max_length=40)
    target_power_w: int | None = Field(default=None, ge=0, le=1500)

    reason: str = Field(min_length=8, max_length=500)

    @model_validator(mode="after")
    def validate_decision(self) -> "CoachDecision":
        if self.source == 'deterministic' and self.action not in {'information_only', 'ask_user'}:
            raise ValueError('Deterministic decisions must be informational')
        if self.source == 'deterministic' and any(value is not None for value in (
            self.duration_min, self.duration_max_min, self.distance_km, self.target_pace, self.target_power_w)):
            raise ValueError('Deterministic decisions cannot carry a prescription')
        if self.source == 'deterministic' and (self.sport != 'none' or self.intensity != 'unknown' or self.session_type is not None):
            raise ValueError('Deterministic decisions cannot prescribe sport or intensity')
        if self.target_pace and self.target_pace.strip().lower() in {
            "easy",
            "moderate",
            "tempo",
            "threshold",
            "vo2max",
            "hard",
            "recovery",
        }:
            raise ValueError("target_pace cannot contain an intensity label")

        if (
            self.duration_max_min is not None
            and self.duration_min is None
        ):
            raise ValueError("Duration maximum requires a minimum")

        if (
            self.duration_min is not None
            and self.duration_max_min is not None
            and self.duration_max_min < self.duration_min
        ):
            raise ValueError("Duration maximum cannot be below minimum")

        if self.action == "rest":
            if self.distance_km not in (None, 0):
                raise ValueError("Rest cannot contain distance")

            if self.target_pace:
                raise ValueError("Rest cannot contain target pace")

            if self.target_power_w:
                raise ValueError("Rest cannot contain target power")

        return self


def validate_deterministic_output(payload, answer, status):
    """Reader-side contract: deterministic completion carries no plan authority."""
    response = CoachStructuredResponse.model_validate(payload)
    if (status != 'completed' or answer != response.answer or not response.decisions
            or response.change_proposal is not None
            or any(d.source != 'deterministic' for d in response.decisions)):
        raise ValueError('Invalid deterministic output')
    return response


class CoachEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "garmin",
        "strava",
        "zepp",
        "unknown",
        "wattwise",
        "training_plan",
        "profile",
        "lab_test",
        "checkin",
        "strength",
        "backend",
    ]

    fact: str = Field(min_length=3, max_length=250)
    date: str | None = Field(default=None, max_length=40)
    source_device: str | None = Field(default=None, max_length=160)
    source_records: list[dict[str, str | None]] = Field(default_factory=list, max_length=20)


class ChangeOperation(StrEnum):
    RESCHEDULE = 'RESCHEDULE'
    ADJUST_DURATION = 'ADJUST_DURATION'
    ADJUST_INTENSITY = 'ADJUST_INTENSITY'
    REPLACE_SESSION = 'REPLACE_SESSION'
    CANCEL_SESSION = 'CANCEL_SESSION'


class ProposedValues(BaseModel):
    model_config = ConfigDict(extra='forbid')
    date: Date | None = None
    sport: Sport | None = None
    session_type: str | None = Field(default=None, min_length=1, max_length=80)
    duration_min: int | None = Field(default=None, strict=True, ge=0, le=600)
    duration_max: int | None = Field(default=None, strict=True, ge=0, le=600)
    intensity: Intensity | None = None
    target_pace: str | None = Field(default=None, min_length=1, max_length=40)
    target_power_w: int | None = Field(default=None, strict=True, ge=0, le=1500)


class SessionChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation: ChangeOperation
    session_id: str = Field(min_length=1, max_length=100)
    proposed_values: ProposedValues
    reason: str = Field(min_length=8, max_length=500)


class StructuredChangeProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=8, max_length=500)
    component_index: int | None = Field(default=None, ge=0, le=6)
    confidence: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    evidence: list[CoachEvidence] = Field(max_length=4)
    changes: list[SessionChange] = Field(min_length=1, max_length=14)


class CoachStructuredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_type: ResponseType
    change_proposal: StructuredChangeProposal | None = None

    # Texto que seguimos mostrando al usuario.
    answer: str = Field(min_length=20, max_length=3500)

    # Decisiones interpretables por Python.
    decisions: list[CoachDecision] = Field(
        default_factory=list,
        max_length=7,
    )

    # Qué datos dice haber usado.
    evidence: list[CoachEvidence] = Field(
        default_factory=list,
        max_length=4,
    )

    warnings: list[str] = Field(
        default_factory=list,
        max_length=4,
    )

    missing_data: list[str] = Field(
        default_factory=list,
        max_length=4,
    )

    @model_validator(mode='after')
    def deterministic_is_read_only(self):
        if any(d.source == 'deterministic' for d in self.decisions):
            if self.change_proposal is not None or any(d.source != 'deterministic' for d in self.decisions):
                raise ValueError('Deterministic responses cannot mix sources or propose changes')
        return self
