import copy
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import experiment as ex
from garmin_sync.coach_deterministic import deterministic_response
from garmin_sync.coach_findings import select_findings


class ExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = ex.prepare_cases(ex.DEFAULT)

    def case(self, name):
        return next(c for c in self.cases if c['id'] == name)

    def payload(self, case):
        return {'selections': [asdict(select_findings(c, case['question'])) for c in case['catalogs']]}

    def test_exact_cases_and_frozen_questions(self):
        self.assertEqual({c['id'] for c in self.cases}, {
            'E01', 'E07', 'E08', 'E09', 'E10', 'E13', 'R01', 'E01-mixto', 'E10-mixto',
            'E01-pace', 'E01-volume', 'E01-sleep', 'E01-plan', 'R01-pace', 'R01-distance'})
        self.assertEqual(self.case('E01-pace')['question'], '¿qué tal el ritmo?')
        self.assertEqual(self.case('E01-pace')['fixture']['estado_inicial'],
                         self.case('E01-volume')['fixture']['estado_inicial'])
        self.assertEqual(self.case('E01-pace')['fixture']['now'], self.case('E01-volume')['fixture']['now'])

    def test_changed_protocol_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'v1'
            shutil.copytree(ex.DEFAULT, dest)
            with (dest / 'fixtures.json').open('a') as f:
                f.write(' ')
            with self.assertRaises(ValueError):
                ex.prepare_cases(dest)

    def test_shared_rendering_matches_current_route_all_cases(self):
        for case in self.cases:
            with self.subTest(case=case['id']):
                selections = ex.parse_selections(json.dumps(self.payload(case)), case['catalogs'])
                text = ex.render_candidate(case['catalogs'], selections, snapshot=case['snapshot'])
                expected = deterministic_response(case['question'], case['fixture']['estado_inicial'],
                                                  now=case['snapshot'].now).answer
                self.assertEqual(text, expected)
        mixed = self.case('E10-mixto')
        text = ex.render_candidate(mixed['catalogs'], ex.parse_selections(
            json.dumps(self.payload(mixed)), mixed['catalogs']), snapshot=mixed['snapshot'])
        self.assertIn('No puedo valorar si es seguro hacerla', text)

    def test_rejects_invalid_structure_and_scope(self):
        case = self.case('E01-mixto')
        mutations = [lambda p: p.update(extra=1), lambda p: p['selections'].pop(),
                     lambda p: p['selections'].append(p['selections'][0]),
                     lambda p: p['selections'][0].update(extra=1),
                     lambda p: p['selections'][0].update(component_index=True),
                     lambda p: p['selections'][0].update(snapshot_id='foreign'),
                     lambda p: p['selections'][0].update(finding_ids=['foreign']),
                     lambda p: p['selections'][0].update(follow_up='keep_plan')]
        for mutate in mutations:
            p = self.payload(case); mutate(p)
            with self.subTest(payload=p), self.assertRaises(ValueError):
                ex.parse_selections(json.dumps(p), case['catalogs'])
        with self.assertRaises(ValueError):
            ex.parse_selections('{"selections":[],"selections":[]}', case['catalogs'])

    def test_missing_safety_and_budget_rejected(self):
        case = self.case('E10-mixto'); p = self.payload(case)
        p['selections'][1]['finding_ids'] = []
        with self.assertRaises(ValueError):
            ex.parse_selections(json.dumps(p), case['catalogs'])
        from dataclasses import replace
        from garmin_sync.coach_findings import Finding
        cat = case['catalogs'][0]
        findings = tuple(Finding(str(i), 'PACE_BLOCKS_NOT_COMPARABLE', 0, None, (), (), 'observed', 'x') for i in range(4))
        cat = replace(cat, findings=findings, required_ids=())
        p = {'selections': [{'schema_version':'1', 'snapshot_id':cat.facts.snapshot_id,
            'component_index':0, 'finding_ids':['0','1','2','3'], 'follow_up':None}]}
        with self.assertRaisesRegex(ValueError, 'BUDGET'):
            ex.parse_selections(json.dumps(p), (cat,))

if __name__ == '__main__':
    unittest.main()
