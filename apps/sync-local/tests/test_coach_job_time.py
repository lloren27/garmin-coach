import unittest
from datetime import datetime, timezone

from garmin_sync.coach_job_time import job_created_at


class CoachJobTimeTests(unittest.TestCase):
    def test_job_time_is_the_trusted_enqueue_instant(self):
        value = '2026-10-03T21:50:00Z'

        self.assertEqual(job_created_at({'created_at': value}), datetime(2026, 10, 3, 21, 50, tzinfo=timezone.utc))

    def test_missing_malformed_or_naive_timestamp_fails_closed(self):
        for job in ({}, {'created_at': 'not-a-date'}, {'created_at': '2026-10-03T21:50:00'}):
            with self.subTest(job=job), self.assertRaises(ValueError):
                job_created_at(job)


if __name__ == '__main__':
    unittest.main()
