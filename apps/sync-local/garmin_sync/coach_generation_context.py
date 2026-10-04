"""Immutable per-generation authority, detached from mutable worker context."""
from __future__ import annotations
from dataclasses import dataclass, field
from .provider_state import context_provider_states
from datetime import date, datetime
from types import MappingProxyType
from collections.abc import Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo
import math
from .coach_generation_contracts import CoachGenerationResponse
from .coach_intent import CoachIntent, IntentResolution, intent_enforcement_enabled, resolve_intent
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
    sport: str | None = None
    source_device: str | None = None
    source_records: tuple = ()
    collected_at: str | None = None
    freshness: str = 'unknown'
    duplicate_candidates: tuple = ()


@dataclass(frozen=True)
class ContextSnapshot:
    id: str
    now: datetime
    sessions: Mapping
    evidence: Mapping
    intent: IntentResolution
    proposal_allowed: bool
    proposal_sources: tuple[str, ...]
    freshness: str
    plan: Mapping
    provider_status: Mapping = field(default_factory=dict)

    def public_context(self):
        components = [{
            'intent': item.intent.value,
            'selector': item.selector.value,
            'observed_dates': [day.isoformat() for day in item.observed_dates],
            'advice_dates': [day.isoformat() for day in item.advice_dates],
            'clarification_code': item.clarification_code.value if item.clarification_code else None,
        } for item in self.intent.components]
        scoped_dates = {day.isoformat() for day in (*self.intent.observed_dates, *self.intent.advice_dates)}
        return {'schema_version': '1', 'context_snapshot_id': self.id,
                'current_time': self.now.isoformat(),
                'intent': {'primary_intent': self.intent.primary_intent.value, 'components': components},
                'observed_dates': [day.isoformat() for day in self.intent.observed_dates],
                'advice_dates': [day.isoformat() for day in self.intent.advice_dates],
                'available_sessions': [thaw(s) for s in self.sessions.values()
                    if s.get('status') in (None, 'planned') and s.get('date') in scoped_dates],
                'available_evidence': [{'id': e.id, 'kind': e.kind, 'source': e.source,
                    'date': e.date, 'sport': e.sport, 'facts': thaw(e.facts),
                    'source_device': e.source_device, 'source_records': thaw(e.source_records),
                    'duplicate_candidates': thaw(e.duplicate_candidates),
                    'collected_at': e.collected_at, 'freshness': e.freshness} for e in self.evidence.values()],
                'provider_status': thaw(self.provider_status),
                'change_proposal_allowed_now': self.proposal_allowed,
                'proposal_evidence_sources': list(self.proposal_sources), 'freshness': self.freshness}


# Numeric fields have explicit units/meaning; unknown fields and prose are not facts.
FACT_FIELDS = frozenset({'distance_km', 'duration_s', 'duration_min', 'duration_max', 'avg_hr',
    'max_hr', 'avg_power', 'target_power_w', 'total_minutes', 'score', 'resting_hr', 'steps',
    'atl', 'ctl', 'tsb', 'trimp', 'sport_load', 'recovery_factor', 'stress_avg', 'deep_minutes', 'rem_minutes', 'light_minutes', 'awake_minutes', 'age', 'weight_kg',
    'height_cm', 'ftp', 'ftp_w', 'vo2max', 'km_28d', 'km_56d', 'km_7d', 'runs_count_28d',
    'avg_weekly_km_8w', 'tss', 'if', 'vi', 'pain', 'soreness',
    'intensity_factor', 'variability_index', 'moving_min', 'avg_power_w', 'vt1_hr', 'vt2_hr',
    'lactate_hr', 'sessions_7d', 'sessions_28d', 'sets_7d', 'volume_kg_7d', 'load_score_7d',
    'lower_sets_7d', 'hard_lower_sets_7d', 'today_sessions', 'today_sets', 'today_load_score',
    'acute_chronic_ratio', 'load_ratio', 'acute_load', 'sleep_seconds', 'deep_seconds',
    'light_seconds', 'rem_seconds', 'awake_seconds', 'last_night_avg', 'weekly_avg',
    'baseline_low', 'baseline_high', 'charged', 'drained', 'current'})
