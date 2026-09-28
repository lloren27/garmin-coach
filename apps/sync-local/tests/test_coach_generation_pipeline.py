import io
import json
import unittest
from contextlib import redirect_stdout
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
        with redirect_stdout(self.output):
            return generate_validated('mañana', compact_fixture(), generate=generate, job_id='job1', now=NOW)

    def test_success_is_rendered_from_one_validated_generation(self):
        wire = self.run_case(lambda reply, attempt: reply)
        self.assertIn('40 a 50 minutos', wire.answer)
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn('answer', self.requests[0][1]['response_schema']['properties'])

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
