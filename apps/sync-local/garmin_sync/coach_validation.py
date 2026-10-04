"""Typed, privacy-safe diagnostics for the internal generation boundary."""
from dataclasses import dataclass
from enum import StrEnum


class ValidationPhase(StrEnum):
    PARSING = 'parsing'
    STRUCTURE = 'structure'
    REFERENCE = 'reference'
    RESOLUTION = 'resolution'
    DOMAIN = 'domain'
    AUTHORIZATION = 'authorization'
    RENDERING = 'rendering'


class ValidationSeverity(StrEnum):
    NORMALIZABLE = 'normalizable'
    RETRY_REQUIRED = 'retry_required'
    FATAL = 'fatal'


class ValidationCode(StrEnum):
    NORMALIZED_ALIAS = 'NORMALIZED_ALIAS'
    REST_INVALID_INTENSITY = 'REST_INVALID_INTENSITY'
    REST_INVALID_TARGET = 'REST_INVALID_TARGET'
    INVALID_PACE_FORMAT = 'INVALID_PACE_FORMAT'
    UNKNOWN_EVIDENCE_REF = 'UNKNOWN_EVIDENCE_REF'
    UNKNOWN_PLAN_SESSION = 'UNKNOWN_PLAN_SESSION'
    PLAN_DATE_MISMATCH = 'PLAN_DATE_MISMATCH'
    INTENT_MISMATCH = 'INTENT_MISMATCH'
    INVALID_DURATION_RANGE = 'INVALID_DURATION_RANGE'
    UNAUTHORIZED_CHANGE_PROPOSAL = 'UNAUTHORIZED_CHANGE_PROPOSAL'
    INVALID_STRUCTURED_OUTPUT = 'INVALID_STRUCTURED_OUTPUT'
    UNSUPPORTED_EXPLANATION_CODE = 'UNSUPPORTED_EXPLANATION_CODE'
    UNSUPPORTED_SCHEMA_VERSION = 'UNSUPPORTED_SCHEMA_VERSION'
    CONTEXT_SNAPSHOT_MISMATCH = 'CONTEXT_SNAPSHOT_MISMATCH'
    INVALID_CONTEXT = 'INVALID_CONTEXT'
    INVALID_DECISION = 'INVALID_DECISION'
    RENDERING_FAILED = 'RENDERING_FAILED'


@dataclass(frozen=True)
class RepairHint:
    rule: str | None = None
    allowed_values: tuple[str, ...] = ()
    allowed_refs: tuple[str, ...] = ()
    expected_value: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    code: ValidationCode
    phase: ValidationPhase
    path: str
    severity: ValidationSeverity = ValidationSeverity.RETRY_REQUIRED
    received: str | None = None
    repair_hint: RepairHint | None = None


class CoachValidationError(ValueError):
    def __init__(self, issues):
        self.issues = tuple(issues)
        # Never stringify model input, health facts, or Pydantic error messages.
        super().__init__(', '.join(str(issue.code) for issue in self.issues))

    @property
    def fatal(self):
        return any(i.severity == ValidationSeverity.FATAL for i in self.issues)
