"""Contract tests only: no coach execution, network or product imports."""
import copy
import json
from pathlib import Path
import re
import tempfile
import unicodedata
import unittest

from verify_protocol import validate_contract, verify, materialize

V1 = Path(__file__).parent / 'v1'


def bundle():
    return {name: json.loads((V1 / f'{name}.json').read_text())
            for name in ('fixtures', 'expectations', 'selector_map', 'rubric')}


class ProtocolTests(unittest.TestCase):
    def test_frozen_package_valid(self):
        self.assertEqual(verify(V1), [])

    def test_changed_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for path in V1.glob('*.json'):
                (target / path.name).write_bytes(path.read_bytes())
            path = target / 'selector_map.json'
            path.write_bytes(path.read_bytes() + b'\n')
            self.assertTrue(any('hash:selector_map.json' in x for x in verify(target)))

    def test_missing_case_rejected(self):
        data = bundle()
        del data['expectations']['cases']['E15b']
        self.assertIn('case_coverage', validate_contract(data))

    def test_pair_cannot_change_facts(self):
        data = bundle()
        variant = next(v for v in data['fixtures']['variants'] if v['id'] == 'E01-pace')
        variant['replace'] = {
            '/estado_inicial/extra_context/recent_activities/0/km': 1}
        self.assertIn('pair_facts:pair-e01-pace-volume', validate_contract(data))

    def test_mixed_safety_cannot_be_relaxed(self):
        data = bundle()
        case = data['expectations']['cases']['E10-mixto']
        case['required_codes'].remove('SESSION_SAFETY_NOT_ASSESSABLE')
        case['forbidden_actions'].remove('keep_plan')
        errors = validate_contract(data)
        self.assertIn('mixed_safety', errors)
        self.assertIn('mixed_actions:E10-mixto', errors)

    def test_wrong_multiple_match_rejected(self):
        data = bundle()
        data['expectations']['cases']['MATCH-multiple']['required_codes'].append(
            'PLAN_ACTIVITY_MAGNITUDE_MISMATCH')
        self.assertIn('multiple_match', validate_contract(data))

    def test_naive_clock_rejected(self):
        data = bundle()
        data['fixtures']['base_fixtures']['E01']['now'] = '2026-10-03T22:00:00'
        self.assertIn('aware_now:E01', validate_contract(data))

    def test_tie_policy_cannot_favor_model(self):
        data = bundle()
        data['rubric']['comparison']['tie_winner'] = 'model'
        self.assertIn('tie_policy', validate_contract(data))

    def test_variants_materialize_without_mutating_base(self):
        data = bundle()['fixtures']
        original = copy.deepcopy(data['base_fixtures']['E01'])
        variant = next(x for x in data['variants'] if x['id'] == 'MATCH-warmup')
        result = materialize(data, variant)
        self.assertEqual(result['estado_inicial']['extra_context']['recent_activities'][0]['duration_s'], 720)
        self.assertEqual(data['base_fixtures']['E01'], original)

    def test_corrupt_json_rejected_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for path in V1.glob('*.json'):
                (target / path.name).write_bytes(path.read_bytes())
            (target / 'fixtures.json').write_text('{')
            self.assertTrue(any('json:fixtures' in x for x in verify(target)))

    def test_keyword_map_covers_frozen_question_focus(self):
        data = bundle()
        families = {f['id']: f for f in data['selector_map']['families']}

        def tokens(text):
            text = ''.join(c for c in unicodedata.normalize('NFKD', text)
                           if not unicodedata.combining(c)).casefold()
            return re.findall(r'[^\W_]+', text)

        for variant in data['fixtures']['variants']:
            if not variant['pair']:
                continue
            words = tokens(variant['question'])
            phrases = [tokens(p) for p in families[variant['focus']]['phrases']]
            self.assertTrue(any(words[i:i + len(p)] == p
                                for p in phrases for i in range(len(words))), variant['id'])

    def test_reference_numbers_from_frozen_facts(self):
        data = bundle()
        bases = data['fixtures']['base_fixtures']
        activity = bases['E01']['estado_inicial']['extra_context']['recent_activities'][0]
        seconds = activity['duration_s']
        self.assertEqual(f'{seconds / 2700:.2f}', '2.33')
        self.assertEqual(seconds - 2700, 3604)
        self.assertEqual(f'{(seconds - 2700) / 2700 * 100:.1f}', '133.5')
        context = bases['R01']['estado_inicial']['extra_context']
        km = context['recent_activities'][0]['km']
        target = context['training_plan']['sessions'][0]['distance_km']
        self.assertEqual(f'{km - target:.2f}', '-5.99')
        self.assertEqual(round(context['recent_activities'][0]['duration_s'] / km), 305)


if __name__ == '__main__':
    unittest.main()
