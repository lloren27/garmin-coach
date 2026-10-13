from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from garmin_sync.provider_state import state_record


class StateRecordTests(unittest.TestCase):
    """Tests for state_record() function in provider_state.py"""

    # Fixed UTC date: 2026-10-13 (today)
    TODAY = date(2026, 10, 13)
    NOW_DT = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

    # Real input format expected by state_record(): 
    # status="ok" with records_received > 0 should return state='available'
    VALID_OK_STATUS_WITH_RECORDS = {
        'status': 'ok',
        'records_received': 5,  # Positive integer indicating data available
        'last_success_at': '2026-10-13T11:00:00+00:00',  # Valid ISO timestamp within today
    }

    def test_status_ok_with_records_is_available(self) -> None:
        """Test that status='ok' with records_received > 0 returns state='available'.
        
        This uses the real input format expected by state_record(): 
        - status='ok' indicates successful sync with available data
        - records_received is an integer count of synced records (not None)
        - last_success_at is a valid ISO 8601 timestamp
        
        The function checks if activity evidence is recent enough (within reference date).
        """
        result = state_record(
            self.VALID_OK_STATUS_WITH_RECORDS, 
            scope='activities', 
            now=self.NOW_DT
        )

        # Verify core assertion: data is available when status=ok with records>0
        self.assertEqual(result['state'], 'available')
        
        # Additional fields should be correctly populated from input
        self.assertEqual(result['status'], 'ok')  # Status passed through unchanged
        self.assertEqual(result['scope'], 'activities')  # Scope matches input
        self.assertIsNone(result['reason'])  # No invalid reason (all alnum, <80 chars)
        
        # Date parsing: last_success_at=2026-10-13T11:00:00+00:00 should be parsed correctly
        expected_last_success = datetime(2026, 10, 13, 11, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(datetime.fromisoformat(result["last_success_at"]), expected_last_success)
        
        # Period fields should be parsed from input or defaulted to collected_at/None
        self.assertIsNone(result['period_start'])  # Not in input, defaults to None
        self.assertIsNone(result['period_end'])    # Not in input, defaults to None
        
        # Records received count should match input
        self.assertEqual(result['records_received'], 5)
        
        # Error should be None since status is 'ok' (not in ERRORS set)
        self.assertIsNone(result['error'])


if __name__ == "__main__":
    unittest.main()
