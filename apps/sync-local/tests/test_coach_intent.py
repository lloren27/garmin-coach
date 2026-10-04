import unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from garmin_sync.coach_intent import (
    ClarificationCode,
    CoachIntent,
    DateSelector,
    IntentComponent,
    IntentResolution,
    DateResolutionScope,
    InvalidDateError,
    resolve_dates,
    resolve_intent,
    clarification_prompt,
)


class IntentContractTests(unittest.TestCase):
    def test_dates_are_date_objects_and_resolution_aggregates_them(self):
        observed = date(2026, 10, 4)
        advice = date(2026, 10, 5)
        analysis = IntentComponent(
            intent=CoachIntent.ANALYZE_DAY,
            selector=DateSelector.BY_DATE,
            observed_dates=(observed,),
        )
        recommendation = IntentComponent(
            intent=CoachIntent.RECOMMEND_NEXT,
            selector=DateSelector.BY_DATE,
            advice_dates=(advice,),
        )

        result = IntentResolution(components=(analysis, recommendation))

        self.assertIsInstance(result.observed_dates[0], date)
        self.assertEqual(result.observed_dates, (observed,))
        self.assertEqual(result.advice_dates, (advice,))
        self.assertEqual(result.primary_intent, CoachIntent.MIXED)
        self.assertEqual(result.selector, DateSelector.BY_DATE)
        self.assertFalse(result.change_requested)

    def test_primary_intent_is_derived_from_a_single_component(self):
        component = IntentComponent(
            intent=CoachIntent.ANALYZE_DAY,
            selector=DateSelector.BY_DATE,
            observed_dates=(date(2026, 10, 4),),
        )

        result = IntentResolution(components=(component,))

        self.assertEqual(result.primary_intent, CoachIntent.ANALYZE_DAY)
        self.assertEqual(result.selector, DateSelector.BY_DATE)

    def test_selector_is_none_when_components_use_different_selectors(self):
        by_date = IntentComponent(CoachIntent.ANALYZE_DAY, DateSelector.BY_DATE)
        latest = IntentComponent(CoachIntent.ANALYZE_ACTIVITY, DateSelector.LATEST_ACTIVITY)

        self.assertIsNone(IntentResolution((by_date, latest)).selector)

    def test_repeated_same_intent_does_not_become_mixed(self):
        first = IntentComponent(CoachIntent.ANALYZE_DAY, DateSelector.BY_DATE)
        second = IntentComponent(CoachIntent.ANALYZE_DAY, DateSelector.BY_DATE)

        self.assertEqual(
            IntentResolution((first, second)).primary_intent,
            CoachIntent.ANALYZE_DAY,
        )

    def test_mixed_is_derived_and_cannot_be_a_component_intent(self):
        with self.assertRaises(ValueError):
            IntentComponent(CoachIntent.MIXED, DateSelector.BY_DATE)

    def test_clarify_requires_a_code_and_other_intents_forbid_one(self):
        with self.assertRaises(ValueError):
            IntentComponent(CoachIntent.CLARIFY, DateSelector.BY_DATE)
        with self.assertRaises(ValueError):
            IntentComponent(
                CoachIntent.ANALYZE_DAY,
                DateSelector.BY_DATE,
                clarification_code=ClarificationCode.NO_SCOPE,
            )

    def test_latest_selector_cannot_carry_explicit_dates(self):
        with self.assertRaises(ValueError):
            IntentComponent(
                CoachIntent.ANALYZE_ACTIVITY,
                DateSelector.LATEST_ACTIVITY,
                observed_dates=(date(2026, 10, 4),),
            )

    def test_change_permission_is_derived_from_an_explicit_change_component(self):
        change = IntentComponent(CoachIntent.REQUEST_CHANGE, DateSelector.BY_DATE)
        analysis = IntentComponent(CoachIntent.ANALYZE_DAY, DateSelector.BY_DATE)

        self.assertTrue(IntentResolution((change, analysis)).change_requested)
        self.assertFalse(IntentResolution((analysis,)).change_requested)


