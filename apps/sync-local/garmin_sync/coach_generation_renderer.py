"""Canonical Spanish text from validated decisions; never a second LLM prescription."""
from .ai_contracts import CoachStructuredResponse
from .coach_generation_resolver import ResolvedGeneration, REASONS, evidence_wire, fail
from .coach_generation_context import ContextSnapshot
from .coach_validation import ValidationCode as Code, ValidationPhase as Phase

SPORTS = {'running': 'carrera', 'cycling': 'bicicleta', 'strength': 'fuerza',
          'mobility': 'movilidad', 'recovery': 'recuperación', 'none': 'descanso'}
INTENSITIES = {'rest': 'descanso', 'recovery': 'recuperación', 'easy': 'suave',
    'moderate': 'moderada', 'tempo': 'tempo', 'threshold': 'umbral', 'vo2max': 'VO2 máx.',
    'hard': 'alta', 'very_easy': 'muy suave', 'Z1': 'zona 1', 'Z1-Z2': 'zonas 1–2',
    'Z2': 'zona 2', 'marathon_pace': 'ritmo de maratón', 'unknown': 'sin determinar'}
# Known metric names only. Labels supply units without inferring unknown metrics.
METRICS = {
    'distance_km': ('distancia', 'km'), 'duration_s': ('duración', 's'),
    'duration_min': ('duración mínima', 'minutos'), 'duration_max': ('duración máxima', 'minutos'),
    'avg_hr': ('pulso medio', 'lpm'), 'max_hr': ('pulso máximo', 'lpm'),
    'avg_power': ('potencia media', 'W'), 'target_power_w': ('potencia objetivo', 'W'),
    'total_minutes': ('sueño', 'minutos'), 'resting_hr': ('pulso en reposo', 'lpm'),
    'steps': ('pasos', ''), 'score': ('puntuación', ''),
    'deep_minutes': ('sueño profundo', 'minutos'), 'rem_minutes': ('sueño REM', 'minutos'),
    'light_minutes': ('sueño ligero', 'minutos'), 'awake_minutes': ('vigilia', 'minutos'),
    'age': ('edad', 'años'), 'weight_kg': ('peso', 'kg'), 'height_cm': ('altura', 'cm'),
    'ftp': ('FTP', 'W'), 'ftp_w': ('FTP', 'W'), 'vo2max': ('VO2 máx.', 'ml/kg/min'),
    'km_28d': ('distancia de 28 días', 'km'), 'km_56d': ('distancia de 56 días', 'km'),
    'km_7d': ('distancia de 7 días', 'km'), 'runs_count_28d': ('carreras en 28 días', ''),
    'avg_weekly_km_8w': ('media semanal de 8 semanas', 'km'),
    'tss': ('TSS', ''), 'if': ('factor de intensidad', ''), 'vi': ('índice de variabilidad', ''),
    'atl': ('carga aguda del proveedor', ''), 'ctl': ('carga crónica del proveedor', ''),
    'tsb': ('balance de carga del proveedor', ''), 'trimp': ('TRIMP del proveedor', ''),
    'sport_load': ('carga deportiva del proveedor', ''), 'recovery_factor': ('factor de recuperación del proveedor', ''),
    'stress_avg': ('estrés medio del proveedor', ''), 'pain': ('dolor comunicado', ''),
    'soreness': ('molestias comunicadas', ''),
}
SOURCES = {'zepp': 'Zepp', 'garmin': 'Garmin', 'wattwise': 'Wattwise', 'backend': 'cálculos del sistema',
           'profile': 'perfil', 'training_plan': 'plan', 'checkin': 'check-in', 'strength': 'fuerza registrada', 'lab_test': 'prueba aplicada'}


def number(value):
    if isinstance(value, bool): return 'sí' if value else 'no'
    return format(value, '.15g').replace('.', ',')


