import unittest
from test_coach_generation_context import compact_fixture, response, NOW
from garmin_sync.coach_generation_context import build_snapshot
from garmin_sync.coach_generation_resolver import resolve_generation
from garmin_sync.coach_generation_renderer import render_generation
from garmin_sync.ai_contracts import CoachStructuredResponse
from garmin_sync.coach_validation import CoachValidationError


class RendererTests(unittest.TestCase):
    def daily_analysis(self, rows):
        compact = compact_fixture()
        compact['extra_context']['recent_activities'] = rows
        self.snapshot = build_snapshot('analiza el entrenamiento de hoy', compact, now=NOW)
        return self.render([{'action': 'information_only'}], response_type='analysis',
            evidence_refs=[f"activity:{r['id']}" for r in rows])

    def test_daily_analysis_explains_two_sports_without_generic_limitation(self):
        wire = self.daily_analysis([
            dict(id='run', date='2026-09-25', sport='running', duration_s=3631,
                 distance_km=12.01, avg_hr=133, max_hr=166),
            dict(id='bike', date='2026-09-25', sport='cycling', duration_s=3777,
                 distance_km=23.15, avg_hr=86, max_hr=120, avg_power=143)])
        for text in ('carrera', 'bicicleta', '1 h 00 min 31 s', '5:02 min/km', '22,1 km/h', '143 W'):
            self.assertIn(text, wire.answer)
        self.assertNotIn('no permite una conclusión adicional', wire.answer)
        self.assertNotIn('no permite una conclusión adicional', wire.decisions[0].reason)
        self.assertIn('zonas', wire.answer)
        CoachStructuredResponse.model_validate(wire.model_dump(mode='json'))

    def test_unknown_sport_or_zero_distance_never_invents_pace(self):
        for sport, distance in [('unknown', 12.01), ('running', 0)]:
            with self.subTest(sport=sport):
                wire = self.daily_analysis([dict(id='a', date='2026-09-25', sport=sport,
                    duration_s=3631, distance_km=distance)])
                self.assertIn('1 h 00 min 31 s', wire.answer)
                self.assertNotIn('min/km', wire.answer)
                self.assertNotIn('km/h', wire.answer)

    def test_previous_activity_is_comparison_not_today_and_different_sport_not_compared(self):
        wire = self.daily_analysis([
            dict(id='now', date='2026-09-25', sport='running', duration_s=3600, distance_km=12),
            dict(id='past', date='2026-09-24', sport='running', duration_s=3000, distance_km=10),
            dict(id='bike', date='2026-09-24', sport='cycling', duration_s=7000, distance_km=45)])
        self.assertIn('10 min', wire.answer)
        self.assertIn('2026-09-24', wire.answer)
        self.assertNotIn('45 km', wire.answer)
        self.assertNotIn('mejora', wire.answer)

    def test_analysis_stale_data_keeps_warning_and_rejects_too_short_output(self):
        self.daily_analysis([dict(id='a', date='2026-09-25', sport='running',
            duration_s=3600, distance_km=12)])
        from dataclasses import replace
        self.snapshot = replace(self.snapshot, freshness='stale')
        resolved = resolve_generation(response(self.snapshot, [{'action': 'information_only'}],
            response_type='analysis', evidence_refs=['activity:a']), self.snapshot)
        self.assertIn('actualiza', render_generation(resolved, self.snapshot, max_chars=3200).answer)
        with self.assertRaises(CoachValidationError):
            render_generation(resolved, self.snapshot, max_chars=40)

    def setUp(self):
        self.snapshot = build_snapshot('qué toca mañana', compact_fixture(), now=NOW)

    def render(self, decisions, **updates):
        resolved = resolve_generation(response(self.snapshot, decisions, **updates), self.snapshot)
        return render_generation(resolved, self.snapshot, max_chars=3200)

    def test_plan_text_uses_authoritative_dose_without_free_titles(self):
        wire = self.render([{'action': 'keep_plan', 'session_id': 'run'}, {'action': 'keep_plan', 'session_id': 'bike'}])
        self.assertIn('40 a 50 minutos', wire.answer)
        self.assertIn('60 a 70 minutos', wire.answer)
        self.assertIn('150 W', wire.answer)
        self.assertIn('2026-09-26', wire.answer)
        self.assertNotIn('30 minutos', wire.answer)
        self.assertNotIn('Ignora', wire.answer)
        CoachStructuredResponse.model_validate(wire.model_dump(mode='json'))

    def test_rest_does_not_invent_activity_and_keeps_caveat(self):
        wire = self.render([{'action': 'rest', 'evidence_refs': ['activity:123']}])
        self.assertIn('descanso', wire.answer)
        self.assertIn('no modifica', wire.answer)
        self.assertIn('Zepp', wire.answer)
        self.assertIn('8 km', wire.answer)
        self.assertNotIn('Garmin', wire.answer)

    def test_activity_preserves_exact_range_and_pace(self):
        wire = self.render([dict(action='modify_session', sport='running', intensity='easy',
            duration_min=40, duration_max_min=50, target_pace='5:00–5:30 min/km', evidence_refs=['activity:123'])])
        self.assertIn('40 a 50 minutos', wire.answer)
        self.assertIn('5:00–5:30 min/km', wire.answer)
        self.assertIn('suave', wire.answer)

    def test_analysis_does_not_force_a_workout(self):
        wire = self.render([{'action': 'information_only'}], response_type='analysis',
            conclusions=[{'code': 'OBSERVED_ACTIVITY', 'evidence_refs': ['activity:123']}])
        self.assertEqual(wire.decisions[0].action, 'information_only')
        self.assertIn('8 km', wire.answer)
        self.assertNotIn('entrena', wire.answer.lower())

    def test_short_limit_never_silently_truncates_prescription(self):
        resolved = resolve_generation(response(self.snapshot, [{'action': 'keep_plan', 'session_id': 'run'},
            {'action': 'keep_plan', 'session_id': 'bike'}]), self.snapshot)
        with self.assertRaises(CoachValidationError) as caught:
            render_generation(resolved, self.snapshot, max_chars=40)
        self.assertEqual(caught.exception.issues[0].phase, 'rendering')
        self.assertTrue(caught.exception.fatal)

    def test_stale_notice_is_required_once(self):
        compact = compact_fixture(); compact['extra_context']['data_freshness']['status'] = 'stale'
        self.snapshot = build_snapshot('qué toca mañana', compact, now=NOW)
        wire = self.render([{'action': 'ask_user'}])
        self.assertEqual(wire.answer.count('actualiza'), 1)

    def test_optional_plan_session_remains_optional_in_text_and_wire(self):
        compact = compact_fixture()
        compact['extra_context']['training_plan']['sessions'] = [dict(id='run', date='2026-09-26',
            sport='strength', session_type='full_body_a', intensity='easy', duration_min=30, optional=True)]
        self.snapshot = build_snapshot('qué toca mañana', compact, now=NOW)
        wire = self.render([{'action': 'keep_plan', 'session_id': 'run'}])
        self.assertIn('opcional', wire.answer.lower())
        self.assertIn('opcional', wire.decisions[0].reason.lower())

    def test_complex_plan_does_not_invent_missing_dose_or_apply_pace_to_whole_run(self):
        compact = compact_fixture()
        compact['extra_context']['training_plan']['sessions'] = [dict(id='run', date='2026-09-26',
            sport='running', session_type='quality', intensity='marathon_pace', target_pace='5:00',
            description='2 km + 3 x 2 km. arbitrary prose')]
        self.snapshot = build_snapshot('qué toca mañana', compact, now=NOW)
        wire = self.render([{'action': 'keep_plan', 'session_id': 'run'}])
        self.assertIn('bloques', wire.answer)
        self.assertNotIn('arbitrary', wire.answer)
        self.assertNotIn('minutos', wire.answer)
