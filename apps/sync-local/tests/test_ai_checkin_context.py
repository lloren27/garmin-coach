from __future__ import annotations

import unittest

from garmin_sync.ai_worker import _compact_injury_checkins


class AiCheckinContextTests(unittest.TestCase):
    def test_only_pain_and_soreness_are_sent_to_ollama(self) -> None:
        result = _compact_injury_checkins(
            [
                {
                    "created_at": "2026-09-09T08:00:00+00:00",
                    "checkin": {"rpe": 9, "sleep": 2, "energy": 2},
                },
                {
                    "created_at": "2026-09-09T09:00:00+00:00",
                    "checkin": {
                        "rpe": 8,
                        "sleep": 3,
                        "pain": "gemelo derecho",
                        "soreness": "soleo",
                        "note": "aparece al correr",
                    },
                },
            ]
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pain"], "gemelo derecho")
        self.assertEqual(result[0]["soreness"], "soleo")
        self.assertNotIn("rpe", result[0])
        self.assertNotIn("sleep", result[0])
        self.assertNotIn("energy", result[0])


if __name__ == "__main__":
    unittest.main()
