from __future__ import annotations

import unittest

from garmin_sync.activity_merge import merge_activities
from garmin_sync.sync import normalize_activities, summarize_normalized


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

    def test_matching_garmin_and_zepp_run_keeps_garmin_only(self) -> None:
        merged = merge_activities(
            [activity("garmin-1", "garmin", "2026-09-24T07:25:00+02:00", 8.02, 2518)],
            [activity("zepp:run:42", "zepp", "2026-09-24T07:27:00+02:00", 8.10, 2500)],
        )

        self.assertEqual([item["id"] for item in merged], ["garmin-1"])

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

    def test_zepp_run_enters_common_summary_when_garmin_is_absent(self) -> None:
        summary = summarize_normalized(
            [activity("zepp:run:42", "zepp", "2026-09-24T07:25:00+02:00", 8.02, 2518, avg_hr=151)],
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
