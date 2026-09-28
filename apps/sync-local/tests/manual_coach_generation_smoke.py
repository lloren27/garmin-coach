"""Manual, synthetic-only smoke test. Never imports worker/backend I/O or dotenv."""
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
from garmin_sync.coach_generation_pipeline import generate_validated
from garmin_sync.coach_validation import CoachValidationError


def main():
    now = datetime.now(ZoneInfo('Europe/Madrid'))
    tomorrow = (now.date() + timedelta(days=1)).isoformat()
    compact = {'extra_context': {'data_freshness': {'status': 'current'},
        'training_plan': {'sessions': [{'id': 'synthetic-run', 'date': tomorrow, 'status': 'planned',
            'sport': 'running', 'session_type': 'easy_run', 'intensity': 'easy', 'duration_min': 40, 'duration_max': 50}]},
        'recent_activities': [{'id': 'synthetic-activity', 'date': now.date().isoformat(),
            'source': 'garmin', 'km': 8, 'duration_s': 2500}]}}
    cases = [('¿Qué hago mañana? Mantén el plan.', compact, 'keep_plan'),
             ('Hoy recomienda descanso, basándote en la actividad disponible.', compact, 'rest'),
             ('Analiza la actividad registrada sin recomendar entrenamiento.', compact, 'information_only'),
             ('¿Qué debería hacer?', {'extra_context': {}}, 'ask_user')]
    failed = False
    for question, context, expected in cases:
        calls = 0
        def local_ollama(messages, **kwargs):
            nonlocal calls
            calls += 1
            result = httpx.post('http://127.0.0.1:11434/api/chat', timeout=180, json={
                'model': 'garmin-coach:9b', 'messages': messages, 'stream': False, 'think': False,
                'format': kwargs['response_schema'], 'options': {'temperature': 0, 'num_ctx': 32768, 'num_predict': 1400}})
            result.raise_for_status()
            return result.json()
        started = time.monotonic()
        try:
            wire = generate_validated(question, context, generate=local_ollama, now=now)
            assert calls <= 2
            assert any(d.action == expected for d in wire.decisions), 'Unexpected action'
            if expected == 'keep_plan':
                assert wire.decisions[0].duration_min == 40
                assert '40 a 50 minutos' in wire.answer
            print(json.dumps({'case': expected, 'ok': True, 'calls': calls, 'seconds': round(time.monotonic()-started, 1)}), flush=True)
        except (CoachValidationError, AssertionError) as exc:
            failed = True
            print(json.dumps({'case': expected, 'ok': False, 'error': type(exc).__name__, 'calls': calls}), flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
