import unittest
from datetime import date, datetime, timezone

from garmin_sync.coach_intent import (
    ClarificationCode,
    CoachIntent,
    DateSelector,
    IntentComponent,
    IntentResolution,
    DateResolutionScope,
    InvalidDateError,
    resolve_dates,
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
        self.assertEqual(self.dates("esta mañana"), ())
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


if __name__ == "__main__":
    unittest.main()
