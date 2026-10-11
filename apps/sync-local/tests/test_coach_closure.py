from datetime import datetime
import unittest
from test_coach_analysis import fixture
from garmin_sync.coach_deterministic import deterministic_response


class ClosureContentTests(unittest.TestCase):
    def answer(self, name):
        row = fixture(name)
        return deterministic_response(row['pregunta'], row['estado_inicial'], now=datetime.fromisoformat(row['now'])).answer

    def test_missing_coverage_requests_activity_sync(self):
        answer = self.answer('E07')
        self.assertIn('sincroniz', answer)
        self.assertIn('actividad', answer)
        self.assertNotIn('no entrenaste', answer)

    def test_missing_plan_describes_activity_and_requests_plan(self):
        answer = self.answer('E08')
        for text in ('20,02 km', '1:45:04', 'garmin', 'plan'):
            self.assertIn(text, answer)
        self.assertIn('aportar el plan', answer)

    def test_multisport_keeps_distances_and_durations_separate(self):
        answer = self.answer('E09')
        for text in ('20,02 km', '35 km', '1:45:04', '1:10:00', '30:00', 'no se suman'):
            self.assertIn(text, answer)

    def test_symptom_detail_and_target_session_survive_without_endorsement(self):
        answer = self.answer('E10')
        for text in ('gemelo derecho al correr', 'umbral', '2026-10-04', 'No puedo valorar si es seguro hacerla'):
            self.assertIn(text, answer)

    def test_comparison_shows_duration_without_claiming_blocks(self):
        self.assertIn('55:53', self.answer('R01'))

    def test_cancelled_or_completed_session_is_not_presented_as_planned(self):
        for update in ({'status': 'cancelled'}, {'status': 'completed'},
                       {'completed_activity_id': 'synthetic-g1'}):
            with self.subTest(update=update):
                row = fixture('E10')
                row['estado_inicial']['extra_context']['training_plan']['sessions'][0].update(update)
                wire = deterministic_response(row['pregunta'], row['estado_inicial'], now=datetime.fromisoformat(row['now']))
                self.assertNotIn('La sesión prevista', wire.answer)
                self.assertIn('No puedo valorar si es seguro hacerla', wire.answer)

    def test_sleep_focus_starts_with_sleep_and_does_not_demand_history(self):
        row = fixture('E01-sleep')
        answer = deterministic_response('¿cómo dormí hoy?', row['estado_inicial'], now=datetime.fromisoformat(row['now'])).answer
        self.assertLess(answer.index('sueño 430'), answer.index('pulso'))
        self.assertNotIn('¿Dispones de un histórico', answer)


if __name__ == '__main__': unittest.main()
