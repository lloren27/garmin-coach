from __future__ import annotations

import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import store
from app.ai_contracts import CoachStructuredResponse, StructuredChangeProposal
from app.pending_changes import PendingChangeValidator


def response(session_id):
    return {
        'response_type': 'analysis', 'answer': 'Propongo reducir la duración; el plan sigue vigente.',
        'change_proposal': {
            'reason': 'Petición explícita de reducir carga', 'confidence': .8, 'evidence': [],
            'changes': [{'operation': 'ADJUST_DURATION', 'session_id': session_id,
                         'proposed_values': {'duration_min': 30, 'duration_max': 40},
                         'reason': 'Reducir carga de entrenamiento'}],
        },
    }


class PendingChangesTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch.object(store, 'DATABASE_URL', None))
        stack.enter_context(patch.object(store, 'DATA_DIR', root))
        for attr, name in [('TRAINING_PLAN_STATE_FILE', 'plans.json'), ('AI_JOBS_FILE', 'jobs.json')]:
            stack.enter_context(patch.object(store, attr, root / name))
        self.date = (datetime.now(ZoneInfo('Europe/Madrid')).date() + timedelta(days=1)).isoformat()
        self.plan = store.save_training_plan({
            'start_date': self.date, 'end_date': self.date,
            'sessions': [{'date': self.date, 'sport': 'running', 'session_type': 'easy_run',
                          'duration_min': 45, 'duration_max': 55, 'intensity': 'easy'}],
        }, 'owner')
        self.job = store.create_ai_job('owner', 'Estoy cansado, ajusta mañana')
        store.prepare_proposal_context(self.job, {'training_plan'})
        self.payload = response(self.plan['sessions'][0]['id'])

    def complete(self, payload=None, job=None):
        return store.complete_ai_job((job or self.job)['id'], structured_output=payload or self.payload,
                                     output_source='ollama', answer=self.payload['answer'])

    def test_valid_proposal_is_persisted_without_changing_plan(self):
        before = store.TRAINING_PLAN_STATE_FILE.read_bytes()
        result = self.complete()
        self.assertEqual(result['pending_change']['status'], 'PENDING')
        self.assertEqual(result['pending_change']['base_plan_revision'], 1)
        self.assertEqual(store.TRAINING_PLAN_STATE_FILE.read_bytes(), before)
        self.assertEqual(store.load_active_training_plan('owner'), self.plan)

    def test_worker_serialized_defaults_are_normalized_and_retry_equivalent(self):
        wire = CoachStructuredResponse.model_validate(self.payload).model_dump(mode='json')
        result = self.complete(wire)['pending_change']
        self.assertEqual(result['status'], 'PENDING')
        self.assertEqual(self.complete()['pending_change']['id'], result['id'])

    def test_concurrent_retries_return_same_proposal(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.complete(), range(8)))
        self.assertEqual(len({r['pending_change']['id'] for r in results}), 1)
        self.assertEqual(len({r['completed_at'] for r in results}), 1)
        changed = copy.deepcopy(self.payload)
        changed['change_proposal']['confidence'] = .5
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.complete(changed)

    def test_retry_after_plan_replacement_returns_original_proposal(self):
        saved = self.complete()['pending_change']
        store.save_training_plan({'start_date': self.date, 'end_date': self.date, 'sessions': []}, 'owner')
        store.prepare_proposal_context(self.job, set())
        self.assertEqual(self.complete()['pending_change'], saved)

    def test_valid_operations_and_unavailable_evidence(self):
        for operation, values in [('RESCHEDULE', {'date': self.date}),
                                  ('ADJUST_INTENSITY', {'intensity': 'recovery'}),
                                  ('CANCEL_SESSION', {})]:
            job = store.create_ai_job('owner', '/ajustar mañana')
            store.prepare_proposal_context(job, {'training_plan'})
            payload = copy.deepcopy(self.payload)
            payload['change_proposal']['changes'][0].update(operation=operation, proposed_values=values)
            self.assertEqual(self.complete(payload, job)['pending_change']['status'], 'PENDING')
        payload = copy.deepcopy(self.payload)
        payload['change_proposal']['evidence'] = [{'source': 'garmin', 'fact': 'Fatiga registrada'}]
        saved = self.complete(payload)['pending_change']
        self.assertEqual(saved['status'], 'INVALID')
        self.assertIn('unavailable_evidence_source', [e['code'] for e in saved['validation_errors']])

    def test_stale_job_stays_bound_to_original_plan(self):
        replacement = store.save_training_plan({'start_date': self.date, 'end_date': self.date,
                                               'sessions': []}, 'owner')
        result = self.complete()['pending_change']
        self.assertEqual(result['status'], 'INVALID')
        self.assertEqual(result['training_plan_id'], self.plan['id'])
        self.assertNotEqual(result['training_plan_id'], replacement['id'])

    def test_domain_errors_are_audited_and_do_not_write_sessions(self):
        cases = [({'session_id': 'absent'}, 'session_not_found'),
                 ({'operation': 'CANCEL_SESSION'}, 'operation_fields'),
                 ({'operation': 'RESCHEDULE', 'proposed_values': {'date': '2000-01-01'}}, 'past_date')]
        for delta, code in cases:
            job = store.create_ai_job('owner', '/ajustar mañana')
            store.prepare_proposal_context(job, {'training_plan'})
            payload = copy.deepcopy(self.payload)
            payload['change_proposal']['changes'][0].update(delta)
            before = store.TRAINING_PLAN_STATE_FILE.read_bytes()
            result = self.complete(payload, job)['pending_change']
            self.assertEqual(result['status'], 'INVALID')
            self.assertIn(code, [e['code'] for e in result['validation_errors']])
            self.assertEqual(store.TRAINING_PLAN_STATE_FILE.read_bytes(), before)

    def test_structure_errors_and_unauthorized_jobs_create_no_proposal(self):
        for field, value in [('confidence', 1.1), ('confidence', -.1), ('confidence', True)]:
            payload = copy.deepcopy(self.payload)
            payload['change_proposal'][field] = value
            with self.assertRaises(ValueError):
                self.complete(payload)
        payload = copy.deepcopy(self.payload)
        payload['change_proposal']['changes'][0]['operation'] = 'DO_WHATEVER_I_WANT'
        with self.assertRaises(ValueError):
            self.complete(payload)
        job = store.create_ai_job('owner', 'Estoy muy cansado')
        with self.assertRaisesRegex(ValueError, 'authorized'):
            self.complete(job=job)
        self.assertFalse((store.DATA_DIR / 'pending_changes.json').exists())

    def test_job_permission_is_not_elevated_by_voice_or_absent_plan(self):
        voice = store.create_ai_job('owner', '', audio_file_id='voice')
        missing = store.create_ai_job('other', '/ajustar mañana')
        self.assertFalse(voice['requested_change_proposal'])
        self.assertFalse(missing['requested_change_proposal'])
        self.assertEqual(self.job['plan_id'], self.plan['id'])
        self.assertEqual(self.job['plan_revision'], 1)

    def test_effective_permission_false_does_not_erase_original_authorization(self):
        store.save_training_plan({'start_date': self.date, 'end_date': self.date, 'sessions': []}, 'owner')
        context = store.prepare_proposal_context(self.job, set())
        self.assertFalse(context['change_proposal_allowed_now'])
        self.assertEqual(context['training_plan']['id'], self.plan['id'])
        persisted = next(j for j in store.load_ai_jobs_file() if j['id'] == self.job['id'])
        self.assertTrue(persisted['requested_change_proposal'])
        with self.assertRaisesRegex(ValueError, 'execution'):
            self.complete()

    def test_revision_change_after_generation_is_invalid(self):
        state = store.load_training_plan_state_file()
        state['plans'][0]['revision'] = 2
        from app.file_state import atomic_json
        atomic_json(store.TRAINING_PLAN_STATE_FILE, state)
        result = self.complete()['pending_change']
        self.assertEqual(result['status'], 'INVALID')
        self.assertEqual(result['base_plan_revision'], 1)

    def test_file_failure_does_not_complete_job_and_retry_recovers(self):
        from app import proposal_repository
        with patch.object(proposal_repository, 'atomic_json', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.complete()
        job = next(j for j in store.load_ai_jobs_file() if j['id'] == self.job['id'])
        self.assertEqual(job['status'], 'pending')
        with patch.object(store, 'save_ai_jobs_file', side_effect=OSError('crash after insert')):
            with self.assertRaises(OSError):
                self.complete()
        created = json.loads((store.DATA_DIR / 'pending_changes.json').read_text())[0]
        self.assertEqual(self.complete()['pending_change']['id'], created['id'])

    def test_domain_rejects_completed_wrong_owner_wrong_plan_and_duplicate(self):
        cases = [({'status': 'completed'}, 'session_not_modifiable'),
                 ({'completed_activity_id': 'garmin-1'}, 'session_not_modifiable'),
                 ({'owner_id': 'other'}, 'wrong_owner'),
                 ({'training_plan_id': 'other'}, 'wrong_plan'),
                 ({'date': '2000-01-01'}, 'session_in_past')]
        proposal = StructuredChangeProposal.model_validate(self.payload['change_proposal'])
        for changes, expected in cases:
            plan = copy.deepcopy(self.plan)
            plan['sessions'][0].update(changes)
            original = copy.deepcopy(plan)
            errors = PendingChangeValidator().validate(proposal, self.job, plan)
            self.assertIn(expected, [e['code'] for e in errors])
            self.assertEqual(plan, original)
        duplicate = copy.deepcopy(self.payload['change_proposal'])
        duplicate['changes'] *= 2
        errors = PendingChangeValidator().validate(StructuredChangeProposal.model_validate(duplicate), self.job, self.plan)
        self.assertIn('duplicate_session', [e['code'] for e in errors])

    def test_replace_keeps_identity_and_requires_complete_compatible_dose(self):
        payload = copy.deepcopy(self.payload)
        change = payload['change_proposal']['changes'][0]
        change.update(operation='REPLACE_SESSION', proposed_values={'session_type': 'easy_run'})
        errors = PendingChangeValidator().validate(StructuredChangeProposal.model_validate(payload['change_proposal']), self.job, self.plan)
        self.assertIn('replacement_requires_complete_dose', [e['code'] for e in errors])
        change['proposed_values'] = {'sport': 'cycling', 'session_type': 'recovery',
                                    'duration_min': 30, 'duration_max': 30, 'intensity': 'easy',
                                    'target_power_w': 100}
        before = store.TRAINING_PLAN_STATE_FILE.read_bytes()
        saved = self.complete(payload)['pending_change']
        self.assertEqual(saved['status'], 'PENDING')
        self.assertEqual(saved['proposal_payload']['changes'][0]['session_id'], self.plan['sessions'][0]['id'])
        self.assertEqual(store.TRAINING_PLAN_STATE_FILE.read_bytes(), before)

    def test_reschedule_does_not_require_duration_for_distance_based_session(self):
        plan = copy.deepcopy(self.plan)
        session = plan['sessions'][0]
        session.pop('duration_min')
        session.pop('duration_max')
        session.update(session_type='long_run', distance_km=18)
        payload = copy.deepcopy(self.payload['change_proposal'])
        payload['changes'][0].update(operation='RESCHEDULE', proposed_values={'date': self.date})
        errors = PendingChangeValidator().validate(StructuredChangeProposal.model_validate(payload), self.job, plan)
        self.assertEqual(errors, [])

    def test_invalid_replacement_type_is_not_accepted(self):
        payload = copy.deepcopy(self.payload['change_proposal'])
        payload['changes'][0].update(operation='REPLACE_SESSION', proposed_values={
            'sport': 'strength', 'session_type': 'long_run', 'duration_min': 30,
            'duration_max': 30, 'intensity': 'easy'})
        errors = PendingChangeValidator().validate(StructuredChangeProposal.model_validate(payload), self.job, self.plan)
        self.assertIn('invalid_session_type', [e['code'] for e in errors])

    def test_replace_with_rest_is_valid_but_rest_with_training_dose_is_not(self):
        payload = copy.deepcopy(self.payload['change_proposal'])
        values = {'sport': 'recovery', 'session_type': 'rest', 'duration_min': 0,
                  'duration_max': 0, 'intensity': 'rest'}
        payload['changes'][0].update(operation='REPLACE_SESSION', proposed_values=values)
        errors = PendingChangeValidator().validate(StructuredChangeProposal.model_validate(payload), self.job, self.plan)
        self.assertEqual(errors, [])
        values['duration_min'] = values['duration_max'] = 30
        errors = PendingChangeValidator().validate(StructuredChangeProposal.model_validate(payload), self.job, self.plan)
        self.assertIn('rest_has_training_dose', [e['code'] for e in errors])

    def test_api_handles_schema_errors_and_does_not_notify(self):
        import asyncio
        from app import main
        from fastapi import HTTPException
        payload = copy.deepcopy(self.payload)
        payload['change_proposal']['confidence'] = 2
        with patch.object(main, 'require_sync_secret'), patch.object(main, 'send_telegram_message') as send:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(main.complete_ai_job_endpoint(self.job['id'], {
                    'status': 'completed', 'output_source': 'ollama', 'structured_output': payload}))
            self.assertEqual(raised.exception.status_code, 400)
            send.assert_not_called()

    def test_next_job_exposes_only_effective_permission(self):
        from app import main
        with ExitStack() as stack:
            for name in ('require_sync_secret', 'load_sync', 'load_profile', 'load_wattwise', 'load_strength_state'):
                stack.enter_context(patch.object(main, name, return_value=None))
            for name in ('load_checkins', 'load_sync_history', 'load_lab_tests'):
                stack.enter_context(patch.object(main, name, return_value=[]))
            result = main.next_ai_job()
        self.assertTrue(result['context']['change_proposal_allowed_now'])
        self.assertNotIn('requested_change_proposal', result['job'])
        self.assertNotIn('proposal_execution_allowed', result['job'])
        self.assertNotIn('allow_change_proposal', result['job'])
        self.assertEqual(result['context']['training_plan']['id'], self.plan['id'])


class IntentTests(unittest.TestCase):
    def test_conservative_explicit_requests_and_negations(self):
        from app.plan_intent import requests_plan_change
        yes = ['Estoy cansado, ajusta mañana', '/ajustar mañana',
               'Reorganízame la semana porque el jueves no puedo',
               'Estoy muy cansado, ¿me ajustas el entrenamiento de mañana?', 'Sí, ajústalo.']
        no = ['Estoy muy cansado', 'He dormido fatal, ¿qué opinas?', 'No me ajustes el plan',
              'No cambies mañana', '¿Cómo ajustar el plan?', 'Dice "ajusta mañana"',
              '¿Qué significa ajustar el plan?', 'Si estoy cansado, ajusta mañana',
              '¿Cómo ves mi carga esta semana?', 'Sí', 'No quiero que ajustes el plan',
              '¿Puedes explicar cómo ajustar el plan?', 'No, ajusta mañana no',
              'Me pregunto si debes ajustar mañana', 'No, ajusta mañana',
              '/ajustar no cambies mañana', 'Nunca me cambies el plan',
              'Sin ajustar el plan, analiza la carga', 'Quizá ajusta mañana',
              'El entrenador dijo: ajusta mañana', '¿Podrías explicar cómo cambiar el plan?',
              '¿Qué entrenamiento tengo mañana?', 'Reorganizar la semana sería útil']
        for value in yes + no:
            with self.subTest(value=value):
                self.assertEqual(requests_plan_change(value), value in yes)
