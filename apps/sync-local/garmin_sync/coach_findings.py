"""Admissible findings, frozen keyword baseline and shared deterministic renderer."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re
import unicodedata

from .coach_analysis import AnalysisFacts, MatchState, build_analysis_facts
from .coach_generation_context import freeze
from .coach_intent import ClarificationCode, CoachIntent, clarification_prompt

SELECTOR = freeze(json.loads(Path(__file__).with_name('coach_selector_v1.json').read_text()))
FOLLOW_UPS = freeze({
    'CLARIFY_SYMPTOM_CONTEXT': '¿La molestia continúa y cuándo aparece?',
    'CONFIRM_PLAN_MATCH': '¿Puedes confirmar qué actividad corresponde a la sesión prevista?',
    'PROVIDE_TRAINING_PLAN': '¿Puedes aportar el plan para comparar estas actividades?',
    'PROVIDE_MISSING_CONTEXT': '¿Puedes aportar los datos o el contexto que faltan para esta consulta?',
    'REVIEW_HISTORY_WINDOW': '¿Dispones de un histórico personal comparable de sueño y pulso?',
})


@dataclass(frozen=True)
class Finding:
    id: str
    code: str
    component_index: int
    date: date | None
    fact_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    certainty: str
    text: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class FindingCatalog:
    facts: AnalysisFacts
    findings: tuple[Finding, ...]
    required_ids: tuple[str, ...]
    question: str


@dataclass(frozen=True)
class AnalysisSelection:
    schema_version: str
    snapshot_id: str
    component_index: int
    finding_ids: tuple[str, ...]
    follow_up: str | None


def tokens(text):
    clean = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return re.findall(r'[^\W_]+', clean.casefold())


def focus_families(question):
    words, hits = tokens(question), []
    for order, family in enumerate(SELECTOR['families']):
        positions = [i for phrase in family['phrases'] for p in [tokens(phrase)]
                     for i in range(len(words)) if words[i:i + len(p)] == p]
        if positions:
            hits.append((min(positions), order, family['id']))
    return tuple(item[2] for item in sorted(hits))


def number(value, places=2):
    text = f'{value:.{places}f}'.rstrip('0').rstrip('.') if places else str(int(value))
    return text.replace('.', ',')


def duration(seconds):
    total = int(Decimal(seconds).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}'


def _activity_summary(facts):
    grouped = {}
    for fact in facts:
        if fact.source == 'training_plan' or fact.metric not in {'duration_s', 'distance_km'}:
            continue
        key = (fact.date, fact.sport, fact.source, tuple(fact.source_refs))
        grouped.setdefault(key, {})[fact.metric] = fact.value

    summaries = []
    for (day, sport, source, _refs), metrics in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1] or '', item[0][2], item[0][3])
    ):
        values = []
        if 'duration_s' in metrics:
            values.append(duration(metrics['duration_s']))
        if 'distance_km' in metrics:
            values.append(number(metrics['distance_km']) + ' km')
        summaries.append(f'{sport or "actividad"}: {", ".join(values)} ({source}, {day.isoformat()})')
    return '; '.join(summaries)


def build_catalog(snapshot, component_index, question):
    facts = build_analysis_facts(snapshot, component_index)
    findings, required = [], []
    by_id = {f.id: f for f in facts.facts}
    component = snapshot.intent.components[component_index]

    def add(code, text, refs=(), day=None, sources=(), certainty='observed', dependencies=(), mandatory=False):
        identifier = f'c{component_index}:{code}:{len(findings)}'
        source_refs = tuple(sorted(set(sources) | {r for ref in refs for r in by_id[ref].source_refs}))
        findings.append(Finding(identifier, code, component_index, day, tuple(refs), source_refs,
                                certainty, text, dependencies))
        if mandatory:
            required.append(identifier)
        return identifier

    for match in facts.matches:
        state = match.state
        if state is MatchState.AMBIGUOUS_MULTIPLE:
            options = f' Actividades: {", ".join(match.activity_refs)}. Sesiones: {", ".join(match.session_refs)}.'
            add('PLAN_MATCH_AMBIGUOUS', 'Hay varias correspondencias posibles entre actividades y sesiones; falta identificar cuál corresponde.' + options, day=match.date, sources=match.activity_refs + match.session_refs)
        elif state is MatchState.INSUFFICIENT_DATA:
            add('PLAN_MATCH_INSUFFICIENT_DATA', 'Faltan datos comparables para relacionar la actividad con el plan.', day=match.date, sources=match.activity_refs + match.session_refs)
        elif state is MatchState.NONE and not match.session_refs:
            refs = tuple(f.id for f in facts.facts if f.source != 'training_plan'
                         and f.metric in {'duration_s', 'distance_km'}
                         and set(f.source_refs) & set(match.activity_refs))
            detail = ''
            # For a single-sport answer, this finding is the place where the
            # recorded activity is surfaced. Multisport answers already have
            # one shared, grouped summary below.
            if 'MULTISPORT_COMPONENTS_SEPARATE' not in facts.limitations:
                detail = _activity_summary([by_id[ref] for ref in refs])
            text = 'No hay sesiones del plan compatibles para comparar con estos datos.'
            if detail:
                text += ' Actividad registrada: ' + detail + '.'
            add('NO_PLAN_FOR_SCOPE', text,
                refs, day=match.date, sources=match.activity_refs)
        dependency = ()
        if state is MatchState.CANDIDATE:
            dependency = (add('PLAN_MATCH_UNCONFIRMED', 'La correspondencia con el plan todavía no está confirmada.', day=match.date, sources=match.activity_refs + match.session_refs, certainty='candidate'),)
        for comp in match.comparisons:
            source = by_id[comp.operand_refs[0]].source
            if comp.metric == 'duration':
                actual = duration(comp.observed)
                target = f'{number(comp.lower / 60)}–{number(comp.upper / 60)} min'
            else:
                actual = f'{number(comp.observed)} km'
                target = f'{number(comp.lower)} km'
            base = f'{actual} registrados ({source}) frente a {target} previstos (plan).'
            if comp.metric == 'distance':
                duration_facts = [f for f in facts.facts if f.metric == 'duration_s'
                                  and f.source != 'training_plan' and set(f.source_refs) & set(match.activity_refs)]
                if len(duration_facts) == 1:
                    base += f' Duración registrada: {duration(duration_facts[0].value)} ({duration_facts[0].source}).'
            if state is MatchState.IMPLAUSIBLE_SINGLE:
                if comp.outside_band:
                    add('PLAN_ACTIVITY_MAGNITUDE_MISMATCH', base + ' La diferencia es grande; puede no tratarse de la misma sesión.', comp.operand_refs, match.date, certainty='uncertain')
            elif state in (MatchState.CONFIRMED, MatchState.CANDIDATE):
                position = 'BELOW' if comp.delta < 0 else 'ABOVE' if comp.delta > 0 else 'WITHIN'
                code = (f'DURATION_{position}_PLAN_RANGE' if comp.metric == 'duration' else
                        f'DISTANCE_{"AT" if position == "WITHIN" else position}_PLAN')
                change = ('Dentro del objetivo previsto.' if comp.delta == 0 else
                          f'Diferencia: {"−" if comp.delta < 0 else "+"}{duration(abs(comp.delta)) if comp.metric == "duration" else number(abs(comp.delta)) + " km"} '
                          f'({"−" if comp.percent < 0 else "+"}{number(abs(comp.percent), 1)} % respecto al objetivo o límite más cercano).')
                prefix = 'Si corresponde a la sesión prevista: ' if dependency else ''
                add(code, prefix + base + ' ' + change,
                    comp.operand_refs + (tuple(f.id for f in duration_facts) if comp.metric == 'distance' else ()), match.date,
                    certainty='candidate' if dependency else 'confirmed', dependencies=dependency)

    if component.intent is CoachIntent.CONSULT_PLAN:
        if 'PLAN_SESSION_SPORT_UNKNOWN' in facts.limitations:
            add('PLAN_SESSION_SPORT_UNKNOWN',
                clarification_prompt(ClarificationCode.PLAN_SESSION_SPORT_UNKNOWN), mandatory=True)
        elif 'PLAN_SPORT_NOT_PLANNED' in facts.limitations:
            sport = component.sport.value if component.sport else 'requested'
            labels = {'cycling': 'ciclismo', 'running': 'carrera', 'swimming': 'natación', 'strength': 'fuerza'}
            label = labels.get(sport, sport)
            days = ', '.join(d.isoformat() for d in component.advice_dates or component.observed_dates)
            add('PLAN_SPORT_NOT_PLANNED',
                f'El plan disponible no muestra una sesión de {label} para {days}.', mandatory=True)
        else:
            plan_facts = [f for f in facts.facts if f.source == 'training_plan']
            sessions_by_id = {f'session:{key}': session for key, session in snapshot.sessions.items()}
            details = []
            sport_labels = {'cycling': 'ciclismo', 'running': 'carrera', 'swimming': 'natación',
                            'strength': 'fuerza', 'walking': 'caminata', 'multisport': 'multideporte'}
            for ref in sorted({ref for fact in plan_facts for ref in fact.source_refs}):
                session = sessions_by_id.get(ref)
                if not session:
                    continue
                sport = sport_labels.get(session.get('sport'), session.get('sport')) or 'actividad sin deporte indicado'
                parts = [f'{sport} ({session.get("date")})']
                low, high = session.get('duration_min'), session.get('duration_max')
                if low is not None and high is not None:
                    parts.append(f'{number(low)}–{number(high)} min')
                elif session.get('duration_min') is not None:
                    parts.append(f'{number(session["duration_min"])} min')
                if session.get('distance_km') is not None:
                    parts.append(f'{number(session["distance_km"])} km')
                if session.get('session_type'):
                    parts.append(str(session['session_type']).replace('_', ' '))
                details.append(', '.join(parts))
            if details:
                add('PLAN_SESSION_AVAILABLE', 'Sesión' + ('es' if len(details) > 1 else '') +
                    ' del plan: ' + '; '.join(details) + '.',
                    sources=tuple(sorted({ref for fact in plan_facts for ref in fact.source_refs})), mandatory=True)

    for fact in facts.facts:
        if fact.metric == 'pace_s_per_km':
            add('PACE_BLOCKS_NOT_COMPARABLE', f'Ritmo medio: {duration(fact.value)} min/km ({fact.source}, {fact.date.isoformat()}). '
                'Se calcula con la duración registrada, cuya inclusión de pausas no consta. El promedio no demuestra cumplimiento de bloques.', (fact.id,), fact.date)
    wellness = [f for f in facts.facts if f.metric in {'total_minutes', 'score', 'resting_hr', 'stress_avg'} and f.source not in {'training_plan', 'derived'}]
    if wellness:
        if 'sleep' in focus_families(question):
            wellness.sort(key=lambda f: ({'total_minutes': 0, 'score': 1}.get(f.metric, 2), f.id))
        labels = {'total_minutes': 'sueño', 'score': 'puntuación de sueño', 'resting_hr': 'pulso en reposo', 'stress_avg': 'estrés'}
        detail = '; '.join(f'{labels[f.metric]} {number(f.value)} {f.unit.value} ({f.source}, {f.date.isoformat()})' for f in wellness)
        add('WELLNESS_OBSERVATION_AVAILABLE', detail + '.', tuple(f.id for f in wellness))
        baseline = any(t in tokens(question) for t in ('costumbre', 'recuperado', 'recuperacion', 'historial', 'habitual', 'tendencia'))
        add('WELLNESS_BASELINE_UNAVAILABLE', 'No se ha establecido una referencia personal comparable.', tuple(f.id for f in wellness), mandatory=baseline)
        add('WELLNESS_TREND_NOT_ASSESSABLE', 'Estas mediciones aisladas no permiten concluir una tendencia ni una mejor recuperación.', tuple(f.id for f in wellness), mandatory=baseline)
    if 'MULTISPORT_COMPONENTS_SEPARATE' in facts.limitations:
        activities = [f for f in facts.facts if f.metric in {'duration_s', 'distance_km'} and f.source != 'training_plan']
        text = _activity_summary(activities)
        add('MULTISPORT_COMPONENTS_SEPARATE', text + '. Las cargas de deportes y escalas distintas se mantienen separadas; no se suman TRIMP, TSS y carga muscular.', tuple(f.id for f in activities))
    if 'DATA_COVERAGE_INCOMPLETE' in facts.limitations:
        periods = []
        if component.selector.value == 'latest_activity':
            for key, status in sorted(facts.provider_status.items()):
                if status.get('scope') != 'activities' or status.get('state') == 'not_configured':
                    continue
                start, end = status.get('period_start'), status.get('period_end')
                if start or end:
                    periods.append(f'{key.split(".", 1)[0]}: {start or "fecha no disponible"} — {end or "fecha no disponible"}')
        text = 'La cobertura de datos es incompleta; falta información para valorar la actividad.'
        if periods:
            text += ' Periodos disponibles: ' + '; '.join(periods) + '.'
        text += ' ¿Puedes sincronizar o aportar el registro de actividad?'
        add('DATA_COVERAGE_INCOMPLETE', text, mandatory=True)
    if 'ACTIVITY_NOT_RECORDED' in facts.limitations:
        add('ACTIVITY_NOT_RECORDED', 'No consta actividad en el ámbito con cobertura comprobada.', mandatory=True)
    if 'INCOMPARABLE_ACTIVITY_TIME' in facts.limitations:
        add('INCOMPARABLE_ACTIVITY_TIME', clarification_prompt(ClarificationCode.INCOMPARABLE_ACTIVITY_TIME),
            mandatory=True)
    if 'MULTISPORT_ACTIVITY_CONFIRMATION' in facts.limitations:
        add('MULTISPORT_ACTIVITY_CONFIRMATION',
            clarification_prompt(ClarificationCode.MULTISPORT_ACTIVITY_CONFIRMATION), mandatory=True)
    for code in facts.limitations:
        if code.endswith('_NOT_RECORDED_IN_WINDOW'):
            sport = code.removesuffix('_NOT_RECORDED_IN_WINDOW').lower()
            labels = {'cycling': 'ciclismo', 'running': 'carrera', 'swimming': 'natación',
                      'strength': 'fuerza', 'activity': 'actividad'}
            label = labels.get(sport, 'actividad')
            add(code, f'No hay {label} registrada en los últimos 120 días; no puedo confirmar una sesión más reciente.',
                mandatory=True)
    # Context for advice keeps its original evidence date; it never becomes an
    # observation on tomorrow's date. Only explicit recorded symptoms qualify.
    symptoms = [e for e in snapshot.evidence.values() if e.kind == 'checkin'
                and e.date and e.date <= snapshot.now.date().isoformat()
                and any(e.facts.get(k) is True or e.facts.get(k) == 1 for k in ('pain', 'soreness'))]
    applicable = [e for e in symptoms if e.date in {d.isoformat() for d in facts.observed_dates} or component.advice_dates
                  or component.clarification_code is not None]
    if applicable:
        refs = tuple(e.id for e in applicable)
        dates = ', '.join(sorted({e.date for e in applicable}))
        details = '; '.join(f'«{text}»' for e in applicable for text in e.symptom_details)
        symptom_text = f'Hay una molestia registrada (checkin, {dates}); falta precisar su evolución.'
        if details:
            symptom_text += ' Texto referido: ' + details + '.'
        target_sessions = [s for s in snapshot.sessions.values()
                           if s.get('date') in {d.isoformat() for d in component.advice_dates}
                           and s.get('status') in (None, 'planned')
                           and not s.get('completed_activity_id')]
        for session in target_sessions:
            if session.get('intensity') == 'threshold':
                symptom_text += f' La sesión prevista para {session["date"]} figura como umbral (plan); esto no avala realizarla.'
        add('SYMPTOM_REPORTED', symptom_text, sources=refs + tuple('session:' + s['id'] for s in target_sessions if s.get('intensity') == 'threshold'))
        if component.advice_dates or component.clarification_code is not None or any(t in tokens(question) for t in ('umbral', 'seguro', 'sesion')):
            symptom_id = findings[-1].id
            required.append(symptom_id)
            add('SESSION_SAFETY_NOT_ASSESSABLE', 'No puedo valorar si es seguro hacerla.', sources=refs, mandatory=True)
    return FindingCatalog(facts, tuple(findings), tuple(required), question)


def _follow_up(findings, question=''):
    codes = {f.code for f in findings}
    if codes & {'PLAN_SESSION_AVAILABLE', 'PLAN_SPORT_NOT_PLANNED', 'PLAN_SESSION_SPORT_UNKNOWN'}:
        return None
    if codes & {'SYMPTOM_REPORTED', 'SESSION_SAFETY_NOT_ASSESSABLE'}:
        return 'CLARIFY_SYMPTOM_CONTEXT'
    if codes & {'PLAN_MATCH_UNCONFIRMED', 'PLAN_MATCH_AMBIGUOUS', 'PLAN_ACTIVITY_MAGNITUDE_MISMATCH'}:
        return 'CONFIRM_PLAN_MATCH'
    if 'NO_PLAN_FOR_SCOPE' in codes:
        return 'PROVIDE_TRAINING_PLAN'
    if not codes or codes & {'DATA_COVERAGE_INCOMPLETE', 'PLAN_MATCH_INSUFFICIENT_DATA'}:
        return 'PROVIDE_MISSING_CONTEXT'
    if codes & {'WELLNESS_BASELINE_UNAVAILABLE', 'WELLNESS_TREND_NOT_ASSESSABLE'}:
        if any(t in tokens(question) for t in ('costumbre', 'recuperado', 'recuperacion', 'historial', 'habitual', 'tendencia')):
            return 'REVIEW_HISTORY_WINDOW'
    return None


def select_findings(catalog, question):
    families = focus_families(question) or SELECTOR['default_family_order']
    mapping = {f['id']: f for f in SELECTOR['families']}
    selected = []
    for family in families:
        for code in mapping[family]['codes']:
            for finding in catalog.findings:
                if finding.code == code and finding.id not in selected and len(selected) < SELECTOR['max_focus_findings']:
                    selected.append(finding.id)
    by_id = {f.id: f for f in catalog.findings}
    for identifier in tuple(selected):
        selected.extend(d for d in by_id[identifier].dependencies if d not in selected)
    selected.extend(i for i in catalog.required_ids if i not in selected)
    chosen = [by_id[i] for i in selected]
    result = AnalysisSelection('1', catalog.facts.snapshot_id, catalog.facts.component_index,
                               tuple(selected), _follow_up(chosen, question))
    validate_selection(catalog, result)
    return result


def validate_selection(catalog, selection):
    by_id = {f.id: f for f in catalog.findings}
    if (selection.schema_version != '1' or selection.snapshot_id != catalog.facts.snapshot_id
            or selection.component_index != catalog.facts.component_index):
        raise ValueError('SELECTION_SCOPE_INVALID')
    ids = selection.finding_ids
    if len(ids) != len(set(ids)) or any(i not in by_id for i in ids):
        raise ValueError('SELECTION_REFERENCE_INVALID')
    families = focus_families(catalog.question) or SELECTOR['default_family_order']
    relevant_codes = {code for family in SELECTOR['families'] if family['id'] in families for code in family['codes']}
    if not ids and any(f.code in relevant_codes for f in catalog.findings):
        raise ValueError('SELECTION_EMPTY')
    dependencies = {d for i in ids for d in by_id[i].dependencies}
    if not (set(catalog.required_ids) | dependencies) <= set(ids):
        raise ValueError('SELECTION_REQUIRED_LIMITATION_MISSING')
    if len(set(ids) - set(catalog.required_ids) - dependencies) > SELECTOR['max_focus_findings']:
        raise ValueError('SELECTION_BUDGET_EXCEEDED')
    if selection.follow_up != _follow_up([by_id[i] for i in ids], catalog.question):
        raise ValueError('SELECTION_FOLLOW_UP_INVALID')


def render_selection(catalog, selection):
    validate_selection(catalog, selection)
    by_id = {f.id: f for f in catalog.findings}
    lines = []
    no_plan_dates = set()
    for identifier in selection.finding_ids:
        finding = by_id[identifier]
        if finding.code == 'NO_PLAN_FOR_SCOPE':
            if finding.date in no_plan_dates:
                continue
            no_plan_dates.add(finding.date)
        lines.append(finding.text)
    if selection.follow_up:
        lines.append(FOLLOW_UPS[selection.follow_up])
    return '\n'.join(lines)
