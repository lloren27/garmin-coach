import unittest

from garmin_sync.coach_engine_contract import (
    ENGINE_REQUIREMENT_UNAVAILABLE,
    ENGINE_REQUIREMENT_UNSUPPORTED,
    required_engine_error,
)


class RequiredEngineContractTests(unittest.TestCase):
    def test_legacy_jobs_remain_compatible(self):
        self.assertIsNone(required_engine_error({}, v3_enabled=False))
        self.assertIsNone(required_engine_error({"required_engine": None}, v3_enabled=False))

    def test_required_v3_is_rejected_if_disabled_and_never_downgraded(self):
        self.assertEqual(
            required_engine_error({"required_engine": "v3"}, v3_enabled=False),
            ENGINE_REQUIREMENT_UNAVAILABLE,
        )
        self.assertIsNone(required_engine_error({"required_engine": "v3"}, v3_enabled=True))

    def test_unknown_requirement_fails_closed(self):
        self.assertEqual(
            required_engine_error({"required_engine": "v9"}, v3_enabled=True),
            ENGINE_REQUIREMENT_UNSUPPORTED,
        )


if __name__ == "__main__":
    unittest.main()
