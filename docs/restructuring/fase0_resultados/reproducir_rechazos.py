"""Replay captured invalid Ollama outputs through validation and worker fallback, offline."""
import copy
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

import evaluar as audit
from garmin_sync import ai_worker as worker

worker.datetime = audit.FrozenDatetime


def main():
    audit.test_isolation()
    for name in ('E09_ollama_2', 'E10_ollama_1'):
        captured = json.loads((audit.OUT/'ejecuciones/2026-10-04-ollama'/f'{name}.json').read_text())
        case = json.loads((audit.OUT/'casos'/f'{captured["id"]}.json').read_text())
        replies = [entry['response'] for entry in captured['calls']]
        attempts = []
        def generate(messages, **kwargs):
            original = copy.deepcopy(replies[min(len(attempts), len(replies)-1)])
            raw = json.loads(original['message']['content'])
            raw['context_snapshot_id'] = json.loads(messages[1]['content'])['context']['context_snapshot_id']
            original['message']['content'] = json.dumps(raw)
            attempts.append(raw)
            return original
        def call(question, context, **kwargs):
            wire = audit.generate_validated(question, case['estado_inicial'], generate=generate,
                                             now=audit.NOW)
            return worker.CoachRunResult(wire.answer, wire.model_dump(mode='json'), 'ollama')
        extra = case['estado_inicial']['extra_context']
        upstream = {'sync': {'received_at': audit.NOW.isoformat(), 'payload': {
            'generated_at': audit.NOW.isoformat(), 'summary': {'activities': extra.get('recent_activities', [])},
            'wellness': extra.get('wellness', {})}}, 'training_plan': extra.get('training_plan'),
            'checkins': extra.get('checkins', [])}
        completed = []
        events = io.StringIO()
        with patch.object(worker, 'start_telegram_processing_indicator', return_value=None), \
             patch.object(worker, 'stop_telegram_processing_indicator'), \
             patch.object(worker, 'fetch_wattwise_context', return_value=None), \
             patch.object(worker, 'call_ollama', side_effect=call), \
             patch.object(worker, 'complete_coach_job', side_effect=lambda job, value: completed.append(value)), \
             patch.object(worker, 'post_json', side_effect=AssertionError('Unexpected external write')), \
             redirect_stdout(events):
            worker.process_job({'id': 'synthetic-replay', 'text': case['pregunta'],
                                'response_mode': 'text', 'chat_id': 'audit'}, upstream)
        outcome = completed[0]
        checks = {'two_attempts': len(attempts) == 2, 'job_completed': outcome['status'] == 'completed',
                  'fallback_marked': outcome['output_source'] == 'deterministic_fallback',
                  'invalid_structured_output_not_forwarded': outcome['structured_output'] is None,
                  'user_notice': 'No he podido completar el análisis del modelo' in outcome['answer']}
        audit.write(name+'_reserva.json', {'resultado': 'cumple' if all(checks.values()) else 'incumple',
                    'checks': checks, 'completion': outcome, 'events': events.getvalue(),
                    'limitation': 'Replay offline de respuestas reales capturadas; transporte del backend interceptado.'})
        print(name, checks)
    audit.write('guardia_rechazos.json', {'blocked_events': audit.BLOCKED, 'expected_self_checks': 3})


if __name__ == '__main__':
    main()
