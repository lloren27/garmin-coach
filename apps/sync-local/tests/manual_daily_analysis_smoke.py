"""Local Ollama regression with synthetic IDs; does not access or modify backend jobs."""
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx
from garmin_sync.coach_generation_pipeline import generate_validated


def main():
    context = {'extra_context': {'data_freshness': {'status': 'current'}, 'recent_activities': [
        dict(id='synthetic-run', date='2026-09-29', sport='running', duration_s=3631,
             km=12.01, avg_hr=133, max_hr=166),
        dict(id='synthetic-bike', date='2026-09-29', sport='cycling', duration_s=3777,
             km=23.15, avg_hr=86, max_hr=120, avg_power=143)],
        'wellness': {'effective': {'date': '2026-09-29',
            'atl': {'source': 'zepp', 'value': 1}, 'ctl': {'source': 'zepp', 'value': 0}}}}}

    def generate(messages, **kwargs):
        response = httpx.post('http://127.0.0.1:11434/api/chat', timeout=180, json={
            'model': 'garmin-coach:9b', 'messages': messages, 'stream': False, 'think': False,
            'format': kwargs['response_schema'],
            'options': {'temperature': 0, 'num_ctx': 32768, 'num_predict': 1400}})
        response.raise_for_status()
        return response.json()

    wire = generate_validated('/coach que me puedes analizar del entrenamiento de hoy', context,
        generate=generate, now=datetime(2026, 9, 29, 22, tzinfo=ZoneInfo('Europe/Madrid')))
    print(wire.answer)
    assert '5:02 min/km' in wire.answer and '22,1 km/h' in wire.answer
    assert 'no permite una conclusión adicional' not in wire.answer


if __name__ == '__main__':
    main()
