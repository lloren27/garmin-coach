import unittest
from test_coach_generation_context import compact_fixture, response, NOW
from garmin_sync.coach_generation_context import build_snapshot
from garmin_sync.coach_generation_resolver import resolve_generation
from garmin_sync.coach_generation_renderer import render_generation
from garmin_sync.ai_contracts import CoachStructuredResponse
from garmin_sync.coach_validation import CoachValidationError


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = build_snapshot('mañana', compact_fixture(), now=NOW)

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
        self.snapshot = build_snapshot('mañana', compact, now=NOW)
        wire = self.render([{'action': 'ask_user'}])
        self.assertEqual(wire.answer.count('actualiza'), 1)