SESSION_FIELDS = frozenset({'id', 'date', 'status', 'sport', 'session_type', 'intensity',
    'duration_min', 'duration_max', 'distance_km', 'target_pace', 'target_power_w', 'optional', 'completed_activity_id', 'owner_id', 'training_plan_id'})


def _facts(row):
    return {k: v for k, v in row.items() if k in FACT_FIELDS and isinstance(v, (int, float))
            and (not isinstance(v, bool) or k in {'pain', 'soreness'}) and math.isfinite(v)}


def _date(value):
    try:
        text = str(value)
        if 'T' in text:
            instant = datetime.fromisoformat(text.replace('Z', '+00:00'))
            if instant.tzinfo is not None:
                return instant.astimezone(ZoneInfo('Europe/Madrid')).date().isoformat()
        return date.fromisoformat(text[:10]).isoformat()
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
        if len(identifier) > 100 or not _date(row.get('date')):
            raise CoachValidationError([ValidationIssue(Code.INVALID_CONTEXT, Phase.RESOLUTION, 'sessions', Severity.FATAL)])
        if identifier in sessions:
            raise CoachValidationError([ValidationIssue(Code.INVALID_CONTEXT, Phase.RESOLUTION, 'sessions', Severity.FATAL)])
        sessions[identifier] = {k: v for k, v in row.items() if k in SESSION_FIELDS}
        sessions[identifier]['has_plan_detail'] = bool(row.get('description'))
    def add(kind, row, index, source, stamp=None):
        if not isinstance(row, Mapping) or row.get('status') in ('unavailable', 'error'): return
        row = dict(row)
        if kind == 'activity' and 'km' in row:
            row['distance_km'] = row['km']
        if kind == 'wellness' and 'value' in row:
            row[str(index)] = row.pop('value')
        if kind == 'checkin':
            for field in ('pain', 'soreness'):
                value = row.get(field)
                if isinstance(value, str) and value.strip():
                    row[field] = value.strip().lower() not in {'no', 'sin dolor', 'sin molestias', 'ninguno', 'ninguna'}
        facts = _facts(row)
        if not facts: return
        origin = row.get('source', source)
        if origin not in {'garmin', 'zepp', 'strava', 'unknown', 'backend', 'profile', 'training_plan', 'checkin', 'strength', 'wattwise', 'lab_test'}:
            origin = 'unknown'
        key = f'{kind}:{row.get("id") or index}'
        # IDs repeated by separate sources must not silently replace a fact.
        if key in evidence or len(key) > 160:
            raise CoachValidationError([ValidationIssue(Code.INVALID_CONTEXT, Phase.REFERENCE, 'evidence', Severity.FATAL)])
        sport = row.get('sport')
        if sport not in ('running', 'cycling', 'strength', 'mobility', 'swimming', 'walking'):
            sport = None
        observed = _date(row.get('date') or row.get('started_at') or row.get('end') or row.get('start') or row.get('created_at') or row.get('observed_at') or row.get('reference_date') or row.get('effective_date') or stamp)
        freshness = ('current' if observed == now.date().isoformat() else 'stale') if observed else 'unknown'
        origins = row.get('source_records') or ([dict(source=origin,
            source_activity_id=str(row.get('source_activity_id') or row.get('id') or index),
            source_device=row.get('source_device'))] if kind == 'activity' else [])
        evidence[key] = EvidenceRecord(key, kind, origin, observed, freeze(facts), sport,
            row.get('source_device'), freeze(origins), row.get('collected_at') or extra.get('generated_at'), freshness,
            freeze(row.get('duplicate_candidates') or []))
    for i, row in enumerate(extra.get('recent_activities') or []): add('activity', row, i, 'unknown')
    wellness = extra.get('wellness') or {}
    effective = wellness.get('effective', wellness)
    if isinstance(effective, Mapping):
        for key, row in effective.items():
            if isinstance(row, Mapping):
                metric = dict(row)
                if key == 'stress' and 'avg' in metric: metric['stress_avg'] = metric.pop('avg')
                add('wellness', metric, key, 'garmin', effective.get('date'))
            elif isinstance(row, (int, float)): add('wellness', {key: row}, key, 'garmin')
    for kind, field, source in [('profile', 'profile', 'profile'), ('checkin', 'checkins', 'checkin'),
        ('lab_test', 'applied_lab_tests', 'lab_test'), ('strength', 'strength_manual', 'strength'),
        ('strength', 'strength_manual_current', 'strength'), ('wattwise', 'wattwise_snapshot', 'wattwise'),
        ('wattwise', 'wattwise_live', 'wattwise'), ('backend', 'summary', 'backend'), ('history', 'history', 'garmin'), ('physiology', 'physiology', 'garmin')]:
        rows = extra.get(field) or []
        if isinstance(rows, Mapping): rows = [rows]
        def walk(row, index, stamp=None, depth=0):
            if not isinstance(row, Mapping) or depth > 4 or row.get('status') in ('unavailable', 'error'):
                return
            stamp = row.get('date') or row.get('created_at') or row.get('generated_at') or row.get('reference_date') or row.get('effective_date') or row.get('observed_at') or stamp
            add(kind, row, index, source, stamp)
            # Only known containers; notes and arbitrary keys are not traversed.
            for key in ('summary', 'metrics', 'payload', 'profile', 'checkin', 'result', 'results',
                        'thresholds', 'physiology', 'today', 'week', 'fatigue', 'running_load', 'sessions',
                        'extracted', 'recent_activities', 'cycling_power_metrics', 'fitness_signature', 'latest_load'):
                nested = row.get(key)
                if isinstance(nested, Mapping): walk(nested, f'{index}:{key}', stamp, depth+1)
                elif isinstance(nested, (list, tuple)):
                    for j, item in enumerate(nested): walk(item, f'{index}:{key}:{j}', stamp, depth+1)
        for i, row in enumerate(rows if isinstance(rows, (list, tuple)) else []): walk(row, f'{field}:{i}')
    for key, row in sessions.items(): add('plan', row, key, 'training_plan', row.get('date'))
    intent = resolve_intent(question, now=now)
    provider_status = context_provider_states(extra, now)
    freshness = (extra.get('data_freshness') or {}).get('status', 'unknown')
    if any(e.kind == 'wellness' and e.freshness != 'current' for e in evidence.values()):
        freshness = 'partial'
    if any(s['state'] in {'provider_error', 'partial', 'stale'} for s in provider_status.values()):
        freshness = 'partial'
    return ContextSnapshot('ctx_' + uuid4().hex, now, freeze(sessions), freeze(evidence), intent,
        extra.get('change_proposal_allowed_now') is True, tuple(extra.get('proposal_evidence_sources') or []),
        freshness, freeze(extra.get('training_plan') or {}), freeze(provider_status))


