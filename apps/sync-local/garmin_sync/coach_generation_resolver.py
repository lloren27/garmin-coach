"""Resolve model choices against Python-owned authority, never model-supplied copies."""
from dataclasses import dataclass
from datetime import date
from pydantic import ValidationError
from .ai_contracts import CoachDecision, CoachEvidence, StructuredChangeProposal
from .coach_generation_contracts import CoachGenerationResponse, Conclusion
from .coach_generation_context import ContextSnapshot, EvidenceRecord, thaw
from .coach_validation import CoachValidationError, RepairHint, ValidationIssue, ValidationCode as Code, ValidationPhase as Phase, ValidationSeverity as Severity


REASONS = {
    'PLAN_SESSION': 'Sesión vigente del plan de entrenamiento.',
    'RECOVERY_RECOMMENDATION': 'Recomendación de recuperación; no modifica el plan vigente.',
    'OBSERVED_ACTIVITY': 'Actividad registrada en los datos disponibles.',
    'OBSERVED_WELLNESS': 'Medición de bienestar disponible.',
    'DATA_STALE': 'Los datos no confirman el estado actual.',
    'DATA_MISSING': 'Faltan datos para concretar la recomendación.',
    'NEEDS_CLARIFICATION': 'Necesito que indiques la fecha o sesión que quieres consultar.',
    'CHANGE_REQUESTED': 'Propuesta solicitada, pendiente de revisión y aprobación.',
    'ANALYSIS_LIMITED': 'El análisis disponible es limitado; no permite una conclusión adicional.',
}


@dataclass(frozen=True)
class ResolvedGeneration:
    response_type: str
    decisions: tuple[CoachDecision, ...]
    conclusions: tuple[Conclusion, ...]
    evidence: tuple[EvidenceRecord, ...]
    change_proposal: StructuredChangeProposal | None


def fail(code, phase, path, *, fatal=False, hint=None):
    raise CoachValidationError([ValidationIssue(code, phase, path,
        Severity.FATAL if fatal else Severity.RETRY_REQUIRED, repair_hint=hint)])


def evidence_wire(record: EvidenceRecord) -> CoachEvidence:
    source = 'backend' if record.source == 'zepp' else record.source
    facts = ', '.join(f'{k}={v}' for k, v in record.facts.items())
    return CoachEvidence(source=source, fact=f'{record.source}: {facts}'[:250], date=record.date)


