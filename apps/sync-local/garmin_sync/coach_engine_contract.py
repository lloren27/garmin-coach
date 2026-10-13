"""Versioned engine requirements shared by the API/worker contract."""

from __future__ import annotations

ENGINE_REQUIREMENT_UNAVAILABLE = "COACH_ENGINE_REQUIREMENT_UNAVAILABLE"
ENGINE_REQUIREMENT_UNSUPPORTED = "COACH_ENGINE_REQUIREMENT_UNSUPPORTED"


def required_engine_error(job: dict, *, v3_enabled: bool) -> str | None:
    """Return a stable failure code instead of silently degrading an engine."""
    required = job.get("required_engine")
    if required not in (None, "v3"):
        return ENGINE_REQUIREMENT_UNSUPPORTED
    if required == "v3" and not v3_enabled:
        return ENGINE_REQUIREMENT_UNAVAILABLE
    return None
