"""Regressions for natural analysis questions and explicit advice dates."""
from datetime import date, datetime
import unittest

from garmin_sync.coach_intent import resolve_intent, CoachIntent, ClarificationCode
from garmin_sync.coach_deterministic import deterministic_response
from test_coach_analysis import fixture


class NaturalAnalysisTests(unittest.TestCase):
    now = datetime.fromisoformat('2026-10-03T12:00:00+02:00')

    def test_analytical_questions_with_explicit_scope(self):
        for question in ('¿qué tal el ritmo hoy?', '¿cumplí el volumen hoy?',
                         '¿cómo dormí hoy?', '¿qué diferencia hubo con el plan hoy?',
                         '¿qué diferencia de distancia hubo frente al plan hoy?'):
            with self.subTest(question=question):
                result = resolve_intent(question, now=self.now)
                self.assertEqual(result.primary_intent, CoachIntent.ANALYZE_DAY)
                self.assertEqual(result.observed_dates, (date(2026, 10, 3),))
                self.assertFalse(result.change_requested)

    def test_scope_is_never_invented(self):
        for question in ('¿qué tal el ritmo?', '¿cumplí el volumen?', '¿cómo dormí?',
                         '¿qué diferencia hubo con el plan?'):
            with self.subTest(question=question):
                c = resolve_intent(question, now=self.now).components[0]
                self.assertEqual(c.clarification_code, ClarificationCode.NO_SCOPE)
                self.assertEqual(c.observed_dates, ())

    def test_mixed_symptom_question_resolves_tomorrow_without_authority(self):
        row = fixture('E10-mixto')
        response = deterministic_response(row['pregunta'], row['estado_inicial'], now=self.now)
        self.assertEqual([d.date for d in response.decisions], [date(2026,10,3), date(2026,10,4)])
        self.assertTrue(all(d.action == 'ask_user' for d in response.decisions))
        self.assertIn('No puedo valorar si es seguro hacerla', response.answer)
        self.assertIsNone(response.change_proposal)

    def test_advice_question_and_negative_or_declarative_forms(self):
        for question in ('¿hago la sesión de umbral de mañana?', '¿debo hacer la sesión de mañana?'):
            result = resolve_intent(question, now=self.now)
            self.assertEqual(result.primary_intent, CoachIntent.RECOMMEND_NEXT)
            self.assertEqual(result.advice_dates, (date(2026,10,4),))
            self.assertFalse(result.change_requested)
        for question in ('hago la sesión mañana', 'no hago la sesión mañana',
                         'no me digas cómo dormí hoy', 'no quiero saber si cumplí el volumen hoy'):
            self.assertEqual(resolve_intent(question, now=self.now).primary_intent, CoachIntent.CLARIFY)

    def test_new_phrases_keep_future_and_invalid_date_guards(self):
        for question in ('¿cómo dormí mañana?', '¿cumplí el volumen mañana?'):
            self.assertEqual(resolve_intent(question, now=self.now).primary_intent, CoachIntent.CLARIFY)
        self.assertEqual(resolve_intent('¿cómo dormí el 31/02/2026?', now=self.now).components[0].clarification_code,
                         ClarificationCode.INVALID_DATE)
        self.assertEqual(resolve_intent('cambia la sesión de mañana', now=self.now).primary_intent,
                         CoachIntent.REQUEST_CHANGE)


if __name__ == '__main__':
    unittest.main()
