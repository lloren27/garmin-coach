from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from garmin_sync import requested_sync


class RequestedSyncTests(unittest.TestCase):
    def test_requested_zepp_sync_runs_full_local_sync_and_completes_request(self) -> None:
        request = {"status": "pending", "mode": "zepp_activities"}
        with (
            patch.object(requested_sync, "get_json", side_effect=[{"pending": True, "request": request}, {"sync": {}}]),
            patch.object(requested_sync, "run_full_sync") as run_full_sync,
            patch.object(requested_sync, "post_json") as post_json,
            patch("builtins.print") as print_output,
        ):
            self.assertEqual(requested_sync.main(), 0)

        run_full_sync.assert_called_once_with()
        post_json.assert_called_once_with("/sync/request/complete", {"status": "completed"})
        self.assertIn("zepp_activities", print_output.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