class DateResolutionTests(unittest.TestCase):
    NOW = datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc)

    def dates(self, text, scope=DateResolutionScope.OBSERVED, now=None):
        return resolve_dates(text, now=now or self.NOW, scope=scope)

    def test_relative_days_use_madrid_civil_date(self):
        self.assertEqual(self.dates("hoy"), (date(2026, 10, 4),))
        self.assertEqual(self.dates("ayer"), (date(2026, 10, 3),))
        self.assertEqual(
            self.dates("mañana", DateResolutionScope.ADVICE),
            (date(2026, 10, 5),),
        )

    def test_morning_time_expression_is_not_tomorrow(self):
        self.assertEqual(self.dates("esta mañana"), (date(2026, 10, 4),))
        self.assertEqual(self.dates("por la mañana"), ())

    def test_explicit_iso_and_spanish_numeric_dates(self):
        self.assertEqual(self.dates("2026-10-04"), (date(2026, 10, 4),))
        self.assertEqual(self.dates("04/10/2026"), (date(2026, 10, 4),))

    def test_month_day_without_year_uses_past_or_next_occurrence(self):
        january = datetime(2027, 1, 5, 12, tzinfo=timezone.utc)
        self.assertEqual(
            self.dates("el 20 de diciembre", now=january),
            (date(2026, 12, 20),),
        )
        self.assertEqual(
            self.dates("el 20 de diciembre", DateResolutionScope.ADVICE, now=january),
            (date(2027, 12, 20),),
        )

    def test_bare_weekday_on_sunday_means_today_for_observation(self):
        self.assertEqual(self.dates("el domingo"), (date(2026, 10, 4),))

    def test_weekday_modifiers_are_strictly_past_or_future(self):
        self.assertEqual(self.dates("el domingo pasado"), (date(2026, 9, 27),))
        self.assertEqual(
            self.dates("el próximo domingo", DateResolutionScope.ADVICE),
            (date(2026, 10, 11),),
        )
        self.assertEqual(self.dates("el martes pasado"), (date(2026, 9, 29),))

    def test_this_week_respects_scope(self):
        tuesday = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)
        observed = tuple(date(2026, 10, day) for day in (5, 6))
        advice = tuple(date(2026, 10, day) for day in range(6, 12))
        plan = tuple(date(2026, 10, day) for day in range(5, 12))
        self.assertEqual(self.dates("esta semana", now=tuesday), observed)
        self.assertEqual(self.dates("esta semana", DateResolutionScope.ADVICE, tuesday), advice)
        self.assertEqual(self.dates("esta semana", DateResolutionScope.PLAN, tuesday), plan)

    def test_previous_and_next_weeks_are_monday_to_sunday(self):
        self.assertEqual(
            self.dates("semana pasada"),
            tuple(date(2026, 9, day) for day in range(21, 28)),
        )
        self.assertEqual(
            self.dates("próxima semana", DateResolutionScope.ADVICE),
            tuple(date(2026, 10, day) for day in range(5, 12)),
        )

    def test_impossible_date_raises_instead_of_silent_correction(self):
        with self.assertRaises(InvalidDateError):
            self.dates("31/02/2026")

    def test_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            self.dates("hoy", now=datetime(2026, 10, 4, 12))

    def test_dst_day_uses_civil_dates_not_elapsed_hours(self):
        dst_start = datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(
            self.dates("hoy", now=dst_start),
            (date(2026, 10, 25),),
        )
        self.assertEqual(
            self.dates("mañana", DateResolutionScope.ADVICE, dst_start),
            (date(2026, 10, 26),),
        )


