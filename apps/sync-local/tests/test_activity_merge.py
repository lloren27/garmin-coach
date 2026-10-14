from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from garmin_sync.activity_merge import merge_activities
from garmin_sync import sync
from garmin_sync.sync import normalize_activities, summarize_normalized, sport


def activity(
    activity_id: str,
    source: str,
    started_at: str,
    km: float,
    duration_s: int,
    avg_hr: int | None = None,
) -> dict:
    value = {
        "id": activity_id,
        "source": source,
        "date": started_at[:10],
        "started_at": started_at,
        "name": "Correr al aire libre",
        "sport": "running",
        "km": km,
        "duration_s": duration_s,
    }
    if avg_hr is not None:
        value["avg_hr"] = avg_hr
    return value


class ActivityMergeTests(unittest.TestCase):
    def test_deduplication_preserves_each_source_max_hr_value(self):
        garmin = activity("edge", "garmin", "2026-10-05T17:46:29+02:00", 40.66, 6156, 112)
        strava = activity("strava:edge", "strava", "2026-10-05T15:46:29Z", 40.66, 6156, 112)
        garmin.update(sport='cycling', max_hr=188)
        strava.update(sport='cycling', max_hr=176)
        merged = merge_activities([garmin], [], [strava])
        self.assertEqual(len(merged), 1)
        values = {record['source']: record['metrics']['max_hr']
                  for record in merged[0]['source_records']}
        self.assertEqual(values, {'garmin': 188, 'strava': 176})

    def test_garmin_sport_uses_structured_type_not_editable_event_name(self):
        cases = {
            "running": "running", "trail_running": "running", "track_running": "running",
            "treadmill_running": "running", "run": "running", "road_biking": "cycling",
            "mountain_biking": "cycling", "gravel_cycling": "cycling", "indoor_cycling": "cycling",
            "virtual_ride": "cycling", "lap_swimming": "swimming", "open_water_swimming": "swimming",
            "pool_swimming": "swimming", "strength_training": "strength", "multisport": "multisport",
            "triathlon": "multisport", "duathlon": "multisport", "brick": "multisport",
        }
        for type_key, normalized in cases.items():
            with self.subTest(type_key=type_key):
                self.assertEqual(sport({"activityType": {"typeKey": type_key}, "activityName": "Carrera Málaga"}), normalized)
        self.assertEqual(sport({"activityType": {"typeKey": "race_event"}, "activityName": "Carrera Málaga"}), "other")

    def test_garmin_strava_copy_with_pauses_counts_once(self) -> None:
        garmin = activity("edge", "garmin", "2026-10-05T17:46:29+02:00", 40.66, 6156)
        strava = activity("strava:edge", "strava", "2026-10-05T15:46:29Z", 40.66, 9808)
        garmin['sport'] = strava['sport'] = 'cycling'
        garmin['avg_hr'] = strava['avg_hr'] = 112
        merged = merge_activities([garmin], [], [strava])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['duration_s'], 6156)
        self.assertEqual(merged[0]['km'], 40.66)
        self.assertEqual({r['source'] for r in merged[0]['source_records']}, {'garmin', 'strava'})

    def test_duration_mismatch_requires_exact_recording_evidence(self) -> None:
        garmin = activity("edge", "garmin", "2026-10-05T17:46:29+02:00", 40.66, 6156)
        garmin['avg_hr'] = 112
        for changes in ({'started_at': '2026-10-05T17:48:29+02:00'},
                        {'km': 42}, {'km': 0}, {'km': None}, {'sport': 'other'},
                        {'avg_hr': None}, {'avg_hr': 140}):
            with self.subTest(changes=changes):
                strava = activity("strava:edge", "strava", garmin['started_at'], 40.66, 9808)
                strava['avg_hr'] = 112
                strava.update(changes)
                self.assertEqual(len(merge_activities([garmin], [], [strava])), 2)

    def test_garmin_normalization_adds_source_and_offset_aware_start(self) -> None:
        normalized = normalize_activities(
            [
                {
                    "activityId": "garmin-1",
                    "activityName": "Carrera Garmin",
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": "2026-09-24T07:25:00",
                    "distance": 8020,
                    "duration": 2518,
                }
            ]
        )

        self.assertEqual(normalized[0]["source"], "garmin")
        self.assertEqual(normalized[0]["started_at"], "2026-09-24T07:25:00+02:00")

    def test_garmin_normalization_writes_utc_and_local_activity_dates(self):
        normalized = normalize_activities([{
            'activityId': 'travel-ride', 'activityType': {'typeKey': 'road_biking'},
            'startTimeGMT': '2026-10-13T22:55:00Z',
            'startTimeLocal': '2026-10-14T00:55:00', 'distance': 12000,
            'duration': 3600,
        }])[0]
        self.assertEqual(normalized['started_at_utc'], '2026-10-13T22:55:00+00:00')
        self.assertEqual(normalized['local_date'], '2026-10-14')
        self.assertEqual(normalized['time_context'], 'Europe/Madrid')

    def test_garmin_gmt_only_derives_local_date_from_absolute_instant(self):
        normalized = normalize_activities([{
            'activityId': 'near-midnight', 'activityType': {'typeKey': 'road_biking'},
            'startTimeGMT': '2026-10-13T22:55:00Z', 'distance': 12000, 'duration': 3600,
        }])[0]
        self.assertEqual(normalized['date'], '2026-10-14')
        self.assertEqual(normalized['local_date'], '2026-10-14')
        self.assertEqual(normalized['started_at_utc'], '2026-10-13T22:55:00+00:00')

    def test_garmin_naive_gmt_is_not_promoted_to_utc(self):
        normalized = normalize_activities([{
            'activityId': 'naive-gmt', 'activityType': {'typeKey': 'road_biking'},
            'startTimeGMT': '2026-10-13T22:55:00', 'distance': 12000,
            'duration': 3600,
        }])[0]
        self.assertNotIn('started_at_utc', normalized)
        self.assertNotIn('local_date', normalized)
        self.assertEqual(normalized['date'], '2026-10-13')

    def test_next_full_sync_keeps_normalized_fields_for_entire_120_day_window(self):
        now = datetime(2026, 10, 14, 12, tzinfo=sync.MADRID_TZ)
        token = sync._SYNC_NOW.set(now)
        self.addCleanup(sync._SYNC_NOW.reset, token)
        raw = []
        for offset in range(32):
            day = (now.date() - timedelta(days=offset)).isoformat()
            raw.append({'activityId': f'ride-{offset}', 'activityType': {'typeKey': 'road_biking'},
                'startTimeGMT': f'{day}T06:00:00Z', 'startTimeLocal': f'{day}T08:00:00',
                'distance': 10000, 'duration': 3600})
        normalized = normalize_activities(raw)
        payload_activities = summarize_normalized(normalized)['activities']
        self.assertEqual(len(payload_activities), 32)
        self.assertTrue(all(row.get('started_at_utc') and row.get('local_date')
                            and row.get('time_context') for row in payload_activities))

    def test_matching_garmin_and_zepp_run_keeps_garmin_only(self) -> None:
        merged = merge_activities(
            [activity("garmin-1", "garmin", "2026-09-24T07:25:00+02:00", 8.02, 2518)],
            [activity("zepp:run:42", "zepp", "2026-09-24T07:27:00+02:00", 8.10, 2500)],
        )

        self.assertEqual([item["id"] for item in merged], ["garmin-1"])

    def test_dedup_merge_fills_missing_temporal_metadata_from_secondary_source(self):
        garmin = activity('garmin-id', 'garmin', '2026-09-24T07:25:00+02:00', 8.02, 2518)
        zepp = activity('zepp-id', 'zepp', '2026-09-24T07:25:00+02:00', 8.02, 2518)
        zepp.update(started_at_utc='2026-09-24T05:25:00+00:00', local_date='2026-09-24',
                    time_context='Europe/Madrid')
        merged = merge_activities([garmin], [zepp])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['started_at_utc'], '2026-09-24T05:25:00+00:00')
        self.assertEqual(merged[0]['local_date'], '2026-09-24')

    def test_eleven_minutes_apart_runs_are_independent(self) -> None:
        merged = merge_activities(
            [activity("garmin-1", "garmin", "2026-09-24T07:25:00+02:00", 8.02, 2518)],
            [activity("zepp:run:42", "zepp", "2026-09-24T07:36:00+02:00", 8.10, 2500)],
        )

        self.assertEqual([item["id"] for item in merged], ["garmin-1", "zepp:run:42"])

    def test_same_time_runs_with_distance_difference_above_ten_percent_are_independent(self) -> None:
        merged = merge_activities(
            [activity("garmin-1", "garmin", "2026-09-24T07:25:00+02:00", 8.02, 2518)],
            [activity("zepp:run:42", "zepp", "2026-09-24T07:27:00+02:00", 9.10, 2500)],
        )

        self.assertEqual([item["id"] for item in merged], ["garmin-1", "zepp:run:42"])

    def test_two_independent_zepp_ids_are_retained(self) -> None:
        merged = merge_activities(
            [],
            [
                activity("zepp:run:42", "zepp", "2026-09-24T07:25:00+02:00", 8.02, 2518),
                activity("zepp:run:43", "zepp", "2026-09-24T18:25:00+02:00", 5.00, 1600),
            ],
        )

        self.assertEqual([item["id"] for item in merged], ["zepp:run:42", "zepp:run:43"])

    def test_strava_copy_of_garmin_is_removed_but_cmf_only_activity_is_retained(self) -> None:
        merged = merge_activities(
            [activity("garmin-1", "garmin", "2026-08-24T07:25:00+02:00", 8.02, 2518)],
            [],
            [
                activity("strava:duplicate", "strava", "2026-08-24T07:27:00+02:00", 8.10, 2500),
                activity("strava:cmf", "strava", "2026-08-24T18:25:00+02:00", 5.00, 1600),
            ],
        )

        self.assertEqual([item["id"] for item in merged], ["garmin-1", "strava:cmf"])

    def test_zepp_run_enters_common_summary_when_garmin_is_absent(self) -> None:
        from garmin_sync.sync import TODAY
        summary = summarize_normalized(
            [activity("zepp:run:42", "zepp", f"{TODAY.isoformat()}T07:25:00+02:00", 8.02, 2518, avg_hr=151)],
            {"profile": {"max_hr": 190, "resting_hr": 50, "sex": "hombre"}},
        )

        self.assertEqual(summary["today"]["km"], 8.0)
        self.assertEqual(summary["activities"][0]["source"], "zepp")
        self.assertEqual(summary["running_load"]["latest"]["source"], "trimp_estimado")

    def test_zepp_run_without_hr_is_retained_without_running_load(self) -> None:
        summary = summarize_normalized(
            [activity("zepp:run:42", "zepp", "2026-09-24T07:25:00+02:00", 8.02, 2518)],
            {"profile": {"max_hr": 190, "resting_hr": 50, "sex": "hombre"}},
        )

        self.assertEqual(summary["activities"][0]["source"], "zepp")
        self.assertNotIn("running_load", summary["activities"][0])
        self.assertFalse(summary["running_load"]["available"])


if __name__ == "__main__":
    unittest.main()
