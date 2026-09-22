from __future__ import annotations

import unittest

from garmin_sync.wellness_models import (
    NormalizedSleep,
    NormalizedWellness,
    deduplicate_sleep_sessions,
)


class WellnessModelTests(unittest.TestCase):
    def test_sleep_belongs_to_local_date_on_which_it_ends(self) -> None:
        sleep = NormalizedSleep(
            start="2026-09-21T23:41:00+02:00",
            end="2026-09-22T07:09:00+02:00",
            total_minutes=448,
        )

        wellness = NormalizedWellness(sleep=sleep)

        self.assertEqual(wellness.wellness_date("Europe/Madrid"), "2026-09-22")

    def test_deduplicates_identical_cross_midnight_sleep_session(self) -> None:
        session = NormalizedSleep(
            source_id="night-1",
            start="2026-09-21T23:41:00+02:00",
            end="2026-09-22T07:09:00+02:00",
            total_minutes=448,
        )

        sessions = deduplicate_sleep_sessions([session, session])

        self.assertEqual(sessions, [session])

    def test_empty_vo2max_observations_are_valid_for_a_rest_day(self) -> None:
        wellness = NormalizedWellness(vo2max_observations=[])

        self.assertEqual(wellness.to_dict()["vo2max_observations"], [])


if __name__ == "__main__":
    unittest.main()
