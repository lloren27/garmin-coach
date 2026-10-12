"""Read-only Telegram navigation and operational presentation."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .queue_status import QueueSnapshot



HELP_COMMANDS = (
    ('/coach', 'Pregunta al entrenador local por texto o voz'),
    ('/plan', 'Consulta el plan vigente, sin modificarlo'),
    ('/plan nuevo', 'Crea explícitamente un plan semanal'),
    ('/plan_semana', 'Alias de consulta del plan'),
    ('/sync', 'Solicita sincronización; también /sync zepp y /sync cmf'),
    ('/estado', 'Fuentes de datos y estado de tu cola'),
    ('/registro', 'Guía para registrar fuerza, molestias, perfil y pruebas'),
    ('/help', 'Ayuda breve; /help comandos muestra esta lista'),
    ('/hoy', 'Vista deportiva local del día'),
    ('/semana', 'Balance y plan mostrados por la ruta local vigente'),
    ('/ultima', 'Última actividad, respuesta local'),
    ('/proximo', 'Recomendación de la ruta local vigente'),
    ('/fatiga', 'Valoración local de fatiga'),
    ('/salud', 'Recuperación y métricas disponibles, ruta local'),
    ('/carga', 'Carga por deporte, ruta local'),
    ('/running', 'Analítica local de carrera'),
    ('/correr', 'Alias de /running'),
    ('/carga_running', 'Alias de /running'),
    ('/tendencia', 'Evolución semanal, ruta local'),
    ('/feedback', 'Valoración local de las actividades del día'),
    ('/ajustar', 'Solicita una propuesta al entrenador; no aplica cambios por sí solo'),
    ('/bici', 'Resumen local de ciclismo'),
    ('/potencia', 'Analítica local Wattwise'),
    ('/wattwise', 'Alias de /potencia'),
    ('/malaga', 'Preparación de maratón, ruta local'),
    ('/fuerza', 'Consulta y registro explícito de fuerza'),
    ('/checkin', 'Guía para registrar molestias y notas'),
    ('/perfil', 'Consulta del perfil; con argumentos registra valores'),
    ('/prueba_esfuerzo', 'Guía de subida de PDF/DOCX'),
    ('/pruebas', 'Historial de pruebas'),
    ('/ver_prueba', 'Consulta una prueba'),
    ('/zonas', 'Consulta zonas actuales'),
    ('/aplicar_prueba', 'Aplica explícitamente la propuesta de una prueba'),
    ('/corregir_prueba', 'Corrige una prueba pendiente'),
    ('/descartar_prueba', 'Descarta una prueba pendiente'),
    ('/status', 'Resumen de sincronización compatible'),
    ('/syncinfo', 'Información de la última sincronización y petición'),
)


def format_help(*, detailed: bool = False) -> str:
    if detailed:
        return 'Comandos disponibles\n' + '\n'.join(f'{cmd} — {description}' for cmd, description in HELP_COMMANDS)
    return ('Garmin Coach\nEscribe tu pregunta o envía una nota de voz.\n'
            '/coach — Pregunta al entrenador\n/plan — Consulta tu plan\n'
            '/sync — Solicita actualización\n/estado — Datos y cola de consultas\n'
            '/registro — Fuerza, molestias, perfil y pruebas\n/help — Ayuda\n\n'
            'Ejemplo: «Analiza mi entrenamiento de hoy».\n'
            'Los comandos anteriores siguen disponibles: /help comandos.')


def format_registration_help(topic: str = '') -> str:
    guides = {
        'fuerza': 'Registro de fuerza\nIniciar: /fuerza iniciar A\nAñadir: /fuerza add sentadilla 60kg 8/8 rir2\nConsultar: /fuerza actual\nCerrar: /fuerza fin',
        'molestias': 'Molestias y notas\nUsa /checkin para ver la sintaxis.\nEjemplo: /checkin dolor gemelo derecho',
        'perfil': 'Perfil\nConsultar: /perfil\nRegistrar: /perfil peso 72\nUsa /perfil ayuda para ver los campos admitidos.',
        'pruebas': 'Pruebas de esfuerzo\nGuía de subida: /prueba_esfuerzo\nHistorial: /pruebas\nRevisar: /ver_prueba\nAplicar: /aplicar_prueba\nCorregir: /corregir_prueba\nDescartar: /descartar_prueba',
    }
    return guides.get(topic.strip().lower(), '¿Qué quieres registrar?\n/registro fuerza\n/registro molestias\n/registro perfil\n/registro pruebas\nAbrir esta guía no guarda datos.')


MADRID = ZoneInfo('Europe/Madrid')


def _stamp(value, now):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp > now:
            return None
        return stamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _date(value, now, *, age=False):
    stamp = _stamp(value, now)
    if stamp is None:
        return 'fecha no disponible o no fiable'
    text = stamp.astimezone(MADRID).strftime('%d/%m/%Y %H:%M %Z')
    if age:
        minutes = int((now.astimezone(timezone.utc) - stamp).total_seconds() // 60)
        text += f' (hace {minutes} min)'
    return text


def _mapping(value):
    return value if isinstance(value, dict) else {}


def format_operational_status(sync: dict | None, sync_request: dict | None,
                              queue: 'QueueSnapshot', *, now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError('timezone-aware now required')
    sync, sync_request = _mapping(sync), _mapping(sync_request)
    payload = _mapping(sync.get('payload'))
    lines = ['Estado Garmin Coach — hora de España',
             'Datos generados: ' + _date(payload.get('generated_at'), now, age=True),
             'Recibidos: ' + _date(sync.get('received_at'), now)]
    request_status = sync_request.get('status')
    labels = {'pending':'pendiente', 'running':'en ejecución', 'completed':'completada', 'failed':'fallida'}
    lines.append('Petición de sincronización: ' + labels.get(request_status, 'no disponible'))
    wellness = _mapping(_mapping(payload.get('wellness')).get('provider_status'))
    activities = _mapping(payload.get('activity_provider_status'))
    errors = ('auth_error','network_error','api_error','invalid_data','error','unavailable')
    for scope, states, providers in [('actividades',activities,('garmin','strava','zepp')), ('bienestar',wellness,('garmin','zepp'))]:
        for provider in providers:
            raw = _mapping(states.get(provider))
            status = raw.get('status')
            if status == 'ok' and isinstance(raw.get('records_received'), int) and not isinstance(raw.get('records_received'), bool) and raw['records_received'] >= 0:
                label = ('sin actividad' if scope == 'actividades' else 'sin datos') if raw['records_received'] == 0 else 'datos disponibles'
            elif status == 'ok':
                label = 'estado no disponible'
            elif status in errors:
                label = 'error del proveedor'
            elif status in ('disabled','not_configured'):
                label = 'sin configurar'
            elif status == 'partial':
                label = 'datos parciales'
            else:
                label = 'estado no disponible'
            name = {'garmin':'Garmin','strava':'Strava','zepp':'Zepp'}[provider]
            lines.append(f'{name} · {scope}: {label}')
            for key, title in [('last_attempt_at','Intento'),('last_success_at','Éxito')]:
                if raw.get(key):
                    lines.append(f'  {title}: ' + _date(raw[key], now))
            stamp = _stamp(raw.get('last_success_at'), now)
            if stamp and stamp.astimezone(MADRID).date() < now.astimezone(MADRID).date():
                lines.append('  Datos de un día anterior')
            # Period metadata is a calendar date, never arbitrary error text.
            period = []
            for key in ('period_start','period_end'):
                value = raw.get(key)
                try:
                    period.append(date.fromisoformat(value).isoformat())
                except (ValueError, TypeError):
                    period.append('no disponible')
            if any(v != 'no disponible' for v in period):
                lines.append('  Periodo: ' + ' — '.join(period))
    if not queue or not queue.get('available'):
        lines.append('Cola no disponible')
    else:
        counts = queue['counts']
        lines.extend([f"Pendientes: {counts['pending']}", f"En ejecución: {counts['running']}"])
        for key, label in [('oldest_pending_at','Pendiente más antiguo'), ('oldest_running_claimed_at','Recogida más antigua en ejecución'), ('last_completed_at','Última finalización correcta'), ('last_failed_at','Último fallo')]:
            invalid = queue['invalid_date_counts'][key]
            suffix = f' — entre fechas disponibles; {invalid} fecha(s) no fiable(s)' if invalid else ''
            lines.append(label + ': ' + _date(queue.get(key),now,age=key=='oldest_pending_at') + suffix)
        if not counts['pending']:
            lines.append('No hay consultas pendientes.')
    lines.append('Estas señales son históricas; no confirman que el Mac esté disponible ahora.')
    return '\n'.join(lines)
