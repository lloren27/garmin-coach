"""Focused activation and calendar boundaries for weekly coach assessments."""

from datetime import date, datetime, timezone
import unittest

from garmin_sync.coach_intent import (
    CoachIntent,
    WeekAssessmentScope,
    resolve_intent,
    resolve_week_assessment,
)


class WeeklyAssessmentIntentTests(unittest.TestCase):
    # Tuesday 27 October at 23:30 in Madrid, fixed when the job is created.
    JOB_TIME = datetime(2026, 10, 27, 22, 30, tzinfo=timezone.utc)

    def resolve(self, question, *, factual_scope=None, now=None):
        return resolve_week_assessment(
            question, now=now or self.JOB_TIME, factual_scope=factual_scope,
        )

    def test_human_assessment_questions_use_the_calendar_week(self):
        expected = WeekAssessmentScope(
            monday=date(2026, 10, 26),
            sunday=date(2026, 11, 1),
            reference_day=date(2026, 10, 27),
        )
        for question in (
            "¿Qué opinas de mi entrenamiento de hoy?",
            "analiza mi entrenamiento de hoy",
            "¿Fue eficiente mi entrenamiento de bici hoy?",
            "¿Cómo afecta lo que hice a esta semana?",
            "Valora mi entrenamiento de esta semana",
            "Valora mi entrenamiento de hoy frente a la sesión prevista",
        ):
            with self.subTest(question=question):
                self.assertEqual(self.resolve(question), expected)

    def test_explicit_historical_date_selects_its_own_week(self):
        self.assertEqual(
            self.resolve("Valora mi entrenamiento del 21/10/2026"),
            WeekAssessmentScope(date(2026, 10, 19), date(2026, 10, 25), date(2026, 10, 21)),
        )

    def test_job_creation_time_stays_fixed_across_processing_midnight(self):
        # The worker can process this Sunday job on Monday; it must pass JOB_TIME.
        sunday_job = datetime(2026, 11, 1, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(
            self.resolve("analiza mi entrenamiento de hoy", now=sunday_job),
            WeekAssessmentScope(date(2026, 10, 26), date(2026, 11, 1), date(2026, 11, 1)),
        )

    def test_alias_factual_scope_disables_assessment_without_changing_e14(self):
        canonical = "Analiza mi entrenamiento de hoy"
        self.assertIsNone(self.resolve(canonical, factual_scope="today"))
        self.assertEqual(resolve_intent(canonical, now=self.JOB_TIME).primary_intent,
                         CoachIntent.ANALYZE_DAY)

    def test_plan_metric_and_change_queries_keep_their_existing_routes(self):
        for question in (
            "¿Qué toca mañana?",
            "¿Qué sesión tenía planificada hoy?",
            "¿Qué opinas de la sesión prevista de hoy?",
            "¿Cuál fue mi pulso máximo de hoy?",
            "Analiza el pulso máximo de mi entrenamiento de hoy",
            "¿Cuál fue mi ritmo de hoy?",
            "Cambia la sesión de hoy",
            "¿Debería cambiar el plan esta semana?",
            "Analiza mi entrenamiento de hoy y cambia el plan",
        ):
            with self.subTest(question=question):
                self.assertIsNone(self.resolve(question))

    def test_missing_ambiguous_or_future_date_does_not_guess_a_week(self):
        for question in (
            "¿Qué opinas de mi entrenamiento?",
            "Valora mi entrenamiento del 31/02/2026",
            "Analiza mi entrenamiento mañana",
            "Analiza mi entrenamiento de hoy y del 21/10/2026",
        ):
            with self.subTest(question=question):
                self.assertIsNone(self.resolve(question))

    def test_now_must_be_timezone_aware(self):
        with self.assertRaises(ValueError):
            self.resolve("analiza mi entrenamiento de hoy", now=datetime(2026, 10, 27, 22, 30))


if __name__ == "__main__":
    unittest.main()
