from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, store
from app.config import Settings


class SyncRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        data_dir = Path(self.tempdir.name)
        self.patchers = [
            patch.object(store, "DATA_DIR", data_dir),
            patch.object(store, "SYNC_REQUEST_FILE", data_dir / "sync_request.json"),
            patch.object(store, "DATABASE_URL", None),
            patch.object(main, "settings", Settings()),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)

    def test_api_accepts_full_and_zepp_activity_modes(self) -> None:
        full = self.client.post("/sync/request", json={"mode": "full"})
        zepp = self.client.post("/sync/request", json={"mode": "zepp_activities"})

        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.json()["request"]["mode"], "full")
        self.assertEqual(zepp.status_code, 200)
        self.assertEqual(zepp.json()["request"]["mode"], "zepp_activities")
        self.assertEqual(store.load_sync_request()["mode"], "zepp_activities")

    def test_api_rejects_unknown_mode(self) -> None:
        for mode in ("partial", ["zepp_activities"]):
            with self.subTest(mode=mode):
                response = self.client.post("/sync/request", json={"mode": mode})
                self.assertEqual(response.status_code, 400)

    def test_completion_preserves_zepp_activity_mode_for_success_and_failure(self) -> None:
        self.client.post("/sync/request", json={"mode": "zepp_activities"})

        completed = self.client.post("/sync/request/complete", json={"status": "completed"})
        self.assertEqual(completed.json()["request"]["mode"], "zepp_activities")

        self.client.post("/sync/request", json={"mode": "zepp_activities"})
        failed = self.client.post("/sync/request/complete", json={"status": "failed", "error": "offline"})
        self.assertEqual(failed.json()["request"]["mode"], "zepp_activities")
        self.assertEqual(failed.json()["request"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