def generation_schema(snapshot: ContextSnapshot, *, enforce_intent: bool | None = None) -> dict:
    if enforce_intent is None:
        enforce_intent = intent_enforcement_enabled()
    schema = CoachGenerationResponse.model_json_schema()
    schema['properties']['context_snapshot_id']['const'] = snapshot.id
    has_change_component = any(item.intent is CoachIntent.REQUEST_CHANGE for item in snapshot.intent.components)
    if not snapshot.proposal_allowed or (enforce_intent and not has_change_component):
        schema['properties']['change_proposal'] = {'type': 'null', 'default': None}
    refs = list(snapshot.evidence)
    for definition in [schema, *schema.get('$defs', {}).values()]:
        properties = definition.get('properties', {})
        if 'evidence_refs' in properties:
            if refs:
                properties['evidence_refs']['items']['enum'] = refs
            else:
                properties['evidence_refs']['maxItems'] = 0
    scoped_dates = ({day.isoformat() for day in snapshot.intent.advice_dates} if enforce_intent else
                    {day.isoformat() for day in (*snapshot.intent.observed_dates, *snapshot.intent.advice_dates)})
    sessions = [key for key, s in snapshot.sessions.items() if s.get('date') in scoped_dates
                and s.get('status') in (None, 'planned') and not s.get('completed_activity_id')]
    if sessions:
        schema['$defs']['KeepPlanDecision']['properties']['session_id']['enum'] = sessions
    else:
        items = schema['properties']['decisions']['items']
        items['oneOf'] = [v for v in items['oneOf'] if v.get('$ref') != '#/$defs/KeepPlanDecision']
        items['discriminator']['mapping'].pop('keep_plan', None)
    if enforce_intent:
        allowed_by_intent = {
            CoachIntent.ANALYZE_ACTIVITY: ['ask_user', 'information_only'],
            CoachIntent.ANALYZE_DAY: ['ask_user', 'information_only'],
            CoachIntent.CONSULT_PLAN: ['ask_user', 'information_only'],
            CoachIntent.RECOMMEND_NEXT: ['ask_user', 'information_only'],
            CoachIntent.REQUEST_CHANGE: ['ask_user', 'information_only'],
            CoachIntent.CLARIFY: ['ask_user', 'information_only'],
        }
        session_dates = {session.get('date') for session in snapshot.sessions.values()
                         if session.get('status') in (None, 'planned') and not session.get('completed_activity_id')}
        for index, component in enumerate(snapshot.intent.components):
            actions = list(allowed_by_intent[component.intent])
            component_advice = {day.isoformat() for day in component.advice_dates}
            component_sessions = {key for key, session in snapshot.sessions.items()
                                  if session.get('date') in component_advice
                                  and session.get('status') in (None, 'planned')
                                  and not session.get('completed_activity_id')}
            if component.intent is CoachIntent.CONSULT_PLAN and component_advice and component_sessions:
                actions.append('keep_plan')
            if component.intent is CoachIntent.RECOMMEND_NEXT and component.advice_dates:
                actions.extend(['rest', 'modify_session', 'recovery', 'cross_training', 'strength'])
            dates = sorted(day.isoformat() for day in (*component.observed_dates, *component.advice_dates))
            item_schema = schema['properties']['decisions']['items']
            condition = {'if': {'properties': {'component_index': {'const': index}},
                                'required': ['component_index']},
                         'then': {'properties': {'action': {'enum': actions}},
                                  'required': ['component_index']}}
            if dates:
                condition['then']['properties']['date'] = {'type': 'string', 'format': 'date', 'enum': dates}
                condition['then']['required'].append('date')
            if 'keep_plan' in actions:
                plan_dates = sorted(component_advice.intersection(session_dates))
                condition['then']['properties']['date']['enum'] = plan_dates
                condition['then'].setdefault('allOf', []).append({
                    'if': {'properties': {'action': {'const': 'keep_plan'}}, 'required': ['action']},
                    'then': {'properties': {'session_id': {'enum': sorted(component_sessions)}}},
                })
            item_schema.setdefault('allOf', []).append(condition)
        for definition in schema['$defs'].values():
            properties = definition.get('properties', {})
            if 'action' in properties and 'component_index' in properties:
                properties['component_index']['enum'] = list(range(len(snapshot.intent.components)))
                definition.setdefault('required', []).append('component_index')
        if snapshot.proposal_allowed and has_change_component:
            proposal_component_indexes = [index for index, item in enumerate(snapshot.intent.components)
                                          if item.intent is CoachIntent.REQUEST_CHANGE]
            proposal_schema = schema['$defs']['GenerationChangeProposal']
            proposal_schema['properties']['component_index']['enum'] = proposal_component_indexes
            proposal_schema.setdefault('required', []).append('component_index')
    return schema