class IntentClassificationTests(unittest.TestCase):
    NOW = datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc)

    def resolve(self, question):
        return resolve_intent(question, now=self.NOW)

    def test_analysis_today_is_one_component(self):
        result = self.resolve("analiza hoy")
        self.assertEqual(result.primary_intent, CoachIntent.ANALYZE_DAY)
        self.assertEqual(len(result.components), 1)
        self.assertEqual(result.observed_dates, (date(2026, 10, 4),))
        self.assertEqual(result.advice_dates, ())

    def test_two_dates_joined_by_y_remain_one_analysis_component(self):
        result = self.resolve("analiza ayer y hoy")
        self.assertEqual(len(result.components), 1)
        self.assertEqual(result.primary_intent, CoachIntent.ANALYZE_DAY)
        self.assertEqual(result.observed_dates, (date(2026, 10, 3), date(2026, 10, 4)))

    def test_latest_activity_and_latest_training_day_selectors(self):
        activity = self.resolve("analiza mi última actividad")
        training_day = self.resolve("analiza mi último día de entrenamiento")
        self.assertEqual(activity.selector, DateSelector.LATEST_ACTIVITY)
        self.assertEqual(training_day.selector, DateSelector.LATEST_TRAINING_DAY)

    def test_plan_weekday_and_past_month_dates_follow_intent(self):
        future_plan = self.resolve("qué toca el domingo")
        past_plan = self.resolve("qué tocaba el 3 de octubre")
        self.assertEqual(future_plan.advice_dates, (date(2026, 10, 11),))
        self.assertEqual(past_plan.observed_dates, (date(2026, 10, 3),))

    def test_latest_selector_with_explicit_date_is_clarified(self):
        result = self.resolve("analiza mi última actividad de ayer")
        self.assertEqual(result.primary_intent, CoachIntent.CLARIFY)
        self.assertEqual(result.components[0].clarification_code, ClarificationCode.CONFLICTING_SCOPE)

    def test_plan_query_and_future_advice_have_distinct_date_scope(self):
        plan = self.resolve("qué toca mañana")
        recommendation = self.resolve("dime qué hacer mañana")
        self.assertEqual(plan.primary_intent, CoachIntent.CONSULT_PLAN)
        self.assertEqual(plan.advice_dates, (date(2026, 10, 5),))
        self.assertEqual(recommendation.primary_intent, CoachIntent.RECOMMEND_NEXT)
        self.assertEqual(recommendation.advice_dates, (date(2026, 10, 5),))

    def test_past_plan_question_uses_observed_dates(self):
        result = self.resolve("qué tocaba ayer")
        self.assertEqual(result.primary_intent, CoachIntent.CONSULT_PLAN)
        self.assertEqual(result.observed_dates, (date(2026, 10, 3),))
        self.assertEqual(result.advice_dates, ())

    def test_advice_without_date_is_clarified(self):
        result = self.resolve("dime qué hacer")
        self.assertEqual(result.primary_intent, CoachIntent.CLARIFY)
        self.assertEqual(result.components[0].clarification_code, ClarificationCode.MISSING_ADVICE_DATE)

    def test_mixed_analysis_and_advice_keep_dates_in_their_own_components(self):
        result = self.resolve("analiza hoy y dime qué hacer mañana")
        self.assertEqual(result.primary_intent, CoachIntent.MIXED)
        self.assertEqual([item.intent for item in result.components], [
            CoachIntent.ANALYZE_DAY, CoachIntent.RECOMMEND_NEXT,
        ])
        self.assertEqual(result.components[0].observed_dates, (date(2026, 10, 4),))
        self.assertEqual(result.components[0].advice_dates, ())
        self.assertEqual(result.components[1].observed_dates, ())
        self.assertEqual(result.components[1].advice_dates, (date(2026, 10, 5),))

    def test_modal_change_question_after_y_starts_a_separate_advice_clause(self):
        result = self.resolve("analiza hoy y ¿debería cambiar la sesión de mañana?")
        self.assertEqual(result.primary_intent, CoachIntent.MIXED)
        self.assertEqual([item.intent for item in result.components], [
            CoachIntent.ANALYZE_DAY, CoachIntent.RECOMMEND_NEXT,
        ])
        self.assertFalse(result.change_requested)

    def test_comma_does_not_separate_context_from_its_question(self):
        result = self.resolve(
            "Con el sueño y pulso de hoy 2026-10-03, ¿estoy mejor recuperado que de costumbre?"
        )
        self.assertEqual(result.primary_intent, CoachIntent.ANALYZE_DAY)
        self.assertEqual(len(result.components), 1)
        self.assertEqual(result.observed_dates, (date(2026, 10, 3), date(2026, 10, 4)))

    def test_analysis_and_change_form_separate_components(self):
        result = self.resolve("analiza y cambia el plan")
        self.assertEqual(result.primary_intent, CoachIntent.MIXED)
        self.assertEqual([item.intent for item in result.components], [
            CoachIntent.CLARIFY, CoachIntent.REQUEST_CHANGE,
        ])
        self.assertTrue(result.change_requested)

    def test_negation_does_not_propagate_to_following_clause(self):
        result = self.resolve("no cambies el plan, analiza hoy")
        self.assertEqual(result.primary_intent, CoachIntent.ANALYZE_DAY)
        self.assertEqual(len(result.components), 1)
        self.assertFalse(result.change_requested)

    def test_negated_analysis_does_not_suppress_following_plan_question(self):
        result = self.resolve("no analices, dime qué toca mañana")
        self.assertEqual(result.primary_intent, CoachIntent.CONSULT_PLAN)
        self.assertEqual(len(result.components), 1)
        self.assertEqual(result.advice_dates, (date(2026, 10, 5),))

    def test_undated_plan_question_after_negated_analysis_is_clarified(self):
        result = self.resolve("no analices, dime qué toca")
        self.assertEqual(result.primary_intent, CoachIntent.CLARIFY)
        self.assertFalse(result.change_requested)

    def test_same_clause_positive_and_negative_change_is_contradictory(self):
        result = self.resolve("cambia la sesión pero no modifiques la sesión")
        self.assertEqual(result.primary_intent, CoachIntent.CLARIFY)
        self.assertEqual(
            result.components[0].clarification_code,
            ClarificationCode.CONTRADICTORY_OPERATION,
        )
        self.assertFalse(result.change_requested)

    def test_change_requires_explicit_plan_object_and_is_not_advice_question(self):
        command = self.resolve("cambia la sesión de mañana")
        advice = self.resolve("¿debería cambiar la sesión de mañana?")
        self.assertEqual(command.primary_intent, CoachIntent.REQUEST_CHANGE)
        self.assertTrue(command.change_requested)
        self.assertEqual(command.advice_dates, (date(2026, 10, 5),))
        self.assertEqual(advice.primary_intent, CoachIntent.RECOMMEND_NEXT)
        self.assertFalse(advice.change_requested)

    def test_past_change_target_is_clarified_and_cannot_request_change(self):
        result = self.resolve("cambia la sesión de ayer")
        self.assertEqual(result.primary_intent, CoachIntent.CLARIFY)
        self.assertEqual(result.components[0].clarification_code, ClarificationCode.PAST_CHANGE_DATE)
        self.assertFalse(result.change_requested)

    def test_changing_pace_or_shoes_is_not_a_plan_change(self):
        for question in ("cambiar de ritmo", "cambiar de zapatillas", "cambia el ritmo"):
            with self.subTest(question=question):
                self.assertFalse(self.resolve(question).change_requested)

    def test_retro_expression_and_date_resolve_as_analysis_hint(self):
        for question in ("¿cómo fue lo del domingo?", "¿qué tal lo del domingo?"):
            with self.subTest(question=question):
                result = self.resolve(question)
                self.assertEqual(result.primary_intent, CoachIntent.ANALYZE_DAY)
                self.assertEqual(result.observed_dates, (date(2026, 10, 4),))

    def test_invalid_explicit_date_returns_fixed_clarification_code(self):
        result = self.resolve("analiza el 31/02/2026")
        self.assertEqual(result.primary_intent, CoachIntent.CLARIFY)
        self.assertEqual(result.components[0].clarification_code, ClarificationCode.INVALID_DATE)

    def test_unknown_request_has_fixed_clarification_code_without_echoing_input(self):
        question = "la sesión morada"
        result = self.resolve(question)
        self.assertEqual(result.primary_intent, CoachIntent.CLARIFY)
        self.assertEqual(result.components[0].clarification_code, ClarificationCode.UNSUPPORTED_PARAPHRASE)
        self.assertNotIn(question, str(result))


