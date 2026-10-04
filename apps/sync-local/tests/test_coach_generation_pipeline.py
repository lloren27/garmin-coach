import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from test_coach_generation_context import compact_fixture, NOW
from garmin_sync.coach_generation_pipeline import generate_validated
from garmin_sync.coach_validation import CoachValidationError


def valid_reply(messages, **kwargs):
    snapshot = json.loads(messages[1]['content'])['context']
    return {'message': {'content': json.dumps(dict(schema_version='1',
        context_snapshot_id=snapshot['context_snapshot_id'], response_type='single_session',
        decisions=[{'action': 'keep_plan', 'session_id': 'run'}, {'action': 'keep_plan', 'session_id': 'bike'}],
        conclusions=[], evidence_refs=[]))}, 'done_reason': 'stop'}


class PipelineTests(unittest.TestCase):
    def run_case(self, mutate):
        self.requests = []
        def generate(messages, **kwargs):
            self.requests.append((messages, kwargs))
            reply = valid_reply(messages, **kwargs)
            return mutate(reply, len(self.requests))
        self.output = io.StringIO()
        with patch.dict(os.environ, {'COACH_INTENT_ENFORCEMENT': ''}), redirect_stdout(self.output):
            return generate_validated('qué toca mañana', compact_fixture(), generate=generate, job_id='job1', now=NOW)

    def test_success_is_rendered_from_one_validated_generation(self):
        wire = self.run_case(lambda reply, attempt: reply)
        self.assertIn('40 a 50 minutos', wire.answer)
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn('answer', self.requests[0][1]['response_schema']['properties'])
        schema = self.requests[0][1]['response_schema']
        self.assertTrue(all('component_index' not in schema['$defs'][name].get('required', [])
                            for name in schema['$defs'] if 'component_index' in schema['$defs'][name].get('properties', {})))
        self.assertNotIn('component_index', self.requests[0][0][0]['content'])

    def test_fixed_clarification_bypasses_generation_when_enforcement_is_on(self):
        generate = unittest.mock.Mock(side_effect=AssertionError('must not invoke model'))
        with patch.dict(os.environ, {'COACH_INTENT_ENFORCEMENT': 'on'}):
            wire = generate_validated('¿Qué hago?', compact_fixture(), generate=generate, now=NOW)
        self.assertEqual(generate.call_count, 0)
        self.assertIn('día quieres', wire.answer)
        self.assertEqual(wire.decisions[0].action, 'ask_user')

    def test_unrecognized_paraphrase_is_routed_to_restricted_generation(self):
        requests = []
        def generate(messages, **kwargs):
            requests.append((messages, kwargs))
            context = json.loads(messages[1]['content'])['context']
            reply = dict(schema_version='1', context_snapshot_id=context['context_snapshot_id'],
                         response_type='information', decisions=[{'action': 'ask_user', 'component_index': 0}],
                         conclusions=[], evidence_refs=[])
            return {'message': {'content': json.dumps(reply)}, 'done_reason': 'stop'}
        with patch.dict(os.environ, {'COACH_INTENT_ENFORCEMENT': 'on'}), redirect_stdout(io.StringIO()):
            wire = generate_validated('¿Qué opinas del domingo?', compact_fixture(), generate=generate, now=NOW)
        self.assertEqual(len(requests), 1)
        self.assertEqual(wire.decisions[0].action, 'ask_user')
        item_schema = requests[0][1]['response_schema']['properties']['decisions']['items']
        scoped = next(rule['then'] for rule in item_schema['allOf']
                      if rule.get('if', {}).get('properties', {}).get('component_index', {}).get('const') == 0)
        self.assertEqual(set(scoped['properties']['action']['enum']), {'ask_user', 'information_only'})

    def test_unauthorized_change_request_returns_fixed_answer_without_model(self):
        generate = unittest.mock.Mock(side_effect=AssertionError('must not invoke model'))
        with patch.dict(os.environ, {'COACH_INTENT_ENFORCEMENT': 'on'}):
            wire = generate_validated('Cambia la sesión de mañana', compact_fixture(), generate=generate, now=NOW)
        self.assertEqual(generate.call_count, 0)
        self.assertIn('autorización', wire.answer.lower())
        self.assertIsNone(wire.change_proposal)

    def test_enforced_mixed_generation_returns_one_scoped_decision_per_component(self):
        requests = []
        def generate(messages, **kwargs):
            requests.append((messages, kwargs))
            context = json.loads(messages[1]['content'])['context']
            reply = dict(schema_version='1', context_snapshot_id=context['context_snapshot_id'],
                         response_type='single_session', decisions=[
                             {'action': 'information_only', 'component_index': 0, 'date': '2026-09-25'},
                             {'action': 'rest', 'component_index': 1, 'date': '2026-09-26',
                              'evidence_refs': ['activity:123']}], conclusions=[], evidence_refs=[])
            return {'message': {'content': json.dumps(reply)}, 'done_reason': 'stop'}

        with patch.dict(os.environ, {'COACH_INTENT_ENFORCEMENT': 'on'}), redirect_stdout(io.StringIO()):
            wire = generate_validated('analiza hoy y dime qué hacer mañana', compact_fixture(),
                                      generate=generate, now=NOW)

        self.assertEqual([(d.component_index, d.date.isoformat()) for d in wire.decisions], [
            (0, '2026-09-25'), (1, '2026-09-26'),
        ])
        context = json.loads(requests[0][0][1]['content'])['context']
        self.assertEqual(context['observed_dates'], ['2026-09-25'])
        self.assertEqual(context['advice_dates'], ['2026-09-26'])

    def test_repair_contains_rejected_decision_and_specific_hint(self):
        def mutate(reply, attempt):
            if attempt == 1:
                raw = json.loads(reply['message']['content'])
                raw['decisions'] = [{'action': 'rest', 'intensity': 'threshold', 'evidence_refs': ['activity:123']}]
                reply['message']['content'] = json.dumps(raw)
            return reply
        wire = self.run_case(mutate)
        self.assertIn('40 a 50 minutos', wire.answer)
        repair = json.loads(self.requests[1][0][-1]['content'])
        self.assertEqual(repair['rejected_output']['decisions'][0]['intensity'], 'threshold')
        self.assertEqual(repair['validation_errors'][0]['repair_hint']['allowed_values'], ['rest', 'recovery'])
        self.assertIn('coach_validation_repaired', self.output.getvalue())

    def test_fatal_authority_precedes_other_invalid_fields(self):
        def mutate(reply, attempt):
            raw = json.loads(reply['message']['content'])
            raw.update(change_proposal={'PRIVATE': 'secret health'}, decisions=[{'action': 'rest', 'intensity': 'tempo'}])
            reply['message']['content'] = json.dumps(raw)
            return reply
        with self.assertRaises(CoachValidationError) as caught: self.run_case(mutate)
        self.assertTrue(caught.exception.fatal)
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn('secret', self.output.getvalue())

    def test_snapshot_mismatch_does_not_retry(self):
        def mutate(reply, attempt):
            raw = json.loads(reply['message']['content']); raw['context_snapshot_id'] = 'foreign'
            reply['message']['content'] = json.dumps(raw); return reply
        with self.assertRaises(CoachValidationError): self.run_case(mutate)
        self.assertEqual(len(self.requests), 1)

    def test_exhausted_repair_does_not_log_rejected_content(self):
        def mutate(reply, attempt):
            return {'message': {'content': '{ private health note'}, 'done_reason': 'stop'}
        with self.assertRaises(CoachValidationError): self.run_case(mutate)
        self.assertEqual(len(self.requests), 2)
        self.assertNotIn('private health', self.output.getvalue())
        self.assertIn('"attempt": 2', self.output.getvalue())

    def test_unknown_evidence_hint_preserves_snapshot(self):
        def mutate(reply, attempt):
            if attempt == 1:
                raw = json.loads(reply['message']['content']); raw['evidence_refs'] = ['checkin:fake']
                reply['message']['content'] = json.dumps(raw)
            return reply
        self.run_case(mutate)
        first, second = [kwargs['response_schema']['properties']['context_snapshot_id']['const'] for _, kwargs in self.requests]
        self.assertEqual(first, second)
        error = json.loads(self.requests[1][0][-1]['content'])['validation_errors'][0]
        self.assertIn('activity:123', error['repair_hint']['allowed_refs'])

    def test_forbidden_proposal_source_wins_over_bad_structure(self):
        compact = compact_fixture()
        compact['extra_context'].update(change_proposal_allowed_now=True, proposal_evidence_sources=['garmin'])
        requests = []
        def generate(messages, **kwargs):
            requests.append(messages)
            reply = valid_reply(messages, **kwargs)
            raw = json.loads(reply['message']['content'])
            raw.update(decisions=[{'action': 'rest', 'intensity': 'tempo'}], evidence_refs=['foreign'],
                       change_proposal={'evidence_refs': ['activity:123']})
            reply['message']['content'] = json.dumps(raw)
            return reply
        with redirect_stdout(io.StringIO()), self.assertRaises(CoachValidationError) as caught:
            generate_validated('mañana', compact, generate=generate, now=NOW)
        self.assertTrue(caught.exception.fatal)
        self.assertEqual(caught.exception.issues[0].code, 'UNAUTHORIZED_CHANGE_PROPOSAL')
        self.assertEqual(len(requests), 1)
