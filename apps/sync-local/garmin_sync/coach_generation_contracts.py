"""Internal Ollama contract. Public/persisted contracts intentionally stay unchanged."""
from __future__ import annotations

import copy
import json
from datetime import date as Date
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from .ai_contracts import ChangeOperation, ProposedValues, ResponseType
from .coach_validation import (CoachValidationError, RepairHint, ValidationCode as Code,
                               ValidationIssue, ValidationPhase as Phase, ValidationSeverity as Severity)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


Ref = Annotated[str, Field(min_length=1, max_length=160)]
Refs = Annotated[list[Ref], Field(max_length=4)]
ConclusionCode = Literal['PLAN_SESSION', 'RECOVERY_RECOMMENDATION', 'OBSERVED_ACTIVITY',
    'OBSERVED_WELLNESS', 'DATA_STALE', 'DATA_MISSING', 'NEEDS_CLARIFICATION',
    'CHANGE_REQUESTED', 'ANALYSIS_LIMITED']


class Conclusion(StrictModel):
    code: ConclusionCode
    evidence_refs: Refs = Field(default_factory=list)


class DecisionBase(StrictModel):
    evidence_refs: Refs = Field(default_factory=list)


class RestDecision(DecisionBase):
    action: Literal['rest']
    intensity: Literal['rest', 'recovery'] = 'rest'
    date: Date | None = None
    target_pace: None = None
    target_power_w: None = None
    distance_km: Literal[0] | None = None


class KeepPlanDecision(DecisionBase):
    action: Literal['keep_plan']
    session_id: Ref


class ActivityDecision(DecisionBase):
    sport: Literal['running', 'cycling', 'strength', 'mobility', 'recovery']
    date: Date | None = None
    session_type: str | None = Field(default=None, min_length=1, max_length=80)
    intensity: Literal['recovery', 'easy', 'moderate', 'tempo', 'threshold', 'vo2max',
                       'hard', 'very_easy', 'Z1', 'Z1-Z2', 'Z2', 'marathon_pace']
    duration_min: int = Field(strict=True, ge=1, le=600)
    duration_max_min: int | None = Field(default=None, strict=True, ge=1, le=600)
    distance_km: float | None = Field(default=None, ge=0, le=350, allow_inf_nan=False)
    target_pace: str | None = Field(default=None, max_length=40,
        pattern=r'^\d{1,2}:[0-5]\d(?:\s*[-–]\s*\d{1,2}:[0-5]\d)?(?:\s*min/km)?$')
    target_power_w: int | None = Field(default=None, strict=True, ge=1, le=1500)

    @model_validator(mode='after')
    def validate_targets(self):
        if self.duration_max_min is not None and self.duration_max_min < self.duration_min:
            raise ValueError('INVALID_DURATION_RANGE')
        if self.target_pace is not None and self.sport != 'running':
            raise ValueError('INVALID_PACE_FORMAT')
        if self.target_power_w is not None and self.sport != 'cycling':
            raise ValueError('INVALID_DECISION')
        return self


class ModifyDecision(ActivityDecision):
    action: Literal['modify_session']


class RecoveryDecision(ActivityDecision):
    action: Literal['recovery']
    intensity: Literal['recovery', 'very_easy', 'Z1'] = 'recovery'


class CrossTrainingDecision(ActivityDecision):
    action: Literal['cross_training']


class StrengthDecision(ActivityDecision):
    action: Literal['strength']
    sport: Literal['strength'] = 'strength'


class AskDecision(DecisionBase):
    action: Literal['ask_user']
    code: Literal['DATA_MISSING', 'NEEDS_CLARIFICATION'] = 'NEEDS_CLARIFICATION'


class InformationDecision(DecisionBase):
    action: Literal['information_only']
    code: Literal['ANALYSIS_LIMITED'] = 'ANALYSIS_LIMITED'


GenerationDecision = Annotated[RestDecision | KeepPlanDecision | ModifyDecision |
    RecoveryDecision | CrossTrainingDecision | StrengthDecision | AskDecision | InformationDecision,
    Field(discriminator='action')]


class GenerationChange(StrictModel):
    operation: ChangeOperation
    session_id: Ref
    proposed_values: ProposedValues
    code: Literal['CHANGE_REQUESTED'] = 'CHANGE_REQUESTED'


