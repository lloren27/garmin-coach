import copy
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext, ROUND_UP
import json
from pathlib import Path
import sys
import unittest

from garmin_sync.coach_analysis import build_analysis_facts, MatchState, Unit
from garmin_sync.coach_generation_context import build_snapshot, freeze

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'docs/restructuring/fase3_evaluacion'))
from verify_protocol import materialize, verify

FIXTURES = json.loads((ROOT / 'docs/restructuring/fase3_evaluacion/v1/fixtures.json').read_text())


def fixture(name='E01'):
    if name in FIXTURES['base_fixtures']:
        return copy.deepcopy(FIXTURES['base_fixtures'][name])
    return materialize(FIXTURES, next(v for v in FIXTURES['variants'] if v['id'] == name))


def snapshot(name='E01', question='analiza hoy', mutate=None, now=None):
    case = fixture(name)
    if mutate:
        mutate(case['estado_inicial']['extra_context'])
    return build_snapshot(question, case['estado_inicial'],
                          now=now or datetime.fromisoformat(case['now']))


class AnalysisTests(unittest.TestCase):
    def test_frozen_protocol_unchanged(self):
        self.assertEqual(verify(), [])

    def test_reference_match_states(self):
        for name, state in [('E01', MatchState.IMPLAUSIBLE_SINGLE),
                            ('R01', MatchState.CANDIDATE),
                            ('MATCH-confirmed', MatchState.CONFIRMED),
                            ('MATCH-warmup', MatchState.IMPLAUSIBLE_SINGLE),
                            ('MATCH-multiple', MatchState.AMBIGUOUS_MULTIPLE),
                            ('MATCH-insufficient', MatchState.INSUFFICIENT_DATA),
                            ('MATCH-within', MatchState.CANDIDATE)]:
            with self.subTest(name=name):
                self.assertEqual(build_analysis_facts(snapshot(name)).matches[0].state, state)

    def test_implausible_retains_magnitudes_without_compliance(self):
        match = build_analysis_facts(snapshot()).matches[0]
        c = match.comparisons[0]
        self.assertEqual((c.observed, c.lower, c.upper), (6304, 2100, 2700))
        self.assertIsNone(c.delta)
        self.assertIsNone(c.percent)
        self.assertTrue(c.outside_band)

    def test_confirmed_duration_comparison(self):
        c = build_analysis_facts(snapshot('MATCH-confirmed')).matches[0].comparisons[0]
        self.assertEqual(c.delta, 3604)
        self.assertEqual(round(c.percent, 1), Decimal('133.5'))
        self.assertEqual(c.reference, 2700)

    def test_r01_distance_and_pace(self):
        result = build_analysis_facts(snapshot('R01'))
        c = result.matches[0].comparisons[0]
        self.assertEqual(c.unit, Unit.KILOMETRES)
        self.assertEqual(c.delta, Decimal('-5.99'))
        self.assertEqual(round(c.percent, 1), Decimal('-35.2'))
        pace = next(f for f in result.facts if f.metric == 'pace_s_per_km')
        self.assertEqual(round(pace.value), 305)
        self.assertEqual(pace.unit, Unit.SECONDS_PER_KM)
        self.assertEqual(len(pace.operand_refs), 2)
        self.assertIn('PACE_DURATION_BASIS_UNSPECIFIED', result.limitations)

    def test_range_boundaries_and_inside(self):
        for duration, reference, delta in [(2100, 2100, 0), (2400, 2400, 0),
                                            (2700, 2700, 0), (1800, 2100, -300)]:
            with self.subTest(duration=duration):
                result = build_analysis_facts(snapshot(mutate=lambda x: x['recent_activities'][0].update(duration_s=duration)))
                c = result.matches[0].comparisons[0]
                self.assertEqual((c.reference, c.delta), (reference, delta))

    def test_multiple_does_not_choose_by_ratio(self):
        result = build_analysis_facts(snapshot('MATCH-multiple'))
        self.assertEqual(len(result.matches[0].activity_refs), 2)
        self.assertEqual(result.matches[0].comparisons, ())

    def test_multiple_sessions_do_not_choose_one(self):
        def mutate(x):
            x['training_plan']['sessions'].append(dict(x['training_plan']['sessions'][0], id='other'))
        match = build_analysis_facts(snapshot(mutate=mutate)).matches[0]
        self.assertEqual(match.state, MatchState.AMBIGUOUS_MULTIPLE)
        self.assertEqual(match.comparisons, ())

    def test_conflicting_confirmed_links_are_not_selected(self):
        def mutate(x):
            session = x['training_plan']['sessions'][0]
            session['completed_activity_id'] = 'synthetic-g1'
            x['training_plan']['sessions'].append(dict(session, id='other'))
        match = build_analysis_facts(snapshot(mutate=mutate)).matches[0]
        self.assertEqual(match.state, MatchState.AMBIGUOUS_MULTIPLE)

    def test_invalid_link_does_not_become_candidate(self):
        def mutate(x):
            x['training_plan']['sessions'][0]['completed_activity_id'] = 'missing'
        match = build_analysis_facts(snapshot(mutate=mutate)).matches[0]
        self.assertEqual(match.state, MatchState.INSUFFICIENT_DATA)

    def test_all_comparable_dimensions_must_be_plausible(self):
        def mutate(x):
            x['training_plan']['sessions'][0]['distance_km'] = 20
        match = build_analysis_facts(snapshot(mutate=mutate)).matches[0]
        self.assertEqual(match.state, MatchState.IMPLAUSIBLE_SINGLE)
        self.assertEqual(len(match.comparisons), 2)
        self.assertTrue(all(c.percent is None for c in match.comparisons))

    def test_bad_duration_is_not_zero_or_a_pace(self):
        for bad in [0, -1, float('nan'), float('inf'), True]:
            with self.subTest(bad=bad):
                result = build_analysis_facts(snapshot(mutate=lambda x: x['recent_activities'][0].update(duration_s=bad)))
                self.assertEqual(result.matches[0].state, MatchState.INSUFFICIENT_DATA)
                self.assertFalse(any(f.metric == 'pace_s_per_km' for f in result.facts))

    def test_reversed_plan_range_is_not_compared(self):
        def mutate(x):
            x['training_plan']['sessions'][0].update(duration_min=45, duration_max=35)
        result = build_analysis_facts(snapshot(mutate=mutate))
        self.assertEqual(result.matches[0].state, MatchState.INSUFFICIENT_DATA)
        self.assertIn('INVALID_PLAN_RANGE', result.limitations)

    def test_incomplete_range_does_not_become_scalar_target(self):
        def mutate(x):
            x['training_plan']['sessions'][0].pop('duration_max')
        result = build_analysis_facts(snapshot(mutate=mutate))
        self.assertEqual(result.matches[0].state, MatchState.INSUFFICIENT_DATA)
        self.assertEqual(result.matches[0].comparisons, ())

    def test_coverage_error_is_not_no_activity(self):
        result = build_analysis_facts(snapshot('E07'))
        self.assertNotIn('ACTIVITY_NOT_RECORDED', result.limitations)
        self.assertIn('DATA_COVERAGE_INCOMPLETE', result.limitations)
        self.assertEqual(result.matches[0].state, MatchState.INSUFFICIENT_DATA)

    def test_absence_requires_explicit_period_coverage(self):
        def mutate(x):
            x['activity_provider_status'] = {
                'garmin': {'status': 'ok', 'records_received': 0,
                           'last_success_at': '2026-10-03T21:00:00+02:00',
                           'period_start': '2026-10-03', 'period_end': '2026-10-03'},
                'strava': {'status': 'disabled'}, 'zepp': {'status': 'disabled'}}
        snap = snapshot('E07', mutate=mutate)
        self.assertIn('ACTIVITY_NOT_RECORDED', build_analysis_facts(snap).limitations)
        statuses = {k: dict(v) for k, v in snap.provider_status.items()}
        statuses['garmin.activities']['period_end'] = '2026-10-02'
        result = build_analysis_facts(replace(snap, provider_status=freeze(statuses)))
        self.assertNotIn('ACTIVITY_NOT_RECORDED', result.limitations)

    def test_symptom_and_wellness_preserve_source(self):
        result = build_analysis_facts(snapshot('E10'))
        pain = next(f for f in result.facts if f.metric == 'pain')
        self.assertIs(pain.value, True)
        self.assertEqual(pain.source, 'checkin')
        sleep = next(f for f in result.facts if f.metric == 'total_minutes')
        self.assertEqual((sleep.value, sleep.unit, sleep.source), (430, Unit.MINUTES, 'zepp'))
        self.assertIn('WELLNESS_BASELINE_NOT_ESTABLISHED', result.limitations)

    def test_stale_wellness_is_not_borrowed_into_today(self):
        result = build_analysis_facts(snapshot('E06'))
        self.assertFalse(any(f.metric == 'total_minutes' for f in result.facts))
        self.assertIn('DATA_COVERAGE_INCOMPLETE', result.limitations)

    def test_component_scope_and_utc_midnight(self):
        snap = snapshot(question='analiza hoy y dime qué hacer mañana',
                        now=datetime(2026, 10, 3, 22, 30, tzinfo=timezone.utc))
        result = build_analysis_facts(snap)
        self.assertEqual(result.observed_dates, (date(2026, 10, 4),))
        self.assertEqual(result.facts, ())
        advice = build_analysis_facts(snap, component_index=1)
        self.assertEqual(advice.facts, ())
        self.assertIn('NO_OBSERVED_SCOPE', advice.limitations)

    def test_latest_activity_tie_not_chosen_by_id(self):
        result = build_analysis_facts(snapshot('MATCH-multiple', question='analiza la última actividad'))
        self.assertIn('LATEST_ACTIVITY_AMBIGUOUS', result.limitations)
        self.assertEqual(result.facts, ())

    def test_deep_immutability_determinism_and_operand_references(self):
        snap = snapshot('MATCH-confirmed')
        before = snap.public_context()
        result = build_analysis_facts(snap)
        self.assertEqual(result, build_analysis_facts(snap))
        self.assertEqual(before, snap.public_context())
        ids = {f.id for f in result.facts}
        self.assertEqual(len(ids), len(result.facts))
        for fact in result.facts:
            self.assertTrue(set(fact.operand_refs) <= ids)
            self.assertIs(type(fact.date), date)
            for ref in fact.source_refs:
                self.assertTrue(ref in snap.evidence or ref.removeprefix('session:') in snap.sessions)
        with self.assertRaises(FrozenInstanceError):
            result.facts[0].value = 0
        with self.assertRaises(TypeError):
            result.provider_status['garmin.activities']['state'] = 'available'

    def test_mixed_sports_not_summed(self):
        result = build_analysis_facts(snapshot('E09'))
        self.assertIn('MULTISPORT_COMPONENTS_SEPARATE', result.limitations)
        self.assertEqual({f.sport for f in result.facts if f.metric == 'duration_s'},
                         {'running', 'cycling', 'strength'})

    def test_decimal_context_does_not_change_facts(self):
        snap = snapshot('R01')
        expected = build_analysis_facts(snap)
        with localcontext() as ctx:
            ctx.prec = 6
            ctx.rounding = ROUND_UP
            self.assertEqual(build_analysis_facts(snap), expected)

    def test_secondary_provenance_is_detached_and_immutable(self):
        def mutate(x):
            x['recent_activities'][0]['source_records'] = [
                {'source': 'garmin', 'source_activity_id': 'synthetic-g1'},
                {'source': 'strava', 'source_activity_id': 'secondary'}]
        result = build_analysis_facts(snapshot(mutate=mutate))
        duration = next(f for f in result.facts if f.metric == 'duration_s')
        self.assertEqual(duration.source_records[1]['source'], 'strava')
        with self.assertRaises(TypeError):
            duration.source_records[1]['source'] = 'unknown'
        self.assertEqual(duration.coverage, 'unknown')

    def test_no_plan_available_vs_no_plan_context(self):
        result = build_analysis_facts(snapshot('E08'))
        self.assertEqual(result.matches[0].state, MatchState.NONE)
        result = build_analysis_facts(snapshot(mutate=lambda x: x.pop('training_plan')))
        self.assertEqual(result.matches[0].state, MatchState.INSUFFICIENT_DATA)

    def test_two_analysis_components_keep_own_dates(self):
        result = snapshot(question='analiza ayer y analiza hoy')
        yesterday = build_analysis_facts(result, 0)
        today = build_analysis_facts(result, 1)
        self.assertEqual(yesterday.facts, ())
        self.assertTrue(today.facts)
        self.assertTrue(all(f.date == date(2026, 10, 3) for f in today.facts))
        self.assertTrue(all(f.id.startswith('c1:') for f in today.facts))

    def test_dst_day_preserves_local_date(self):
        def mutate(x):
            x['recent_activities'][0]['date'] = '2026-10-25'
            x['training_plan']['sessions'][0]['date'] = '2026-10-25'
        for hour in (0, 1):
            result = build_analysis_facts(snapshot(mutate=mutate,
                now=datetime(2026, 10, 25, hour, 30, tzinfo=timezone.utc)))
            self.assertEqual(result.observed_dates, (date(2026, 10, 25),))
            self.assertEqual(result.matches[0].state, MatchState.IMPLAUSIBLE_SINGLE)


if __name__ == '__main__':
    unittest.main()
