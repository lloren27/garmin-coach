import copy
import json
import unittest
from pydantic import ValidationError
from garmin_sync.coach_generation_contracts import (
    CoachGenerationResponse, RestDecision, KeepPlanDecision,
    normalize_generation, parse_generation,
)
from garmin_sync.coach_validation import CoachValidationError


def payload(**updates):
    data = dict(schema_version='1', context_snapshot_id='ctx_test', response_type='recovery',
                decisions=[{'action': 'rest', 'evidence_refs': []}], conclusions=[], evidence_refs=[])
    data.update(updates)
    return data


class GenerationContractTests(unittest.TestCase):
    def test_empty_decision_cannot_silently_answer_unknown_question(self):
        with self.assertRaises(CoachValidationError):
            parse_generation(json.dumps(payload(decisions=[])))

    def test_rest_rejects_training_intensity_and_targets(self):
        for extra in ({'intensity': 'easy'}, {'intensity': 'threshold'}, {'intensity': 'unknown'},
                      {'target_pace': '5:00'}, {'target_power_w': 100}, {'distance_km': 1},
                      {'duration_min': 30}):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                RestDecision(action='rest', evidence_refs=[], **extra)
        self.assertEqual(RestDecision(action='rest', evidence_refs=[]).intensity, 'rest')

    def test_keep_plan_cannot_regenerate_authoritative_fields(self):
        for key, value in [('duration_min', 30), ('intensity', 'easy'),
                           ('source', 'training_plan')]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                KeepPlanDecision(action='keep_plan', session_id='s1', evidence_refs=[], **{key: value})
        decision = KeepPlanDecision(action='keep_plan', session_id='s1', evidence_refs=[],
                                     component_index=0, date='2026-09-25')
        self.assertEqual(decision.component_index, 0)
        self.assertEqual(decision.date.isoformat(), '2026-09-25')

    def test_response_requires_version_snapshot_and_forbids_free_answer(self):
        for key in ('schema_version', 'context_snapshot_id'):
            data = payload(); del data[key]
            with self.assertRaises(CoachValidationError): parse_generation(json.dumps(data))
        for extra in ({'schema_version': '2'}, {'answer': 'Haz 30 minutos.'}, {'conclusions': [{'code': 'TOTAL_LOAD_ACCEPTABLE', 'evidence_refs': []}]}):
            with self.assertRaises(CoachValidationError): parse_generation(json.dumps(payload(**extra)))

    def test_safe_normalization_does_not_mutate_input_or_hide_contradictions(self):
        original = payload(decisions=[{'action': ' REST ', 'intensity': 'threshold', 'evidence_refs': []}])
        before = copy.deepcopy(original)
        normalized, issues = normalize_generation(original)
        self.assertEqual(original, before)
        self.assertEqual(normalized['decisions'][0]['action'], 'rest')
        self.assertEqual(normalized['decisions'][0]['intensity'], 'threshold')
        self.assertEqual(issues[0].severity, 'normalizable')
        with self.assertRaises(CoachValidationError) as caught: parse_generation(json.dumps(original))
        issue = caught.exception.issues[0]
        self.assertEqual(issue.code, 'REST_INVALID_INTENSITY')
        self.assertEqual(issue.phase, 'structure')
        self.assertEqual(issue.repair_hint.allowed_values, ('rest', 'recovery'))

    def test_activity_duration_pace_and_information_constraints(self):
        base = dict(action='modify_session', sport='running', intensity='easy', duration_min=40,
                    duration_max_min=50, evidence_refs=[])
        for fields in ({'duration_max_min': 30}, {'target_pace': 'easy'}, {'duration_min': True},
                       {'target_pace': '4:99'}, {'target_power_w': 250}, {'intensity': 'unknown'}):
            with self.subTest(fields=fields), self.assertRaises(CoachValidationError):
                parse_generation(json.dumps(payload(decisions=[dict(base, **fields)])))
        parsed = parse_generation(json.dumps(payload(decisions=[dict(base, target_pace='5:00–5:30 min/km')])))
        self.assertEqual(parsed.decisions[0].duration_max_min, 50)
        parsed = parse_generation(json.dumps(payload(decisions=[dict(base, target_pace='5:13/km')])))
        self.assertEqual(parsed.decisions[0].target_pace, '5:13/km')
        with self.assertRaises(CoachValidationError):
            parse_generation(json.dumps(payload(decisions=[{'action': 'information_only', 'duration_min': 30}])))

    def test_parsing_errors_do_not_expose_content(self):
        with self.assertRaises(CoachValidationError) as caught: parse_generation('private health note')
        self.assertEqual(caught.exception.issues[0].phase, 'parsing')
        self.assertNotIn('private', str(caught.exception))

    def test_schema_has_discriminated_variants(self):
        schema = CoachGenerationResponse.model_json_schema()
        variants = schema['properties']['decisions']['items']
        self.assertEqual(variants['discriminator']['propertyName'], 'action')
        self.assertEqual(set(variants['discriminator']['mapping']), {'rest', 'keep_plan', 'modify_session',
            'recovery', 'cross_training', 'strength', 'ask_user', 'information_only'})
        information = schema['$defs']['InformationDecision']
        self.assertNotIn('component_index', information.get('required', []))
