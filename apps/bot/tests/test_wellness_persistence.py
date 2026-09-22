from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main, store
from app.config import Settings


def wellness_payload(score: int = 78) -> dict:
    dates = ("2026-09-20", "2026-09-21", "2026-09-22")
    garmin = {day: {"steps": {"value": 5000, "source": "garmin"}} for day in dates}
    zepp = {
        day: {
            "sleep": {"total_minutes": 440, "score": score, "source": "zepp"},
            "steps": {"value": 8000, "source": "zepp"},
        }
        for day in dates
    }
    history = {
        day: {"effective": {"date": day, "sleep": {"total_minutes": 440, "score": score, "source": "zepp"}}}
        for day in dates
    }
    return {
        "wellness": {
            "schema_version": 2,
            "timezone": "Europe/Madrid",
            "garmin": garmin,
            "zepp": zepp,
            "history": history,
            "effective": history[dates[-1]]["effective"],
        }
    }


class WellnessPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.data_dir = Path(self.tempdir.name)
        self.patchers = [
            patch.object(store, "DATA_DIR", self.data_dir),
            patch.object(store, "SYNC_FILE", self.data_dir / "latest_sync.json"),
            patch.object(store, "SYNC_HISTORY_FILE", self.data_dir / "sync_history.jsonl"),
            patch.object(store, "WELLNESS_HISTORY_FILE", self.data_dir / "wellness_history.json"),
            patch.object(store, "DATABASE_URL", None),
            patch.object(main, "settings", Settings()),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_second_sync_updates_same_date_and_source_without_duplicate(self) -> None:
        store.upsert_wellness_days(wellness_payload(score=78))
        store.upsert_wellness_days(wellness_payload(score=82))

        rows = store.load_wellness_history(3)

        self.assertEqual(rows["2026-09-22"]["sources"]["zepp"]["sleep"]["score"], 82)
        self.assertEqual(rows["2026-09-22"]["effective"]["sleep"]["score"], 82)
        self.assertEqual(len(rows["2026-09-22"]["sources"]), 2)

    def test_postgres_schema_has_one_row_per_owner_date_source(self) -> None:
        self.assertIn("primary key (owner_id, wellness_date, source)", store.WELLNESS_DAILY_DDL.lower())

    def test_sync_endpoint_persists_three_wellness_dates(self) -> None:
        client = TestClient(main.app)

        response = client.post("/sync", json=wellness_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(store.load_wellness_history(3)), {"2026-09-20", "2026-09-21", "2026-09-22"})


if __name__ == "__main__":
    unittest.main()
