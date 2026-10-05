"""V3 deterministic service; no generation, storage or mutation authority."""
from .ai_contracts import CoachDecision, CoachStructuredResponse, CoachEvidence
from .coach_findings import build_catalog, select_findings, render_selection, FOLLOW_UPS
from .coach_generation_context import build_snapshot
from .coach_intent import clarification_prompt, CoachIntent


def safe_response(snapshot=None):
    text = ('No puedo completar la valoración con los datos disponibles ni valorar si es seguro '
            'hacer la sesión. ¿Puedes precisar la fecha, la sesión y si hay molestias?')
    decisions = []
    if snapshot is not None:
        for index, component in enumerate(snapshot.intent.components):
            dates = component.observed_dates or component.advice_dates
            decisions.append(CoachDecision(action='ask_user', source='deterministic', reason=text,
                component_index=index, date=dates[0] if len(dates) == 1 else None))
    return CoachStructuredResponse(response_type='information', answer=text,
        decisions=decisions or [CoachDecision(action='ask_user', source='deterministic', reason=text)])


def deterministic_response(question, compact, *, now, max_chars=3200):
    snapshot = build_snapshot(question, compact, now=now)
    parts, decisions, evidence = [], [], {}
    mismatch_seen = False
    for index, component in enumerate(snapshot.intent.components):
        catalog = build_catalog(snapshot, index, question)
        selection = select_findings(catalog, question)
        codes = {f.code for f in catalog.findings if f.id in selection.finding_ids}
        for finding in catalog.findings:
            if finding.id not in selection.finding_ids:
                continue
            for ref in finding.source_refs:
                if ref in evidence:
                    continue
                record = snapshot.evidence.get(ref)
                session = snapshot.sessions.get(ref.removeprefix('session:')) if ref.startswith('session:') else None
                if record:
                    evidence[ref] = CoachEvidence(source=record.source, date=record.date,
                        fact=f'{finding.code}: {ref}'[:250], source_device=record.source_device,
                        source_records=[{k: None if v is None else str(v) for k, v in row.items()}
                                        for row in record.source_records[:20]])
                elif session:
                    evidence[ref] = CoachEvidence(source='training_plan', date=session.get('date'),
                        fact=f'{finding.code}: {ref}'[:250])
        text = render_selection(catalog, selection)
        follow_up = selection.follow_up
        if component.clarification_code and not catalog.required_ids:
            text = clarification_prompt(component.clarification_code)
            follow_up = 'PROVIDE_MISSING_CONTEXT'
        elif component.intent is CoachIntent.REQUEST_CHANGE:
            text += '\nNo se ha aplicado ningún cambio. Hace falta el flujo de propuesta y aprobación para modificar el plan.'
            follow_up = follow_up or 'PROVIDE_MISSING_CONTEXT'
        elif component.advice_dates and not catalog.required_ids:
            follow_up = 'CONFIRM_PLAN_MATCH' if mismatch_seen else 'PROVIDE_MISSING_CONTEXT'
            text = FOLLOW_UPS[follow_up]
        mismatch_seen |= bool(codes & {'PLAN_ACTIVITY_MAGNITUDE_MISMATCH', 'PLAN_MATCH_AMBIGUOUS'})
        dates = component.observed_dates or component.advice_dates or catalog.facts.observed_dates
        label = ', '.join(d.isoformat() for d in dates)
        parts.append((label + ':\n' if label else '') + text)
        reason = FOLLOW_UPS[follow_up] if follow_up else 'Valoración informativa basada en los hechos disponibles.'
        decisions.append(CoachDecision(action='ask_user' if follow_up else 'information_only',
            source='deterministic', component_index=index, date=dates[0] if len(dates) == 1 else None,
            reason=reason))
    answer = '\n\n'.join(parts)
    # Never truncate mandatory safety or attach a plan decision to a partial answer.
    if len(answer) > min(max_chars, 3500):
        return safe_response(snapshot)
    return CoachStructuredResponse(response_type='analysis', decisions=decisions, answer=answer,
                                   evidence=list(evidence.values())[:4])
