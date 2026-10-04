"""Additional synthetic probes; reuse the audit isolation and product functions."""
import copy
import io
import json
import tempfile
import time
from datetime import date, datetime, timedelta
from contextlib import redirect_stdout
from unittest.mock import patch
from zoneinfo import ZoneInfo

import evaluar as audit
from garmin_sync import sync, ai_worker as worker
from garmin_sync.zepp_provider import ZeppProvider
from garmin_sync.wellness_models import deduplicate_sleep_sessions

tempfile.tempdir = str(audit.TMP)
worker.datetime = audit.FrozenDatetime


class ZeppClient:
    def __init__(self, sleep_by_day=None, band_by_day=None):
        self.sleep_by_day = sleep_by_day or {}
        self.band_by_day = band_by_day or {}
        self.sleep_queries = []

    def get_sleep(self, day):
        self.sleep_queries.append(day)
        return self.sleep_by_day.get(day, {})

    def get_band_data(self, day):
        return self.band_by_day.get(day, {})

    def get_steps(self, day):
        return {}

    def __getattr__(self, name):
        if name in ('get_stress', 'get_training_load', 'get_phn', 'get_sport_load', 'get_vo2_max'):
            return lambda *args: []
        raise AttributeError(name)


def collect(client, today):
    provider = ZeppProvider('synthetic-token', 'synthetic-owner')
    provider._client = client
    with patch.object(sync, 'TODAY', today), patch.dict(sync.os.environ, {'ZEPP_SYNC_LOOKBACK_DAYS': '2'}), \
            patch.object(sync, 'compact_garmin_wellness', return_value={}):
        return sync.collect_wellness_history(None, sync._wellness_dates(), provider, 'Europe/Madrid')


def late_sleep():
    _, store = audit.store_setup()
    day = '2026-10-03'
    sleep = {'start': '2026-10-02T23:30:00+02:00', 'end': '2026-10-03T07:00:00+02:00',
             'total_minutes': 450, 'sleep_score': 78}
    client = ZeppClient()
    rounds = []
    for today, value in [(date(2026, 10, 3), None), (date(2026, 10, 4), 78), (date(2026, 10, 4), 82)]:
        if value is not None:
            client.sleep_by_day[day] = {**sleep, 'sleep_score': value}
        client.sleep_queries.clear()
        wellness = collect(client, today)
        store.upsert_wellness_days({'wellness': wellness}, owner_id='audit-late')
        rows = store.load_wellness_history(10, owner_id='audit-late')
        rounds.append({'today': today.isoformat(), 'queries': list(client.sleep_queries),
                       'target': copy.deepcopy(rows[day]), 'stored_days': sorted(rows)})
    score = rounds[-1]['target']['sources']['zepp']['sleep']['score']
    checks = {'requeries_previous_day': all(day in r['queries'] for r in rounds),
              'initially_no_sleep': not rounds[0]['target']['sources']['zepp'].get('sleep'),
              'late_sleep_received': rounds[1]['target']['sources']['zepp']['sleep']['score'] == 78,
              'correction_applied': score == 82,
              'no_duplicate_day': len(rounds[-1]['stored_days']) == len(set(rounds[-1]['stored_days']))}
    return audit.result(all(checks.values()), {'checks': checks, 'rounds': rounds},
                        'Cliente Zepp sustituido; fecha seleccionada, normalizador, resolución y almacén de ficheros reales. PostgreSQL y cloud real fuera de alcance.')


def dst_sleep():
    # Absolute timestamp difference is the oracle, including the repeated hour.
    start = datetime.fromisoformat('2026-10-24T21:30:00+00:00')
    end = datetime.fromisoformat('2026-10-25T06:30:00+00:00')
    expected = round((end.timestamp() - start.timestamp()) / 60)
    band = {'summary': {'slp': {'st': int(start.timestamp()), 'ed': int(end.timestamp()),
                                'ss': 78, 'dp': 90, 'lt': 330}}}
    client = ZeppClient(band_by_day={'2026-10-24': band})
    provider = ZeppProvider('synthetic-token', 'synthetic-owner')
    provider._client = client
    rows, status = provider.fetch_days([date(2026, 10, 24), date(2026, 10, 25)])
    observed = rows['2026-10-25'].data.sleep
    checks = {'assigned_to_wake_date': rows['2026-10-24'].data.sleep is None and observed is not None,
              'correct_elapsed_minutes': observed.total_minutes == expected,
              'deduplicate_same_sleep': len(deduplicate_sleep_sessions([observed, observed])) == 1}
    _, store = audit.store_setup()
    wellness = collect(client, date(2026, 10, 25))
    for _ in range(2):
        store.upsert_wellness_days({'wellness': wellness}, owner_id='audit-dst')
    saved = store.load_wellness_history(10, owner_id='audit-dst')
    checks['persistent_wake_date'] = saved['2026-10-25']['sources']['zepp']['sleep']['end'] == observed.end
    return audit.result(all(checks.values()), {'checks': checks, 'expected_minutes_from_utc': expected,
                        'observed_sleep': observed.to_dict(), 'provider_status': status,
                        'persisted_dates': sorted(saved)}, 'Zepp band fallback sintético; no cambio de reloj del sistema.')


