"""Immutable per-generation authority, detached from mutable worker context."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from types import MappingProxyType
from collections.abc import Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo
import math
import re
import unicodedata
from .coach_generation_contracts import CoachGenerationResponse
from .coach_validation import CoachValidationError, ValidationIssue, ValidationCode as Code, ValidationPhase as Phase, ValidationSeverity as Severity


def freeze(value):
    if isinstance(value, Mapping): return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)): return tuple(freeze(v) for v in value)
    return value


def thaw(value):
    if isinstance(value, Mapping): return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple): return [thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    kind: str
    source: str
    date: str | None
    facts: Mapping


@dataclass(frozen=True)
class ContextSnapshot:
    id: str
    now: datetime
    sessions: Mapping
    evidence: Mapping
    target_dates: tuple[str, ...]
    proposal_allowed: bool
    proposal_sources: tuple[str, ...]
    freshness: str

    def public_context(self):
        return {'schema_version': '1', 'context_snapshot_id': self.id,
                'current_time': self.now.isoformat(), 'target_dates': list(self.target_dates),
                'available_sessions': [thaw(s) for s in self.sessions.values()
                    if s.get('status') in (None, 'planned') and s.get('date') in self.target_dates],
                'available_evidence': [{'id': e.id, 'kind': e.kind, 'source': e.source,
                    'date': e.date, 'facts': thaw(e.facts)} for e in self.evidence.values()],
                'change_proposal_allowed_now': self.proposal_allowed,
                'proposal_evidence_sources': list(self.proposal_sources), 'freshness': self.freshness}


# Numeric fields have explicit units/meaning; unknown fields and prose are not facts.
FACT_FIELDS = frozenset({'distance_km', 'duration_s', 'duration_min', 'duration_max', 'avg_hr',
    'max_hr', 'avg_power', 'target_power_w', 'total_minutes', 'score', 'resting_hr', 'steps',
    'value', 'deep_minutes', 'rem_minutes', 'light_minutes', 'awake_minutes', 'age', 'weight_kg',
    'height_cm', 'ftp', 'ftp_w', 'vo2max', 'km_28d', 'km_56d', 'km_7d', 'runs_count_28d',
    'avg_weekly_km_8w', 'tss', 'if', 'vi', 'pain', 'soreness'})
SESSION_FIELDS = frozenset({'id', 'date', 'status', 'sport', 'session_type', 'intensity',
    'duration_min', 'duration_max', 'distance_km', 'target_pace', 'target_power_w', 'completed_activity_id'})


def _facts(row):
    return {k: v for k, v in row.items() if k in FACT_FIELDS and isinstance(v, (int, float))
            and not isinstance(v, bool) and math.isfinite(v)}


def _date(value):
    try: return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError: return None


def build_snapshot(question: str, compact: dict, *, now: datetime) -> ContextSnapshot:
    if now.tzinfo is None:
        raise CoachValidationError([ValidationIssue(Code.INVALID_CONTEXT, Phase.RESOLUTION, '$', Severity.FATAL)])
    now = now.astimezone(ZoneInfo('Europe/Madrid'))
    extra = compact.get('extra_context') or {}
    sessions, evidence = {}, {}
    for row in (extra.get('training_plan') or {}).get('sessions') or []:
        identifier = row.get('id')
        if not isinstance(identifier, str) or not identifier: continue
        if identifier in sessions:
            raise CoachValidationError([ValidationIssue(Code.INVALID_CONTEXT, Phase.RESOLUTION, 'sessions', Severity.FATAL)])
        sessions[identifier] = {k: v for k, v in row.items() if k in SESSION_FIELDS}
    def add(kind, row, index, source, stamp=None):
        if not isinstance(row, Mapping) or row.get('status') in ('unavailable', 'error'): return
        row = dict(row)
        if kind == 'activity' and 'km' in row:
            row['distance_km'] = row['km']
        if kind == 'wellness' and 'value' in row:
            row[str(index)] = row.pop('value')
        facts = _facts(row)
        if not facts: return
        origin = row.get('source', source)
        if origin not in {'garmin', 'zepp', 'backend', 'profile', 'training_plan', 'checkin', 'strength', 'wattwise', 'lab_test'}:
            origin = source
        key = f'{kind}:{row.get("id") or index}'
        # IDs repeated by separate sources must not silently replace a fact.
        if key in evidence:
            key = f'{key}:{index}'
        evidence[key] = EvidenceRecord(key, kind, origin,
            _date(row.get('date') or row.get('started_at') or row.get('start') or row.get('created_at') or stamp), freeze(facts))
    for i, row in enumerate(extra.get('recent_activities') or []): add('activity', row, i, 'garmin')
    wellness = extra.get('wellness') or {}
    effective = wellness.get('effective', wellness)
    if isinstance(effective, Mapping):
        for key, row in effective.items():
            if isinstance(row, Mapping): add('wellness', row, key, 'garmin')
            elif isinstance(row, (int, float)): add('wellness', {key: row}, key, 'garmin')
    for kind, field, source in [('profile', 'profile', 'profile'), ('checkin', 'checkins', 'checkin'),
        ('lab_test', 'applied_lab_tests', 'lab_test'), ('strength', 'strength_manual', 'strength'),
        ('strength', 'strength_manual_current', 'strength'), ('wattwise', 'wattwise_snapshot', 'wattwise'),
        ('wattwise', 'wattwise_live', 'wattwise'), ('backend', 'summary', 'backend')]:
        rows = extra.get(field) or []
        if isinstance(rows, Mapping): rows = [rows]
        for i, row in enumerate(rows if isinstance(rows, (list, tuple)) else []): add(kind, row, f'{field}:{i}', source)
    for key, row in sessions.items(): add('plan', row, key, 'training_plan', row.get('date'))
    normalized = ''.join(c for c in unicodedata.normalize('NFKD', question.lower()) if not unicodedata.combining(c))
    today = now.date()
    dates = ()
    explicit = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', normalized)
    if explicit:
        dates = tuple(dict.fromkeys(d for d in map(_date, explicit) if d))
    elif re.search(r'\b(?:siete|7) dias\b', normalized):
        dates = tuple((today + timedelta(days=i)).isoformat() for i in range(7))
    elif 'semana' in normalized:
        start = today + timedelta(days=7 - today.weekday()) if 'proxima' in normalized or 'que viene' in normalized else today
        end = start + timedelta(days=6 - start.weekday())
        dates = tuple((start + timedelta(days=i)).isoformat() for i in range((end-start).days + 1))
    elif re.search(r'\bmanana\b', normalized): dates = ((today + timedelta(days=1)).isoformat(),)
    elif re.search(r'\bhoy\b', normalized): dates = (today.isoformat(),)
    elif 'proximo' in normalized:
        candidates = sorted(s['date'] for s in sessions.values() if s.get('status') in (None, 'planned')
            and _date(s.get('date')) and s['date'] >= today.isoformat())
        if candidates: dates = (candidates[0],)
    return ContextSnapshot('ctx_' + uuid4().hex, now, freeze(sessions), freeze(evidence), dates,
        extra.get('change_proposal_allowed_now') is True, tuple(extra.get('proposal_evidence_sources') or []),
        (extra.get('data_freshness') or {}).get('status', 'unknown'))


def generation_schema(snapshot: ContextSnapshot) -> dict:
    schema = CoachGenerationResponse.model_json_schema()
    schema['properties']['context_snapshot_id']['const'] = snapshot.id
    if not snapshot.proposal_allowed: schema['properties']['change_proposal'] = {'type': 'null', 'default': None}
    return schema
