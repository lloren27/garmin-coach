from __future__ import annotations

import unittest

from garmin_sync.wellness_resolver import is_valid_metric, resolve_wellness


GARMIN_COMPLETE_SLEEP = {
    "sleep": {
        "start": "2026-09-21T23:30:00+02:00",
        "end": "2026-09-22T07:00:00+02:00",
        "total_minutes": 450,
        "deep_minutes": 80,
        "light_minutes": 250,
        "rem_minutes": 95,
        "awake_minutes": 25,
        "score": 78,
    }
}
ZEPP_COMPLETE_SLEEP = {
    "sleep": {
        "start": "2026-09-21T23:41:00+02:00",
        "end": "2026-09-22T07:09:00+02:00",
        "total_minutes": 448,
        "deep_minutes": 82,
        "light_minutes": 244,
        "rem_minutes": 96,
        "awake_minutes": 26,
        "score": 84,
    }
}


class WellnessResolverTests(unittest.TestCase):
    def test_invalid_zepp_resting_hr_falls_back_to_valid_garmin(self) -> None:
        resolved = resolve_wellness(
            garmin={"resting_hr": {"value": 48, "unit": "bpm"}},
            zepp={"resting_hr": {"value": 0, "unit": "bpm"}},
            wellness_date="2026-09-22",
        )

        self.assertEqual(resolved["resting_hr"], {"value": 48, "unit": "bpm", "source": "garmin"})

    def test_zero_zepp_steps_are_valid(self) -> None:
        resolved = resolve_wellness({}, {"steps": {"value": 0, "unit": "steps"}}, "2026-09-22")

        self.assertEqual(resolved["steps"], {"value": 0, "unit": "steps", "source": "zepp"})

    def test_sleep_is_selected_as_one_complete_provider_block(self) -> None:
        resolved = resolve_wellness(GARMIN_COMPLETE_SLEEP, ZEPP_COMPLETE_SLEEP, "2026-09-22")

        self.assertEqual(resolved["sleep"]["source"], "zepp")
        self.assertEqual(resolved["sleep"]["deep_minutes"], 82)
        self.assertNotIn("garmin_deep_minutes", resolved["sleep"])

    def test_zepp_stress_does_not_fall_back_to_garmin(self) -> None:
        resolved = resolve_wellness({"stress": {"avg": 22}}, {}, "2026-09-22")

        self.assertNotIn("stress", resolved)

    def test_partial_zepp_sleep_uses_complete_garmin_sleep(self) -> None:
        resolved = resolve_wellness(GARMIN_COMPLETE_SLEEP, {"sleep": {"total_minutes": 420}}, "2026-09-22")

        self.assertEqual(resolved["sleep"]["source"], "garmin")

    def test_provider_specific_training_load_never_uses_garmin_as_zepp(self) -> None:
        resolved = resolve_wellness({"training_load": {"atl": 20, "ctl": 30, "tsb": 10}}, {}, "2026-09-22")

        self.assertNotIn("atl", resolved)
        self.assertNotIn("ctl", resolved)
        self.assertNotIn("tsb", resolved)

    def test_validators_reject_zero_resting_hr_but_allow_zero_steps(self) -> None:
        self.assertFalse(is_valid_metric("resting_hr", {"value": 0}))
        self.assertTrue(is_valid_metric("steps", {"value": 0}))


if __name__ == "__main__":
    unittest.main()
