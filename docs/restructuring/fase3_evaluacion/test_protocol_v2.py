import unittest
import json
from datetime import datetime
from experiment import DEFAULT, materialize, build_snapshot, build_catalog
from protocol_v2 import V2
from garmin_sync.coach_deterministic import deterministic_response
from protocol_v2 import prepare_v2, verify_v2
from garmin_sync.coach_findings import select_findings


class V2Tests(unittest.TestCase):
    def test_all_twenty_response_cases_keep_required_findings_and_read_only_actions(self):
        fixtures = json.loads((DEFAULT / 'fixtures.json').read_text())
        expectations = json.loads((DEFAULT / 'expectations.json').read_text())['cases']
        variants = {v['id']: v for v in fixtures['variants']}
        overrides = json.loads(V2.read_text())['question_overrides']
        checked = 0
        for identifier, expected in expectations.items():
            if expected['kind'] != 'response':
                continue
            with self.subTest(case=identifier):
                row = (materialize(fixtures, variants[identifier]) if identifier in variants
                       else fixtures['base_fixtures'][identifier])
                question = overrides.get(identifier, row['pregunta'])
                now = datetime.fromisoformat(row['now'])
                snapshot = build_snapshot(question, row['estado_inicial'], now=now)
                codes = set()
                for i in range(len(snapshot.intent.components)):
                    catalog = build_catalog(snapshot, i, question)
                    selection = select_findings(catalog, question)
                    codes.update(f.code for f in catalog.findings if f.id in selection.finding_ids)
                self.assertTrue(set(expected.get('required_codes', [])) <= codes)
                self.assertFalse(set(expected.get('forbidden_codes', [])) & codes)
                wire = deterministic_response(question, row['estado_inicial'], now=now)
                self.assertTrue(wire.answer)
                self.assertIsNone(wire.change_proposal)
                self.assertTrue(all(d.action in {'ask_user', 'information_only'} for d in wire.decisions))
                checked += 1
        self.assertEqual(checked, 20)

    def test_protocol_and_six_comparisons_reach_expected_findings(self):
        self.assertEqual(verify_v2(), [])
        cases = prepare_v2()
        self.assertEqual(len(cases), 15)
        for case in cases[:6]:
            with self.subTest(case=case['id']):
                cat = case['catalogs'][0]
                self.assertTrue(cat.facts.facts)
                self.assertEqual([str(d) for d in cat.facts.observed_dates], ['2026-10-03'])
                selection = select_findings(cat, case['question'])
                codes = {f.code for f in cat.findings if f.id in selection.finding_ids}
                self.assertTrue(set(case['expectations']['required_codes']) <= codes)
        self.assertEqual(cases[0]['fixture']['estado_inicial'], cases[1]['fixture']['estado_inicial'])
        self.assertEqual(cases[4]['fixture']['estado_inicial'], cases[5]['fixture']['estado_inicial'])


if __name__ == '__main__': unittest.main()
