from dataclasses import replace
from datetime import datetime, timezone
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
        self.assertEqual(wire.decisions[1].date.isoformat(), '2026-10-04')
        self.assertEqual(wire.decisions[1].action, 'ask_user')

    def test_future_plan_query_renders_only_requested_sport(self):
        row = fixture('E01')
        extra = row['estado_inicial']['extra_context']
        extra['recent_activities'] = []
        extra['training_plan']['sessions'] = [
            {'id': 'bike-plan', 'date': '2026-10-04', 'status': 'planned', 'sport': 'cycling',
             'duration_min': 60, 'duration_max': 90},
            {'id': 'run-plan', 'date': '2026-10-04', 'status': 'planned', 'sport': 'running',
             'duration_min': 30, 'duration_max': 45},
        ]
        wire = deterministic_response('qué sesión de bici tengo mañana', row['estado_inicial'],
            now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        self.assertIn('ciclismo (2026-10-04), 60–90 min', wire.answer)
        self.assertNotIn('running', wire.answer)
        self.assertNotIn('¿Puedes aportar los datos', wire.answer)

    def test_plan_without_requested_sport_says_so(self):
        row = fixture('E01')
        extra = row['estado_inicial']['extra_context']
        extra['recent_activities'] = []
        extra['training_plan']['sessions'] = [
            {'id': 'run-plan', 'date': '2026-10-04', 'status': 'planned', 'sport': 'running',
             'duration_min': 30, 'duration_max': 45},
        ]
        wire = deterministic_response('qué sesión de bici tengo mañana', row['estado_inicial'],
            now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        self.assertIn('El plan disponible no muestra una sesión de ciclismo para 2026-10-04.', wire.answer)

    def test_plan_with_no_session_on_requested_day_says_so(self):
        row = fixture('E01')
        extra = row['estado_inicial']['extra_context']
        extra['recent_activities'] = []
        extra['training_plan']['sessions'] = [
            {'id': 'bike-later', 'date': '2026-10-05', 'status': 'planned', 'sport': 'cycling',
             'duration_min': 60, 'duration_max': 90},
        ]
        wire = deterministic_response('qué sesión de bici tengo mañana', row['estado_inicial'],
            now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        self.assertIn('El plan disponible no muestra una sesión de ciclismo para 2026-10-04.', wire.answer)
        self.assertNotIn('bike-later', wire.answer)

    def test_plan_without_sport_metadata_asks_for_confirmation(self):
        row = fixture('E01')
        extra = row['estado_inicial']['extra_context']
        extra['recent_activities'] = []
        extra['training_plan']['sessions'] = [
            {'id': 'unknown-plan', 'date': '2026-10-04', 'status': 'planned',
             'duration_min': 60, 'duration_max': 90},
        ]
        wire = deterministic_response('qué sesión de bici tengo mañana', row['estado_inicial'],
            now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        self.assertIn('El plan no indica el deporte', wire.answer)

    def test_multiple_activities_on_one_day_are_listed_separately(self):
        row = fixture('E01')
        extra = row['estado_inicial']['extra_context']
        extra['recent_activities'] = [
            {'id': 'ride-a', 'source': 'garmin', 'sport': 'cycling', 'date': '2026-10-03',
             'local_date': '2026-10-03', 'started_at_utc': '2026-10-03T07:00:00Z',
             'time_context': 'Europe/Madrid', 'duration_s': 1800, 'km': 8},
            {'id': 'ride-b', 'source': 'garmin', 'sport': 'cycling', 'date': '2026-10-03',
             'local_date': '2026-10-03', 'started_at_utc': '2026-10-03T10:00:00Z',
             'time_context': 'Europe/Madrid', 'duration_s': 2400, 'km': 12},
        ]
        extra['training_plan']['sessions'] = []
        wire = deterministic_response('analiza las actividades de bici de hoy', row['estado_inicial'],
            now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        self.assertIn('30:00, 8 km', wire.answer)
        self.assertIn('40:00, 12 km', wire.answer)

    def test_max_hr_finding_is_selected_rendered_and_references_source_facts(self):
        row = fixture('E01')
        question = '¿Cuál fue mi FC máxima en la carrera de hoy?'
        extra = row['estado_inicial']['extra_context']
        extra['recent_activities'] = [{
            'id': 'run-dedup', 'source': 'garmin', 'sport': 'running', 'date': '2026-10-03',
            'local_date': '2026-10-03', 'started_at_utc': '2026-10-03T07:00:00Z',
            'time_context': 'Europe/Madrid', 'duration_s': 1800, 'km': 5, 'avg_hr': 140,
            'max_hr': 188,
            'source_records': [
                {'source': 'garmin', 'source_activity_id': 'g-run', 'metrics': {'max_hr': 188}},
                {'source': 'strava', 'source_activity_id': 's-run', 'metrics': {'max_hr': 176}},
            ],
        }]
        snap = snapshot(question=question, mutate=lambda x: x.update(extra),
                        now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        catalog = build_catalog(snap, 0, question)
        selection = select_findings(catalog, question)
        finding = next(f for f in catalog.findings if f.code == 'ACTIVITY_METRIC_VALUE')
        self.assertTrue(finding.fact_refs)
        self.assertTrue(set(finding.fact_refs) <= {fact.id for fact in catalog.facts.facts})
        self.assertEqual(set(finding.source_refs), {'activity:run-dedup'})
        self.assertIn(finding.id, selection.finding_ids)
        self.assertEqual(selection.schema_version, '2')
        with self.assertRaises(ValueError):
            validate_selection(catalog, replace(selection, schema_version='1'))
        answer = render_selection(catalog, selection)
        self.assertIn('188 lpm (Garmin)', answer)
        self.assertIn('176 lpm (Strava)', answer)

    def test_metric_selector_is_versioned_and_contains_the_new_code(self):
        from garmin_sync.coach_findings import SELECTOR
        self.assertEqual(SELECTOR['protocol_version'], 'fase4-v2')
        metric_family = next(f for f in SELECTOR['families'] if f['id'] == 'activity_metrics')
        self.assertIn('ACTIVITY_METRIC_VALUE', metric_family['codes'])

    def test_average_hr_does_not_fall_back_to_max_hr(self):
        row = fixture('E01')
        extra = row['estado_inicial']['extra_context']
        extra['recent_activities'] = [{
            'id': 'run-average-only', 'source': 'garmin', 'sport': 'running', 'date': '2026-10-03',
            'local_date': '2026-10-03', 'started_at_utc': '2026-10-03T07:00:00Z',
            'time_context': 'Europe/Madrid', 'avg_hr': 141,
        }]
        question = '¿Cuál fue mi FC máxima en la carrera de hoy?'
        wire = deterministic_response(question, row['estado_inicial'],
            now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        self.assertIn('No hay un pulso máximo válido registrado', wire.answer)
        self.assertNotIn('141', wire.answer)

    def test_multiple_max_hr_activities_render_as_separate_findings(self):
        row = fixture('E01')
        extra = row['estado_inicial']['extra_context']
        extra['recent_activities'] = [
            {'id': 'run-a', 'source': 'garmin', 'sport': 'running', 'date': '2026-10-03',
             'local_date': '2026-10-03', 'started_at_utc': '2026-10-03T07:00:00Z',
             'time_context': 'Europe/Madrid', 'max_hr': 175},
            {'id': 'run-b', 'source': 'strava', 'sport': 'running', 'date': '2026-10-03',
             'local_date': '2026-10-03', 'started_at_utc': '2026-10-03T10:00:00Z',
             'time_context': 'Europe/Madrid', 'max_hr': 181},
        ]
        question = 'pulso máximo en mis actividades de carrera de hoy'
        wire = deterministic_response(question, row['estado_inicial'],
            now=datetime(2026, 10, 3, 12, tzinfo=timezone.utc))
        self.assertIn('175 lpm (Garmin)', wire.answer)
        self.assertIn('181 lpm (Strava)', wire.answer)
        self.assertEqual(wire.answer.count('Pulso máximo'), 2)

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
