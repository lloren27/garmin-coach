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
METRICS.update({
    'intensity_factor': ('factor de intensidad', ''), 'variability_index': ('índice de variabilidad', ''),
    'moving_min': ('duración en movimiento', 'minutos'), 'avg_power_w': ('potencia media', 'W'),
    'vt1_hr': ('pulso del primer umbral', 'lpm'), 'vt2_hr': ('pulso del segundo umbral', 'lpm'),
    'lactate_hr': ('pulso del umbral de lactato', 'lpm'), 'sessions_7d': ('sesiones de fuerza en 7 días', ''),
    'sessions_28d': ('sesiones de fuerza en 28 días', ''), 'sets_7d': ('series de fuerza en 7 días', ''),
    'volume_kg_7d': ('volumen de fuerza en 7 días', 'kg'), 'load_score_7d': ('carga muscular en 7 días', ''),
    'lower_sets_7d': ('series de tren inferior en 7 días', ''), 'hard_lower_sets_7d': ('series intensas de tren inferior en 7 días', ''),
    'today_sessions': ('sesiones de fuerza en la fecha indicada', ''), 'today_sets': ('series en la fecha indicada', ''),
    'today_load_score': ('carga muscular en la fecha indicada', ''), 'acute_chronic_ratio': ('relación de carga aguda y crónica', ''),
    'load_ratio': ('relación de carga del proveedor', ''), 'acute_load': ('carga aguda del proveedor', ''),
    'sleep_seconds': ('sueño', 's'), 'deep_seconds': ('sueño profundo', 's'), 'light_seconds': ('sueño ligero', 's'),
    'rem_seconds': ('sueño REM', 's'), 'awake_seconds': ('vigilia', 's'), 'last_night_avg': ('VFC nocturna', 'ms'),
    'weekly_avg': ('VFC semanal', 'ms'), 'baseline_low': ('referencia inferior VFC', 'ms'),
    'baseline_high': ('referencia superior VFC', 'ms'), 'charged': ('Body Battery recargada', ''),
    'drained': ('Body Battery consumida', ''), 'current': ('Body Battery', ''),
})
SOURCES = {'zepp': 'Zepp', 'garmin': 'Garmin', 'wattwise': 'Wattwise', 'backend': 'cálculos del sistema',
           'strava': 'Strava', 'unknown': 'origen desconocido',
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
    text = ', '.join(parts) + '.'
    if decision.source == 'training_plan':
        text += ' ' + decision.reason
    return text


def elapsed(seconds):
    hours, remainder = divmod(round(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return (f'{hours} h {minutes:02d} min {seconds:02d} s' if hours
            else f'{minutes} min {seconds:02d} s')


def activity_analysis(result, snapshot):
    """Describe selected, dated observations; never infer physiological intensity."""
    if result.response_type != 'analysis' or not all(d.action == 'information_only' for d in result.decisions):
        return []
    observed_dates = {day.isoformat() for day in snapshot.intent.observed_dates}
    rows = [e for e in result.evidence if e.kind == 'activity' and e.date
            and (not observed_dates or e.date in observed_dates)]
    lines = []
    for row in rows:
        facts = row.facts
        duration, distance = facts.get('duration_s'), facts.get('distance_km')
        details = []
        if duration is not None and duration > 0: details.append(elapsed(duration))
        if distance is not None and distance >= 0: details.append(f'{number(distance)} km')
        if duration and duration > 0 and distance and distance > 0:
            if row.sport == 'running':
                minutes, seconds = divmod(round(duration / distance), 60)
                details.append(f'ritmo calculado: {minutes}:{seconds:02d} min/km')
            elif row.sport == 'cycling':
                details.append(f'velocidad calculada: {number(round(distance * 3600 / duration, 1))} km/h')
        for key in ('avg_hr', 'max_hr', 'avg_power'):
            if key in facts:
                label, unit = METRICS[key]
                details.append(f'{label}: {number(facts[key])} {unit}')
        if not details: continue
        sport = SPORTS.get(row.sport, {'swimming': 'natación', 'walking': 'caminata'}.get(row.sport, 'actividad'))
        lines.append(f'{row.date} — {sport} ({SOURCES[row.source]}): ' + '; '.join(details) + '.')
        previous = [e for e in result.evidence if e.kind == 'activity' and e.date and e.date < row.date
                    and row.sport and e.sport == row.sport and e.source == row.source
                    and e.facts.get('duration_s', 0) > 0]
        if duration and duration > 0 and previous:
            reference = max(previous, key=lambda e: e.date)
            delta = duration - reference.facts['duration_s']
            lines.append(f'Frente a la sesión de {reference.date} del mismo deporte y proveedor, '
                         + (f'la duración aumentó {elapsed(delta)}.' if delta > 0 else
                            f'la duración disminuyó {elapsed(-delta)}.' if delta < 0 else 'la duración fue igual.')
                         + ' Es una comparación de volumen, sin equiparar recorrido ni condiciones.')
    if lines:
        lines.append('El ritmo y la velocidad calculados usan la duración registrada; pueden incluir pausas. '
                     'El pulso medio y máximo por sí solos no determinan tus zonas ni la intensidad de la sesión. '
                     'Para valorar el esfuerzo se necesitan referencias personales vinculadas al deporte y tiempo en zonas o sensaciones.')
    return lines


def render_generation(result: ResolvedGeneration, snapshot: ContextSnapshot, *, max_chars: int) -> CoachStructuredResponse:
    analysis = activity_analysis(result, snapshot)
    required = analysis or [decision_text(d) for d in result.decisions]
    warnings = []
    labels = {'provider_error':'error del proveedor', 'not_configured':'no configurado',
              'stale':'datos antiguos', 'partial':'cobertura parcial', 'no_activity':'sin actividad en el periodo consultado'}
    status_lines = [f"{provider}: {labels[status['state']]}. Último intento: {status.get('last_attempt_at') or 'desconocido'}."
                    for provider, status in result_statuses(snapshot)]
    if status_lines:
        warnings.append(' '.join(status_lines))
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
    suppressed = {'DATA_STALE'} | ({'OBSERVED_ACTIVITY', 'OBSERVED_WELLNESS', 'ANALYSIS_LIMITED'} if analysis else set())
    optional = [REASONS[c.code] for c in result.conclusions if c.code not in suppressed]
    for record in result.evidence[:4]:
        if analysis:
            continue  # The analysis already presents the relevant observations with their dates.
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
        decisions=[d.model_copy(update={'reason': 'Análisis descriptivo de las actividades registradas.'})
                   if analysis else d for d in result.decisions],
        evidence=[evidence_wire(e) for e in result.evidence[:4]],
        warnings=warnings, missing_data=[d.reason for d in result.decisions if d.action == 'ask_user'][:4],
        change_proposal=result.change_proposal)


def result_statuses(snapshot):
    return [(key, value) for key, value in snapshot.provider_status.items()
            if value['state'] in {'provider_error', 'not_configured', 'stale', 'partial', 'no_activity'}]