class GenerationChangeProposal(StrictModel):
    code: Literal['CHANGE_REQUESTED'] = 'CHANGE_REQUESTED'
    confidence: float = Field(strict=True, ge=0, le=1, allow_inf_nan=False)
    evidence_refs: Refs = Field(default_factory=list)
    changes: list[GenerationChange] = Field(min_length=1, max_length=14)


class CoachGenerationResponse(StrictModel):
    schema_version: Literal['1']
    context_snapshot_id: Ref
    response_type: ResponseType
    decisions: list[GenerationDecision] = Field(max_length=7)
    conclusions: list[Conclusion] = Field(max_length=4)
    evidence_refs: Refs
    change_proposal: GenerationChangeProposal | None = None


def normalize_generation(payload: dict) -> tuple[dict, list[ValidationIssue]]:
    normalized = copy.deepcopy(payload)
    issues = []
    actions = {'rest', 'keep_plan', 'modify_session', 'recovery', 'cross_training', 'strength', 'ask_user', 'information_only'}
    intensities = {'rest', 'recovery', 'easy', 'moderate', 'tempo', 'threshold', 'vo2max', 'hard',
                   'very_easy', 'marathon_pace', 'unknown', 'Z1', 'Z1-Z2', 'Z2'}
    rows = normalized.get('decisions')
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        for key, allowed in (('action', actions), ('intensity', intensities)):
            value = row.get(key)
            if not isinstance(value, str):
                continue
            aliases = {v.lower(): v for v in allowed}
            if key == 'intensity':
                aliases.update({'easy run': 'easy', 'recovery_run': 'recovery'})
            replacement = aliases.get(value.strip().lower())
            if replacement is not None and replacement != value:
                row[key] = replacement
                issues.append(ValidationIssue(Code.NORMALIZED_ALIAS, Phase.STRUCTURE,
                    f'decisions[{index}].{key}', Severity.NORMALIZABLE))
    return normalized, issues


def parse_generation(content: str) -> CoachGenerationResponse:
    try:
        raw = json.loads(content)
    except (ValueError, TypeError):
        raise CoachValidationError([ValidationIssue(Code.INVALID_STRUCTURED_OUTPUT, Phase.PARSING, '$')]) from None
    if not isinstance(raw, dict):
        raise CoachValidationError([ValidationIssue(Code.INVALID_STRUCTURED_OUTPUT, Phase.STRUCTURE, '$')])
    normalized, _ = normalize_generation(raw)
    try:
        return CoachGenerationResponse.model_validate(normalized)
    except ValidationError as exc:
        issues = []
        for err in exc.errors(include_input=False, include_url=False, include_context=False):
            loc = err['loc']
            code = Code.INVALID_STRUCTURED_OUTPUT
            hint = None
            if 'schema_version' in loc:
                code, hint = Code.UNSUPPORTED_SCHEMA_VERSION, RepairHint(expected_value='1')
            elif 'rest' in loc:
                code = Code.REST_INVALID_INTENSITY if 'intensity' in loc else Code.REST_INVALID_TARGET
                hint = RepairHint(rule='Rest cannot prescribe training intensity or targets.', allowed_values=('rest', 'recovery'))
            elif 'target_pace' in loc or 'INVALID_PACE_FORMAT' in err['msg']:
                code = Code.INVALID_PACE_FORMAT
            elif 'INVALID_DURATION_RANGE' in err['msg']:
                code = Code.INVALID_DURATION_RANGE
            elif 'conclusions' in loc and 'code' in loc:
                code = Code.UNSUPPORTED_EXPLANATION_CODE
            # Locations may contain attacker-controlled extra keys; only use known fields.
            known = {'decisions', 'conclusions', 'schema_version', 'context_snapshot_id', 'intensity',
                     'target_pace', 'target_power_w', 'distance_km', 'duration_min', 'duration_max_min',
                     'action', 'code', 'date', 'evidence_refs', 'change_proposal', 'session_id'}
            path = ''
            for part in loc:
                if isinstance(part, int): path += f'[{part}]'
                elif part in known: path += ('.' if path else '') + part
            issues.append(ValidationIssue(code, Phase.STRUCTURE, path or '$', repair_hint=hint))
        raise CoachValidationError(issues) from None