def context_loss():
    upstream = {'sync': {'received_at': audit.NOW.isoformat(), 'payload': {
        'generated_at': audit.NOW.isoformat(), 'summary': {'activities': [
            {'id': 'synthetic-st1', 'source': 'strava', 'source_device': 'CMF Watch 3 Pro',
             'date': '2026-10-03', 'sport': 'running', 'km': 8, 'duration_s': 2500}]},
        'activity_provider_status': {'strava': {'status': 'ok'}, 'garmin': {'status': 'network_error'}},
        'wellness': {'schema_version': 2, 'effective': {'date': '2026-10-01',
            'resting_hr': {'source': 'zepp', 'value': 45}},
            'provider_status': {'zepp': {'status': 'auth_error', 'last_success_at': '2026-10-01'}}}}},
        'wattwise_live': {'status': 'unavailable'}}
    compact = worker.compact_context(upstream)
    snapshot = audit.build_snapshot('Valora hoy', compact, now=audit.NOW).public_context()
    observed = {'strava_source': next(e['source'] for e in snapshot['available_evidence'] if e['kind'] == 'activity'),
                'has_activity_provider_status_in_compact': 'activity_provider_status' in compact['extra_context'],
                'has_wellness_provider_status_in_snapshot': 'provider_status' in snapshot,
                'freshness': snapshot['freshness']}
    preserved = (observed['strava_source'] == 'strava' and
                 observed['has_activity_provider_status_in_compact'] and
                 observed['has_wellness_provider_status_in_snapshot'])
    return {'resultado': 'cumple' if preserved else 'incumple', 'entrada': upstream, 'compact': compact, 'snapshot': snapshot,
            'observado': observed,
            'limitacion': 'Traza sintética; muestra tres pérdidas, no atestigua un trabajo de producción.'}


def fallback_and_voice():
    # Execute process_job itself with in-memory transport and deterministic model failure.
    captures = []
    outputs = []
    def capture(job_id, payload):
        captures.append(copy.deepcopy(payload))
        return {'ok': True}
    with patch.object(worker, 'start_telegram_processing_indicator', return_value=None), \
         patch.object(worker, 'stop_telegram_processing_indicator'), \
         patch.object(worker, 'fetch_wattwise_context', return_value=None), \
         patch.object(worker, 'download_telegram_audio', return_value=audit.TMP/'synthetic.ogg'), \
         patch.object(worker, 'transcribe_audio', return_value='Analiza mi entrenamiento de hoy'), \
         patch.object(worker, 'complete_coach_job', side_effect=capture), \
         patch.object(worker, 'post_json', side_effect=AssertionError('Unexpected external operation')), \
         patch.object(worker, 'call_ollama', side_effect=ValueError('synthetic invalid model output')) as model:
        for voice in (False, True):
            job = {'id': 'synthetic-audit', 'chat_id': 'audit', 'response_mode': 'text',
                   'text': '' if voice else 'Analiza mi entrenamiento de hoy'}
            if voice:
                job['audio_file_id'] = 'synthetic-voice'
            with redirect_stdout(io.StringIO()):
                worker.process_job(job, {})
            outputs.append({'question': model.call_args.args[0], 'context': model.call_args.args[1],
                            'completion': captures[-1]})
    checks = {'same_question': outputs[0]['question'] == outputs[1]['question'],
              'same_context': outputs[0]['context'] == outputs[1]['context'],
              'completed': all(x['completion']['status'] == 'completed' for x in outputs),
              'fallback_marked': all(x['completion'].get('output_source') == 'deterministic_fallback' for x in outputs),
              'answer_present': all(x['completion'].get('answer') for x in outputs)}
    return audit.result(all(checks.values()), {'checks': checks, 'outputs': outputs},
                        'Texto y voz transcrita con transporte interceptado. No prueba precisión Whisper ni envío Telegram.')


def main():
    audit.test_isolation()
    for name, operation in [('E05_reconsulta', late_sleep), ('E16_sueno_cambio_horario', dst_sleep),
                            ('contexto_extremo_a_extremo', context_loss), ('fallback_y_voz', fallback_and_voice)]:
        started = time.monotonic()
        try:
            record = operation()
        except Exception:
            import traceback
            record = {'resultado': 'no evaluable', 'error_evaluador': traceback.format_exc()}
        record['seconds'] = round(time.monotonic()-started, 3)
        audit.write(name+'.json', record)
        print(name, record['resultado'])
    audit.write('guardia_ampliadas.json', {'blocked_events': audit.BLOCKED, 'expected_self_checks': 3})


if __name__ == '__main__':
    main()
