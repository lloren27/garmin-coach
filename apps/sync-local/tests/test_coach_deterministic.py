from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import os

from test_coach_analysis import fixture, snapshot, ROOT
from garmin_sync.coach_findings import build_catalog, select_findings, validate_selection, render_selection
from garmin_sync.coach_deterministic import deterministic_response


class DeterministicTests(unittest.TestCase):
    def test_map_is_byte_identical_to_frozen_protocol(self):
        self.assertEqual((ROOT/'docs/restructuring/fase3_evaluacion/v1/selector_map.json').read_bytes(),
                         (ROOT/'apps/sync-local/garmin_sync/coach_selector_v1.json').read_bytes())

    def response(self, case, question):
        row = fixture(case)
        return deterministic_response(question, row['estado_inicial'], now=datetime.fromisoformat(row['now']))

    def test_mismatch_retains_values_without_percentage(self):
        wire = self.response('E01', 'analiza hoy frente al plan')
        self.assertIn('1:45:04', wire.answer)
        self.assertIn('35–45 min', wire.answer)
        self.assertNotIn('%', wire.answer)
        self.assertIn('misma sesión', wire.answer)
        self.assertEqual({e.source for e in wire.evidence}, {'garmin', 'training_plan'})
        self.assertTrue(all(d.action in {'information_only', 'ask_user'} for d in wire.decisions))

    def test_r01_conditional_and_derived_metrics(self):
        wire = self.response('R01', 'analiza hoy la distancia frente al plan')
        self.assertIn('5,99', wire.answer)
        self.assertIn('35,2', wire.answer)
        self.assertIn('Si corresponde', wire.answer)

    def test_focus_changes_order_on_same_facts(self):
        cat = build_catalog(snapshot(), 0, '¿qué tal el ritmo?')
        pace = select_findings(cat, '¿qué tal el ritmo?')
        volume = select_findings(cat, '¿cumplí el volumen?')
        by_id = {f.id: f for f in cat.findings}
        self.assertEqual(by_id[pace.finding_ids[0]].code, 'PACE_BLOCKS_NOT_COMPARABLE')
        self.assertEqual(by_id[volume.finding_ids[0]].code, 'PLAN_ACTIVITY_MAGNITUDE_MISMATCH')
        self.assertIn('5:15', render_selection(cat, pace))

    def test_unknown_reference_rejected(self):
        cat = build_catalog(snapshot(), 0, 'analiza hoy')
        selection = select_findings(cat, 'analiza hoy')
        with self.assertRaises(ValueError):
            validate_selection(cat, replace(selection, finding_ids=('foreign',)))
        with self.assertRaises(ValueError):
            validate_selection(cat, replace(selection, component_index=1))
        with self.assertRaises(ValueError):
            validate_selection(cat, replace(selection, finding_ids=(), follow_up='PROVIDE_MISSING_CONTEXT'))

    def test_mixed_safety_and_dates(self):
        wire = self.response('E10-mixto', 'analiza hoy y dime qué hacer mañana')
        self.assertIn('No puedo valorar si es seguro hacerla', wire.answer)
        self.assertIn('molestia', wire.answer)
        self.assertTrue(all(d.action in {'ask_user', 'information_only'} for d in wire.decisions))
        self.assertEqual([d.component_index for d in wire.decisions], [0, 1])
        self.assertEqual([d.date.isoformat() for d in wire.decisions], ['2026-10-03', '2026-10-04'])
        self.assertIsNone(wire.change_proposal)

    def test_safety_cannot_be_omitted(self):
        cat = build_catalog(snapshot('E10', question='analiza hoy y dime qué hacer mañana'), 1, 'qué hacer mañana')
        selection = select_findings(cat, 'qué hacer mañana')
        safety_ids = {f.id for f in cat.findings if f.code == 'SESSION_SAFETY_NOT_ASSESSABLE'}
        self.assertTrue(safety_ids)
        with self.assertRaises(ValueError):
            validate_selection(cat, replace(selection, finding_ids=tuple(x for x in selection.finding_ids if x not in safety_ids)))

    def test_multiple_never_chooses_arbitrary_pair(self):
        wire = self.response('MATCH-multiple', 'analiza hoy frente al plan')
        self.assertIn('varias', wire.answer)
        self.assertNotIn('35–45', wire.answer)

    def test_missing_coverage_not_absence(self):
        wire = self.response('E07', 'analiza hoy frente al plan')
        self.assertIn('cobertura', wire.answer)
        self.assertNotIn('no entrenaste', wire.answer)

    def test_unresolved_scope_asks_without_borrowing_dates(self):
        wire = self.response('E01', 'una cosa cualquiera')
        self.assertTrue(all(d.action == 'ask_user' for d in wire.decisions))
        self.assertNotIn('1:45:04', wire.answer)

    def test_too_short_budget_retains_safety(self):
        row = fixture('E10-mixto')
        wire = deterministic_response('analiza hoy y dime qué hacer mañana', row['estado_inicial'],
            now=datetime.fromisoformat(row['now']), max_chars=50)
        self.assertLessEqual(len(wire.answer), 3500)
        self.assertIn('valorar si es seguro', wire.answer)
        self.assertEqual([d.component_index for d in wire.decisions], [0, 1])

    def test_frozen_e10_wording_preserves_safety_without_inventing_scope(self):
        row = fixture('E10-mixto')
        wire = self.response('E10-mixto', row['pregunta'])
        self.assertIn('No puedo valorar si es seguro hacerla', wire.answer)
        self.assertIsNone(wire.decisions[1].date)  # Existing resolver leaves this paraphrase unresolved.
        self.assertEqual(wire.decisions[1].action, 'ask_user')

    def test_change_request_does_not_erase_safety(self):
        wire = self.response('E10', 'cambia la sesión de mañana')
        self.assertIn('No puedo valorar si es seguro hacerla', wire.answer)
        self.assertIsNone(wire.change_proposal)

    def test_source_is_deterministic_and_read_only(self):
        wire = self.response('E01', 'analiza hoy')
        self.assertTrue(all(d.source == 'deterministic' for d in wire.decisions))
        data = wire.model_dump(mode='json')
        data['decisions'][0]['action'] = 'keep_plan'
        with self.assertRaises(ValueError):
            type(wire).model_validate(data)

    def test_worker_flag_off_preserves_legacy(self):
        from garmin_sync import ai_worker as worker
        with patch.object(worker, 'COACH_ANALYSIS_V3_ENABLED', False), patch.object(worker, 'call_ollama') as old:
            result = worker.call_coach('analiza hoy', {})
            self.assertIs(result, old.return_value)

    def test_flag_is_not_reloaded_per_job(self):
        from garmin_sync import ai_worker as worker
        with patch.object(worker, 'COACH_ANALYSIS_V3_ENABLED', False), patch.dict(os.environ, {'COACH_ANALYSIS_V3_ENABLED': 'on'}), patch.object(worker, 'call_ollama') as old:
            worker.call_coach('analiza hoy', {})
            old.assert_called_once()

    def test_enforcement_switch_does_not_expand_v3_permissions(self):
        outputs = []
        for flag in ('off', 'on'):
            with patch.dict(os.environ, {'COACH_INTENT_ENFORCEMENT': flag}):
                outputs.append(self.response('E10', 'analiza hoy y dime qué hacer mañana').model_dump())
        self.assertEqual(outputs[0], outputs[1])

    def test_worker_flag_on_never_calls_model(self):
        from garmin_sync import ai_worker as worker
        row = fixture('E01')
        with patch.object(worker, 'COACH_ANALYSIS_V3_ENABLED', True), patch.object(worker, 'compact_context', return_value=row['estado_inicial']), patch.object(worker, 'call_ollama') as old:
            result = worker.call_coach('analiza hoy frente al plan', {}, now=datetime.fromisoformat(row['now']))
            old.assert_not_called()
            self.assertEqual(result.source, 'deterministic')
            self.assertIn('1:45:04', result.answer)

    def test_invalid_v3_context_does_not_use_legacy_fallback(self):
        from garmin_sync import ai_worker as worker
        with patch.object(worker, 'COACH_ANALYSIS_V3_ENABLED', True), patch.object(worker, 'compact_context', side_effect=ValueError('private input')), patch.object(worker, 'basic_fallback_answer') as legacy:
            result = worker.call_coach('analiza hoy', {})
            legacy.assert_not_called()
            self.assertNotIn('private input', result.answer)
            self.assertEqual(result.structured_output['decisions'][0]['action'], 'ask_user')


if __name__ == '__main__':
    unittest.main()
