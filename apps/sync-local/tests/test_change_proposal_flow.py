import json
import unittest
from unittest.mock import patch
import httpx
from garmin_sync import ai_worker as worker


class ProposalBoundaryTests(unittest.TestCase):
    def test_exhausted_completion_retries_do_not_send_failed_status(self):
        seen = []
        def post(path, body):
            seen.append(body.copy())
            raise httpx.ReadTimeout('ack lost')
        with patch.object(worker, 'post_json', side_effect=post), \
             patch.object(worker, 'start_telegram_processing_indicator', return_value=None), \
             patch.object(worker, 'stop_telegram_processing_indicator'), \
             patch.object(worker, 'fetch_wattwise_context', return_value=None), \
             patch.object(worker, 'call_ollama', return_value=worker.CoachRunResult('Respuesta de análisis completa.', None, 'deterministic_fallback')):
            with self.assertRaises(httpx.ReadTimeout):
                worker.process_job({'id': 'job', 'text': 'Ajusta mañana'}, {})
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(item['status'] == 'completed' for item in seen))

    def test_completion_retries_same_payload_without_marking_failed(self):
        payload = {'status': 'completed', 'structured_output': {'change_proposal': 'same'}}
        seen = []
        def post(path, body):
            seen.append(body.copy())
            if len(seen) == 1:
                raise httpx.ReadTimeout('ack lost')
            return {'ok': True}
        with patch.object(worker, 'post_json', side_effect=post):
            worker.complete_coach_job('job', payload)
        self.assertEqual(seen, [payload, payload])

    def test_context_false_rejects_proposal_even_if_schema_ignored(self):
        compact = worker.compact_context({'change_proposal_allowed_now': False})
        self.assertEqual(worker._response_schema(compact)['properties']['change_proposal']['type'], 'null')
        raw = {'response_type': 'analysis', 'answer': 'Para hoy propongo reducir la carga del entrenamiento.',
               'change_proposal': {'reason': 'Petición de ajuste explícita', 'confidence': .8, 'evidence': [],
                                   'changes': [{'operation': 'CANCEL_SESSION', 'session_id': 's',
                                                'proposed_values': {}, 'reason': 'Necesita más recuperación'}]}}
        with self.assertRaisesRegex(ValueError, 'not authorized'):
            worker._validate_ollama_response({'response': json.dumps(raw)}, compact)
        allowed = worker.compact_context({'change_proposal_allowed_now': True})
        parsed, _ = worker._validate_ollama_response({'response': json.dumps(raw)}, allowed)
        self.assertEqual(parsed.change_proposal.changes[0].session_id, 's')

    def test_missing_or_non_boolean_permission_is_denied(self):
        for value in (None, 'true', 1):
            compact = worker.compact_context({'change_proposal_allowed_now': value})
            self.assertEqual(worker._response_schema(compact)['properties']['change_proposal']['type'], 'null')