def decision_text(decision):
    if decision.action in {'ask_user', 'information_only'}: return decision.reason
    when = f'{decision.date}: ' if decision.date else ''
    if decision.action == 'rest': return when + 'recomiendo descanso.'
    lead = 'Sesión del plan' if decision.source == 'training_plan' else 'Recomendación puntual'
    parts = [f'{when}{lead}: {SPORTS[decision.sport]}']
    if decision.duration_min is not None:
        high = decision.duration_max_min
        span = str(decision.duration_min) if high in (None, decision.duration_min) else f'{decision.duration_min} a {high}'
        parts.append(f'{span} minutos')
    parts.append(f'intensidad {INTENSITIES[decision.intensity]}')
    if decision.distance_km is not None: parts.append(f'{number(decision.distance_km)} km')
    if decision.target_pace: parts.append(f'ritmo {decision.target_pace}')
    if decision.target_power_w is not None: parts.append(f'{decision.target_power_w} W')
    return ', '.join(parts) + '.'


def render_generation(result: ResolvedGeneration, snapshot: ContextSnapshot, *, max_chars: int) -> CoachStructuredResponse:
    required = [decision_text(d) for d in result.decisions]
    warnings = []
    if snapshot.freshness != 'current':
        warnings.append('Los datos no confirman tu estado actual; actualiza la sincronización antes de decidir la carga.')
    if any(d.source != 'training_plan' and d.action not in {'ask_user', 'information_only'} for d in result.decisions):
        warnings.append('Esta recomendación no modifica el plan vigente; ajústala si aparecen molestias o cambia tu recuperación.')
    if result.change_proposal:
        required.append(REASONS['CHANGE_REQUESTED'])
        # Summarize the exact proposed deltas, not a second description of a workout.
        for change in result.change_proposal.changes:
            values = change.proposed_values.model_dump(mode='json', exclude_none=True)
            names = {'RESCHEDULE': 'Reprogramar', 'ADJUST_DURATION': 'Ajustar duración',
                     'ADJUST_INTENSITY': 'Ajustar intensidad', 'REPLACE_SESSION': 'Sustituir sesión',
                     'CANCEL_SESSION': 'Cancelar sesión'}
            session = snapshot.sessions[change.session_id]
            details = []
            for key, value in values.items():
                if key == 'session_type': continue  # Sport, dose and intensity define the dose below.
                if key == 'sport': details.append(SPORTS[value])
                elif key == 'intensity': details.append('intensidad ' + INTENSITIES[value])
                elif key == 'date': details.append('nueva fecha ' + value)
                elif key == 'target_pace': details.append('ritmo ' + value)
                elif key in METRICS:
                    label, unit = METRICS[key]; details.append(f'{label}: {number(value)} {unit}'.strip())
            required.append(f"{names[change.operation]} ({session['date']}, {SPORTS[session['sport']]}): " +
                            ('; '.join(details) if details else 'pendiente de aprobación') + '.')
    required.extend(warnings)
    if not required: required = [REASONS['ANALYSIS_LIMITED']]
    answer = '\n'.join(required)
    if len(answer) > min(max_chars, 3500):
        fail(Code.RENDERING_FAILED, Phase.RENDERING, 'answer', fatal=True)
    optional = [REASONS[c.code] for c in result.conclusions if c.code != 'DATA_STALE']
    for record in result.evidence[:4]:
        facts = []
        for key, value in record.facts.items():
            if key in METRICS:
                label, unit = METRICS[key]
                facts.append(f'{label}: {number(value)} {unit}'.strip())
        if facts:
            stamp = record.date or 'fecha no disponible'
            optional.append(f"{SOURCES[record.source]} ({stamp}): " + '; '.join(facts) + '.')
    for sentence in dict.fromkeys(optional):
        if sentence not in required and len(answer) + len(sentence) + 1 <= min(max_chars, 3500):
            answer += '\n' + sentence
    return CoachStructuredResponse(response_type=result.response_type, answer=answer,
        decisions=list(result.decisions), evidence=[evidence_wire(e) for e in result.evidence[:4]],
        warnings=warnings, missing_data=[d.reason for d in result.decisions if d.action == 'ask_user'][:4],
        change_proposal=result.change_proposal)
