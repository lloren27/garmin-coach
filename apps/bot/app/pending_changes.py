"""Proposal service and pure domain validation. No plan mutation capabilities."""
from datetime import date, datetime, timezone
from enum import StrEnum
import logging
import uuid
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from .ai_contracts import CoachStructuredResponse

log = logging.getLogger(__name__)


class ProposalError(ValueError):
    pass


class ProposalConflict(ProposalError):
    pass


class PendingChangeStatus(StrEnum):
    PENDING = 'PENDING'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    APPLIED = 'APPLIED'
    EXPIRED = 'EXPIRED'
    SUPERSEDED = 'SUPERSEDED'
    INVALID = 'INVALID'


def allowed_now(job, plan):
    return bool(job.get('requested_change_proposal') is True and plan
                and plan.get('id') == job.get('plan_id')
                and plan.get('owner_id') == job.get('owner_id')
                and plan.get('status') == 'active'
                and plan.get('revision', 1) == job.get('plan_revision'))


class PendingChangeValidator:
    def validate(self, proposal, job, plan, today=None):
        today = today or datetime.now(ZoneInfo('Europe/Madrid')).date()
        errors = []

        def fail(code, index=None, field=None):
            errors.append({'code': code, 'change_index': index, 'field': field})

        if not allowed_now(job, plan):
            fail('stale_or_unavailable_plan')
        sessions = {s['id']: s for s in (plan or {}).get('sessions', [])}
        seen = set()
        fields = {
            'RESCHEDULE': {'date'},
            'ADJUST_DURATION': {'duration_min', 'duration_max'},
            'ADJUST_INTENSITY': {'intensity', 'target_pace', 'target_power_w'},
            'REPLACE_SESSION': {'date', 'sport', 'session_type', 'duration_min', 'duration_max',
                                'intensity', 'target_pace', 'target_power_w'},
            'CANCEL_SESSION': set(),
        }
        for i, change in enumerate(proposal.changes):
            if change.session_id in seen:
                fail('duplicate_session', i, 'session_id')
            seen.add(change.session_id)
            session = sessions.get(change.session_id)
            if not session:
                fail('session_not_found', i, 'session_id')
                continue
            if session.get('owner_id') != job.get('owner_id'):
                fail('wrong_owner', i, 'session_id')
            if session.get('training_plan_id') != job.get('plan_id'):
                fail('wrong_plan', i, 'session_id')
            if session.get('status') != 'planned' or session.get('completed_activity_id'):
                fail('session_not_modifiable', i, 'session_id')
            try:
                if date.fromisoformat(session['date']) < today:
                    fail('session_in_past', i, 'session_id')
            except (ValueError, KeyError, TypeError):
                fail('invalid_session_date', i, 'session_id')
            # Optional nulls from the worker's Pydantic serialization mean absent,
            # never "erase this value". Required operation fields are checked below.
            values = change.proposed_values.model_dump(mode='json', exclude_none=True)
            op = change.operation
            if (set(values) - fields[op] or (not values and op != 'CANCEL_SESSION')
                    or (op == 'RESCHEDULE' and not values.get('date'))
                    or (op == 'ADJUST_DURATION' and values.get('duration_min') is None)
                    or (op == 'REPLACE_SESSION' and not values.get('session_type'))):
                fail('operation_fields', i, 'proposed_values')
            if op == 'CANCEL_SESSION':
                continue
            # REPLACE_SESSION transforms this same identity. Sport/type changes must
            # explicitly supply their own dose; never inherit incompatible targets.
            replace = op == 'REPLACE_SESSION'
            if replace and not {'sport', 'session_type', 'duration_min', 'duration_max', 'intensity'} <= set(values):
                fail('replacement_requires_complete_dose', i, 'proposed_values')
            candidate = {**session, **values}
            if replace:
                for target in ('target_pace', 'target_power_w'):
                    candidate[target] = values.get(target)
                candidate.pop('distance_km', None)
            if values.get('date'):
                proposed_date = date.fromisoformat(values['date'])
                if proposed_date < today:
                    fail('past_date', i, 'date')
                if not plan['start_date'] <= values['date'] <= plan['end_date']:
                    fail('outside_plan', i, 'date')
            low, high = candidate.get('duration_min'), candidate.get('duration_max')
            rest = candidate.get('sport') == 'recovery' and candidate.get('session_type') == 'rest'
            if op in ('ADJUST_DURATION', 'REPLACE_SESSION') and (low is None or high is None or high < low or (low <= 0 and not rest)):
                fail('invalid_duration_range', i, 'duration_min')
            if rest and op != 'RESCHEDULE' and (
                low not in (None, 0) or high not in (None, 0)
                or candidate.get('target_pace') or candidate.get('target_power_w')
            ):
                fail('rest_has_training_dose', i, 'proposed_values')
            sport = candidate.get('sport')
            if sport not in {'running', 'cycling', 'strength', 'mobility', 'recovery'}:
                fail('invalid_sport', i, 'sport')
            supported_types = {
                'running': {'easy', 'easy_run', 'easy_progressions', 'aerobic', 'long_run', 'quality', 'recovery'},
                'cycling': {'easy', 'recovery', 'aerobic'},
                'strength': {'full_body_a', 'full_body_b'},
                'recovery': {'rest', 'rest_mobility'},
                'mobility': {'rest_mobility'},
            }
            if replace and candidate.get('session_type') not in supported_types.get(sport, set()):
                fail('invalid_session_type', i, 'session_type')
            if candidate.get('intensity') in (None, 'unknown') or (candidate.get('intensity') == 'rest' and not rest):
                fail('invalid_intensity', i, 'intensity')
            if candidate.get('target_power_w') and sport != 'cycling':
                fail('power_requires_cycling', i, 'target_power_w')
            pace = candidate.get('target_pace')
            if pace:
                import re
                if sport != 'running' or not re.fullmatch(r'\d{1,2}:[0-5]\d(?:\s*(?:-|–)\s*\d{1,2}:[0-5]\d)?(?:\s*min/km)?', pace):
                    fail('invalid_running_pace', i, 'target_pace')
        for evidence in proposal.evidence:
            if evidence.source not in job.get('proposal_evidence_sources', []):
                fail('unavailable_evidence_source', field='evidence')
        return errors