class ClarificationTests(unittest.TestCase):
    NOW = datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc)

    def resolve(self, question):
        return resolve_intent(question, now=self.NOW)

    def test_every_clarification_code_has_one_fixed_template(self):
        questions = {
            ClarificationCode.NO_SCOPE: "",
            ClarificationCode.CONTRADICTORY_OPERATION: "cambia la sesión pero no modifiques la sesión",
            ClarificationCode.UNSUPPORTED_PARAPHRASE: "la sesión morada",
            ClarificationCode.INVALID_DATE: "analiza 31/02/2026",
            ClarificationCode.MISSING_ADVICE_DATE: "dime qué hacer",
            ClarificationCode.PAST_CHANGE_DATE: "cambia la sesión de ayer",
            ClarificationCode.CONFLICTING_SCOPE: "analiza mi última actividad de ayer",
        }
        self.assertEqual(set(questions), set(ClarificationCode))

        for code, question in questions.items():
            with self.subTest(code=code):
                result = self.resolve(question)
                self.assertEqual(result.primary_intent, CoachIntent.CLARIFY)
                self.assertEqual(result.components[0].clarification_code, code)
                self.assertEqual(result.components[0].clarification_template_key, code.value)
                prompt = clarification_prompt(code)
                self.assertTrue(prompt)
                if question:
                    self.assertNotIn(question, prompt)

    def test_templates_reject_unknown_codes(self):
        with self.assertRaises((TypeError, ValueError)):
            clarification_prompt("no_scope")


