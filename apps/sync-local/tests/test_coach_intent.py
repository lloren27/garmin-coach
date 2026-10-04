import unittest
from datetime import date

from garmin_sync.coach_intent import (
    ClarificationCode,
    CoachIntent,
    DateSelector,
    IntentComponent,
    IntentResolution,
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


if __name__ == "__main__":
    unittest.main()