def create_pending_change(raw, job, repository):
    """Repository exposes only read_plan/find/insert; all identity comes from job."""
    try:
        structured = (CoachStructuredResponse.model_validate_json(raw) if isinstance(raw, str)
                      else CoachStructuredResponse.model_validate(raw))
    except ValidationError as exc:
        log.warning('Invalid structured coach output job=%s errors=%s', job['id'], exc.error_count())
        raise ProposalError('Invalid structured_output') from exc
    proposal = structured.change_proposal
    existing = repository.find(job['id'])
    if proposal is None:
        if existing:
            raise ProposalConflict('Proposal payload conflict for source_job_id')
        return None
    if job.get('requested_change_proposal') is not True:
        raise ProposalError('Change proposal not authorized')
    payload = proposal.model_dump(mode='json', exclude_none=True)
    if existing:
        if existing['proposal_payload'] != payload:
            raise ProposalConflict('Proposal payload conflict for source_job_id')
        return existing
    if job.get('proposal_execution_allowed') is not True:
        raise ProposalError('Change proposal not authorized at execution')
    plan = repository.read_plan(job['plan_id'])
    errors = PendingChangeValidator().validate(proposal, job, plan)
    document = {
        'id': str(uuid.uuid4()), 'owner_id': job['owner_id'],
        'training_plan_id': job['plan_id'], 'base_plan_revision': job['plan_revision'],
        'source_job_id': job['id'], 'source': 'ollama',
        'status': PendingChangeStatus.INVALID.value if errors else PendingChangeStatus.PENDING.value,
        'proposal_payload': payload,
        'validation_errors': errors, 'created_at': datetime.now(timezone.utc).isoformat(),
        'expires_at': None,
    }
    return repository.insert(document)