class IntentRegressionCorpusTests(unittest.TestCase):
    NOW = datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc)
    EVALUATION_NOW = datetime(2026, 10, 3, 22, 0, tzinfo=timezone(timedelta(hours=2)))

    EVALUATION_PROMPTS = (
        ("E01", "Valora lo que he hecho hoy 2026-10-03 frente al plan y dime qué toca después.", CoachIntent.MIXED),
        ("E07", "¿He completado la sesión de hoy 2026-10-03?", CoachIntent.ANALYZE_DAY),
        ("E08", "Analiza hoy 2026-10-03: ¿cómo encaja esta actividad en mi plan?", CoachIntent.ANALYZE_DAY),
        ("E09", "Valora la carga conjunta de carrera, bici y fuerza de hoy 2026-10-03 y qué implica para mañana.", CoachIntent.MIXED),
        ("E10", "Tengo molestia en el gemelo. Valora la sesión de calidad de mañana.", CoachIntent.CONSULT_PLAN),
        ("E13", "Con el sueño y pulso de hoy 2026-10-03, ¿estoy mejor recuperado que de costumbre?", CoachIntent.ANALYZE_DAY),
        ("E14", "Analiza mi entrenamiento de hoy", CoachIntent.ANALYZE_DAY),
    )

    AUTHORED_PROMPTS = (
        ("Valora lo que he hecho hoy", CoachIntent.ANALYZE_DAY),
        ("¿Qué tal me fue ayer?", CoachIntent.ANALYZE_DAY),
        ("¿Cómo me salió el entreno del domingo?", CoachIntent.ANALYZE_DAY),
        ("Revisa la salida del martes pasado", CoachIntent.ANALYZE_DAY),
        ("Analiza mi última actividad", CoachIntent.ANALYZE_ACTIVITY),
        ("Repasa mi último día de entrenamiento", CoachIntent.ANALYZE_DAY),
        ("¿Qué toca mañana?", CoachIntent.CONSULT_PLAN),
        ("¿Qué tocaba ayer?", CoachIntent.CONSULT_PLAN),
        ("Dime qué hacer mañana", CoachIntent.RECOMMEND_NEXT),
        ("¿Qué debería hacer el jueves?", CoachIntent.RECOMMEND_NEXT),
        ("¿Debería cambiar la sesión del viernes?", CoachIntent.RECOMMEND_NEXT),
        ("Cambia la sesión de mañana", CoachIntent.REQUEST_CHANGE),
        ("Modifica el plan", CoachIntent.REQUEST_CHANGE),
        ("No cambies el plan, analiza hoy", CoachIntent.ANALYZE_DAY),
        ("Analiza hoy y dime qué hacer mañana", CoachIntent.MIXED),
        ("Analiza ayer y hoy", CoachIntent.ANALYZE_DAY),
        ("¿Cómo fue lo del domingo?", CoachIntent.ANALYZE_DAY),
        ("Cambia de ritmo", CoachIntent.CLARIFY),
        ("Cambia las zapatillas", CoachIntent.CLARIFY),
        ("Dime qué hacer", CoachIntent.CLARIFY),
        ("Esta mañana corrí", CoachIntent.CLARIFY),
        ("¿Qué tengo mañana?", CoachIntent.CLARIFY),
    )

    def test_evaluation_and_authored_prompts_match_reviewed_intent_outcomes(self):
        corpus = tuple((case_id, text, expected) for case_id, text, expected in self.EVALUATION_PROMPTS)
        corpus += tuple((f"manual-{index:02d}", text, expected)
                        for index, (text, expected) in enumerate(self.AUTHORED_PROMPTS, 1))
        clarify_count = 0
        component_clarify_count = 0
        outcome_counts = Counter()
        for case_id, question, expected in corpus:
            with self.subTest(case_id=case_id):
                now = self.EVALUATION_NOW if case_id.startswith("E") else self.NOW
                result = resolve_intent(question, now=now)
                self.assertEqual(result.primary_intent, expected)
                self.assertTrue(result.components)
                outcome_counts[result.primary_intent.value] += 1
                if expected is not CoachIntent.REQUEST_CHANGE:
                    self.assertFalse(result.change_requested)
                if expected is CoachIntent.CLARIFY:
                    clarify_count += 1
                component_clarify_count += sum(
                    component.intent is CoachIntent.CLARIFY for component in result.components
                )
        self.assertEqual(clarify_count, 5)
        self.assertEqual(component_clarify_count, 6)
        print(
            f"\nIntent corpus: {dict(sorted(outcome_counts.items()))}; "
            f"fully clarified={clarify_count}/{len(corpus)} "
            f"({clarify_count / len(corpus):.1%}); queries containing a clarify component="
            f"{component_clarify_count}/{len(corpus)}"
        )


if __name__ == "__main__":
    unittest.main()