def resolve_generation(response: CoachGenerationResponse, snapshot: ContextSnapshot) -> ResolvedGeneration:
    if response.context_snapshot_id != snapshot.id:
        fail(Code.CONTEXT_SNAPSHOT_MISMATCH, Phase.REFERENCE, 'context_snapshot_id', fatal=True)
    if response.change_proposal is not None and not snapshot.proposal_allowed:
        fail(Code.UNAUTHORIZED_CHANGE_PROPOSAL, Phase.AUTHORIZATION, 'change_proposal', fatal=True)
    refs = list(response.evidence_refs)
    for item in (*response.decisions, *response.conclusions): refs.extend(item.evidence_refs)
    if response.change_proposal: refs.extend(response.change_proposal.evidence_refs)
    for ref in refs:
        if ref not in snapshot.evidence:
            fail(Code.UNKNOWN_EVIDENCE_REF, Phase.REFERENCE, 'evidence_refs',
                 hint=RepairHint(allowed_refs=tuple(snapshot.evidence)))
    decisions, seen = [], set()
    for index, item in enumerate(response.decisions):
        path = f'decisions[{index}]'
        if item.action == 'keep_plan':
            session = snapshot.sessions.get(item.session_id)
            if (not session or session.get('status') not in (None, 'planned')
                or session.get('completed_activity_id') or item.session_id in seen):
                fail(Code.UNKNOWN_PLAN_SESSION, Phase.RESOLUTION, path + '.session_id')
            if any(session.get(k) is None for k in ('sport', 'session_type', 'intensity', 'duration_min')) or session.get('intensity') == 'unknown':
                fail(Code.INVALID_CONTEXT, Phase.RESOLUTION, path, fatal=True)
            seen.add(item.session_id)
            if session.get('date') not in snapshot.target_dates:
                fail(Code.PLAN_DATE_MISMATCH, Phase.RESOLUTION, path + '.date', hint=RepairHint(allowed_values=snapshot.target_dates))
            data = {k: v for k, v in session.items() if k in {'date', 'sport', 'session_type',
                    'intensity', 'duration_min', 'distance_km', 'target_pace', 'target_power_w'}}
            data.update(action='keep_plan', source='training_plan', reason=REASONS['PLAN_SESSION'],
                        duration_max_min=session.get('duration_max'))
        else:
            if item.action not in {'ask_user', 'information_only'} and not item.evidence_refs:
                fail(Code.INVALID_DECISION, Phase.DOMAIN, path + '.evidence_refs', hint=RepairHint(allowed_refs=tuple(snapshot.evidence)))
            data = item.model_dump(exclude={'evidence_refs', 'code'}, exclude_none=True)
            if item.action in {'ask_user', 'information_only'}:
                data['reason'] = REASONS[item.code]
            else:
                data['reason'] = REASONS['RECOVERY_RECOMMENDATION'] if item.action in {'rest', 'recovery'} else 'Recomendación puntual; el plan persistido no se ha modificado.'
                if item.date is None:
                    if len(snapshot.target_dates) != 1:
                        fail(Code.PLAN_DATE_MISMATCH, Phase.DOMAIN, path + '.date', hint=RepairHint(rule='Specify an unambiguous target date or ask the user.'))
                    data['date'] = snapshot.target_dates[0]
            if item.action == 'rest': data.update(sport='none', session_type='rest')
        try: decision = CoachDecision.model_validate(data)
        except ValidationError:
            fail(Code.INVALID_CONTEXT if item.action == 'keep_plan' else Code.INVALID_DECISION,
                 Phase.RESOLUTION if item.action == 'keep_plan' else Phase.DOMAIN, path, fatal=item.action == 'keep_plan')
        if decision.date and (decision.date < snapshot.now.date() or
                (snapshot.target_dates and str(decision.date) not in snapshot.target_dates)):
            fail(Code.PLAN_DATE_MISMATCH, Phase.DOMAIN, path + '.date')
        decisions.append(decision)
    if seen:
        expected = {k for k, s in snapshot.sessions.items() if s.get('status') in (None, 'planned')
                    and not s.get('completed_activity_id') and s.get('date') in snapshot.target_dates}
        if seen != expected:
            fail(Code.INVALID_DECISION, Phase.DOMAIN, 'decisions', hint=RepairHint(rule='Include every planned session in the requested scope, or ask for clarification.'))
    rests = {d.date for d in decisions if d.action == 'rest'}
    if any(d.date in rests and d.action not in {'rest', 'ask_user', 'information_only'} for d in decisions):
        fail(Code.INVALID_DECISION, Phase.DOMAIN, 'decisions')
    if not decisions and not response.conclusions and not refs:
        fail(Code.INVALID_DECISION, Phase.DOMAIN, 'decisions')
    for index, conclusion in enumerate(response.conclusions):
        kinds = {snapshot.evidence[r].kind for r in conclusion.evidence_refs}
        required = {'OBSERVED_ACTIVITY': 'activity', 'OBSERVED_WELLNESS': 'wellness', 'PLAN_SESSION': 'plan'}
        if conclusion.code in required and required[conclusion.code] not in kinds:
            fail(Code.INVALID_DECISION, Phase.DOMAIN, f'conclusions[{index}]')
        if conclusion.code == 'DATA_STALE' and snapshot.freshness != 'stale':
            fail(Code.INVALID_DECISION, Phase.DOMAIN, f'conclusions[{index}]')
        if conclusion.code == 'RECOVERY_RECOMMENDATION' and not any(d.action in {'rest', 'recovery'} for d in decisions):
            fail(Code.INVALID_DECISION, Phase.DOMAIN, f'conclusions[{index}]')
        if conclusion.code == 'DATA_MISSING' and snapshot.evidence:
            fail(Code.INVALID_DECISION, Phase.DOMAIN, f'conclusions[{index}]')
        if conclusion.code == 'CHANGE_REQUESTED' and response.change_proposal is None:
            fail(Code.INVALID_DECISION, Phase.DOMAIN, f'conclusions[{index}]')
    proposal = None
    if response.change_proposal:
        value = response.change_proposal
        changes, changed = [], set()
        for change in value.changes:
            session = snapshot.sessions.get(change.session_id)
            if not session or session.get('status') != 'planned' or change.session_id in changed:
                fail(Code.UNKNOWN_PLAN_SESSION, Phase.RESOLUTION, 'change_proposal.changes')
            changed.add(change.session_id)
            changes.append(dict(operation=change.operation, session_id=change.session_id,
                proposed_values=change.proposed_values, reason=REASONS['CHANGE_REQUESTED']))
        evidence = [evidence_wire(snapshot.evidence[r]) for r in value.evidence_refs]
        if any(e.source not in snapshot.proposal_sources for e in evidence):
            fail(Code.UNAUTHORIZED_CHANGE_PROPOSAL, Phase.AUTHORIZATION, 'change_proposal.evidence_refs', fatal=True)
        proposal = StructuredChangeProposal(reason=REASONS['CHANGE_REQUESTED'], confidence=value.confidence,
                                             evidence=evidence, changes=changes)
    if proposal is not None:
        from app.pending_changes import PendingChangeValidator
        plan = thaw(snapshot.plan)
        if any(plan.get(k) is None for k in ('id', 'owner_id', 'revision', 'start_date', 'end_date')):
            fail(Code.INVALID_CONTEXT, Phase.AUTHORIZATION, 'change_proposal', fatal=True)
        job = dict(requested_change_proposal=snapshot.proposal_allowed, plan_id=plan['id'],
                   owner_id=plan['owner_id'], plan_revision=plan['revision'],
                   proposal_evidence_sources=list(snapshot.proposal_sources))
        errors = PendingChangeValidator().validate(proposal, job, plan, today=snapshot.now.date())
        if errors:
            fail(Code.INVALID_DECISION, Phase.DOMAIN, 'change_proposal',
                 hint=RepairHint(rule='Respect operation fields, dose, sport, session identity and plan date bounds.'))
    return ResolvedGeneration(response.response_type, tuple(decisions), tuple(response.conclusions),
                              tuple(snapshot.evidence[r] for r in dict.fromkeys(refs)), proposal)
