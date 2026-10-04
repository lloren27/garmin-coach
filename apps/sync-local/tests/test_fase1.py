import copy
import json
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock

from garmin_sync import sync
from garmin_sync.ai_worker import compact_context
from garmin_sync.activity_merge import merge_activities
from garmin_sync.coach_generation_context import build_snapshot
from garmin_sync.coach_generation_resolver import evidence_wire
from garmin_sync.zepp_provider import ZeppProvider

NOW = datetime(2026, 10, 4, 12, tzinfo=ZoneInfo('Europe/Madrid'))

def activity(source, identifier):
    return dict(id=identifier, source=source, source_activity_id=identifier,
                source_device='watch', sport='running', date='2026-10-04',
                started_at='2026-10-04T09:00:00+02:00', km=11, duration_s=3300)

class PhaseOneTests(unittest.TestCase):
    def test_injected_range_is_independent_of_machine_date(self):
        self.assertEqual(sync._strava_activity_date_range(today=date(2026, 9, 29)),
                         (date(2026, 7, 31), date(2026, 9, 29)))

    def test_merge_retains_origins_without_mutating_inputs(self):
        left, right = activity('garmin', 'g1'), activity('strava', 's1')
        original = copy.deepcopy([left, right])
        result = merge_activities([left], [], [right])
        self.assertEqual(len(result), 1)
        self.assertEqual({(r['source'], r['source_activity_id']) for r in result[0]['source_records']},
                         {('garmin', 'g1'), ('strava', 's1')})
        self.assertEqual([left, right], original)
        self.assertEqual(merge_activities(result, [], [right]), result)

    def test_same_provider_sessions_and_ambiguous_match_are_not_merged(self):
        a, b, c = activity('garmin', 'a'), activity('garmin', 'b'), activity('strava', 'c')
        result = merge_activities([a, b], [], [c])
        self.assertEqual(len(result), 3)
        self.assertEqual(len(next(r for r in result if r['id']=='c')['duplicate_candidates']), 2)

    def test_inverse_ambiguity_and_duration_mismatch_remain_separate(self):
        a, b, c = activity('garmin', 'a'), activity('strava', 'b'), activity('strava', 'c')
        self.assertEqual(len(merge_activities([a], [], [b, c])), 3)
        b['duration_s'] = 6000
        self.assertEqual(len(merge_activities([a], [], [b])), 2)

    def test_sleep_equivalent_offsets_and_incomplete_input(self):
        from garmin_sync.wellness_models import deduplicate_sleep_sessions, NormalizedWellness
        p = ZeppProvider('x', 'y')
        a = p._normalize_sleep(dict(start='2026-10-24T21:30:00Z', end='2026-10-25T06:30:00Z', total_minutes=520))
        b = p._normalize_sleep(dict(start='2026-10-24T23:30:00+02:00', end='2026-10-25T07:30:00+01:00', total_minutes=520))
        self.assertEqual(len(deduplicate_sleep_sessions([a, b])), 1)
        self.assertEqual(NormalizedWellness(sleep=a).wellness_date('Europe/Madrid'), '2026-10-25')
        self.assertIsNone(p._normalize_sleep({'start': a.start, 'total_minutes': 520}))
        self.assertIsNone(p._normalize_sleep(dict(start=a.end, end=a.start, total_minutes=520)))
        self.assertIsNone(p._normalize_sleep(dict(start='2026-10-25T02:30:00', end=a.end, total_minutes=200)))

    def test_source_device_and_links_survive_compaction_snapshot_wire(self):
        row = activity('strava', 's1')
        row['source_records'] = [dict(source='strava', source_activity_id='s1', source_device='watch')]
        context = {'sync': {'payload': {'summary': {'activities': [row]}}}}
        compact = compact_context(context, now=NOW)
        snapshot = build_snapshot('hoy', compact, now=NOW)
        record = snapshot.evidence['activity:s1']
        self.assertEqual(record.source, 'strava')
        self.assertEqual(evidence_wire(record).source, 'strava')
        public = snapshot.public_context()['available_evidence'][0]
        self.assertEqual(public['source_device'], 'watch')
        self.assertEqual(public['source_records'], row['source_records'])
        row.pop('source')
        unknown = build_snapshot('hoy', compact_context(context, now=NOW), now=NOW)
        self.assertEqual(unknown.evidence['activity:s1'].source, 'unknown')

    def test_provider_failures_and_old_measurements_survive_snapshot(self):
        context = {'sync': {'payload': {'generated_at': NOW.isoformat(),
            'activity_provider_status': {'strava': {'status':'network_error'}},
            'wellness': {'schema_version':2, 'provider_status': {'zepp': {'status':'auth_error'}},
                'effective': {'sleep': {'source':'zepp','date':'2026-10-02','total_minutes':400}}}}},
            'wattwise_live': {'status':'unavailable', 'reason':'connection_error'}}
        snapshot = build_snapshot('hoy', compact_context(context, now=NOW), now=NOW)
        public = snapshot.public_context()
        self.assertEqual(public['provider_status']['strava.activities']['state'], 'provider_error')
        self.assertEqual(public['provider_status']['zepp.wellness']['state'], 'provider_error')
        self.assertEqual(public['provider_status']['wattwise']['state'], 'provider_error')
        sleep = next(e for e in public['available_evidence'] if e['kind']=='wellness')
        self.assertEqual(sleep['freshness'], 'stale')
        self.assertNotEqual(snapshot.freshness, 'current')

    def test_band_sleep_uses_elapsed_instants_at_dst(self):
        provider = ZeppProvider('x','y')
        start = datetime.fromisoformat('2026-10-24T21:30:00+00:00').timestamp()
        end = datetime.fromisoformat('2026-10-25T06:30:00+00:00').timestamp()
        client = Mock()
        client.get_band_data.return_value = {'summary':{'slp':{'st':start,'ed':end}}}
        result = provider._sleep_from_band_data(client, date(2026,10,25))
        self.assertEqual(result.total_minutes, 540)
        self.assertEqual(result.to_dict()['timezone'], 'Europe/Madrid')

    def test_direct_sleep_preserves_provider_sleep_duration(self):
        result = ZeppProvider('x','y')._normalize_sleep({'start':'2026-10-24T21:30:00Z',
            'end':'2026-10-25T06:30:00Z','total_minutes':520,'awake_minutes':20})
        self.assertEqual(result.total_minutes, 520)  # sleep duration is not time in bed
        self.assertEqual(result.to_dict()['elapsed_minutes'], 540)
        self.assertEqual(result.to_dict()['timezone'], 'Europe/Madrid')
