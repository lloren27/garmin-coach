from __future__ import annotations

from datetime import date as Date
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
    "unknown",
]

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
    sport: Sport = "none"

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


class CoachEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "garmin",
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


class CoachStructuredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_type: ResponseType

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
