from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from zoneinfo import ZoneInfo


class ProviderStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    DISABLED = "disabled"
    AUTH_ERROR = "auth_error"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"
    INVALID_DATA = "invalid_data"


@dataclass(frozen=True)
class NormalizedSleep:
    start: str
    end: str
    total_minutes: int
    source_id: str | None = None
    deep_minutes: int | None = None
    light_minutes: int | None = None
    rem_minutes: int | None = None
    awake_minutes: int | None = None
    score: int | None = None
    resting_hr: int | None = None
    source: str = "zepp"

    def identity(self) -> tuple[str, ...]:
        if self.source_id:
            return ("id", self.source_id)
        return ("times", self.start, self.end)

    def to_dict(self) -> dict[str, Any]:
        values = {
            "source_id": self.source_id,
            "start": self.start,
            "end": self.end,
            "total_minutes": self.total_minutes,
            "deep_minutes": self.deep_minutes,
            "light_minutes": self.light_minutes,
            "rem_minutes": self.rem_minutes,
            "awake_minutes": self.awake_minutes,
            "score": self.score,
            "resting_hr": self.resting_hr,
            "source": self.source,
        }
        return {key: value for key, value in values.items() if value is not None}


def deduplicate_sleep_sessions(sessions: list[NormalizedSleep]) -> list[NormalizedSleep]:
    unique: list[NormalizedSleep] = []
    seen: set[tuple[str, ...]] = set()
    for session in sessions:
        identity = session.identity()
        if identity not in seen:
            seen.add(identity)
            unique.append(session)
    return unique


@dataclass(frozen=True)
class NormalizedWellness:
    sleep: NormalizedSleep | None = None
    resting_hr: dict[str, Any] | None = None
    steps: dict[str, Any] | None = None
    stress: dict[str, Any] | None = None
    training_load: dict[str, Any] | None = None
    trimp: dict[str, Any] | None = None
    sport_load: dict[str, Any] | None = None
    vo2max_observations: list[dict[str, Any]] = field(default_factory=list)

    def wellness_date(self, timezone_name: str) -> str | None:
        if not self.sleep:
            return None
        end = datetime.fromisoformat(self.sleep.end.replace("Z", "+00:00"))
        if end.tzinfo is None:
            raise ValueError("Sleep end timestamp must include an offset")
        return end.astimezone(ZoneInfo(timezone_name)).date().isoformat()

    def to_dict(self) -> dict[str, Any]:
        values = {
            "sleep": self.sleep.to_dict() if self.sleep else None,
            "resting_hr": self.resting_hr,
            "steps": self.steps,
            "stress": self.stress,
            "training_load": self.training_load,
            "trimp": self.trimp,
            "sport_load": self.sport_load,
            "vo2max_observations": self.vo2max_observations,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True)
class ProviderDayResult:
    date: str
    status: Literal["ok", "error"]
    data: NormalizedWellness | None = None
    error_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        values = {
            "date": self.date,
            "status": self.status,
            "data": self.data.to_dict() if self.data else None,
            "error_kind": self.error_kind,
        }
        return {key: value for key, value in values.items() if value is not None}
