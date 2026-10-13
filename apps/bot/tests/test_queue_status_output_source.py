import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.queue_status import read_snapshot


class QueueOutputSourceTests(unittest.TestCase):
    def test_last_source_is_selected_from_latest_completed_job_for_chat(self):
        rows = [
            {"chat_id": "allowed-chat", "status": "completed", "completed_at": "2026-10-12T20:00:00Z", "output_source": "ollama", "text": "PRIVATE"},
            {"chat_id": "allowed-chat", "status": "completed", "completed_at": "2026-10-12T21:00:00Z", "output_source": "deterministic"},
            {"chat_id": "other-chat", "status": "completed", "completed_at": "2026-10-12T22:00:00Z", "output_source": "ollama"},
        ]
        now = datetime(2026, 10, 12, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            path.write_text(json.dumps(rows), encoding="utf-8")
            snapshot = read_snapshot("allowed-chat", now=now, database_url=None, path=path)
        self.assertEqual(snapshot["last_completed_output_source"], "deterministic")
        self.assertNotIn("PRIVATE", str(snapshot))

    def test_missing_and_unknown_sources_remain_non_authoritative(self):
        now = datetime(2026, 10, 12, 23, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            path.write_text(json.dumps([{
                "chat_id": "chat", "status": "completed",
                "completed_at": "2026-10-12T22:00:00Z", "output_source": "unrecognized",
            }]), encoding="utf-8")
            snapshot = read_snapshot("chat", now=now, database_url=None, path=path)
        self.assertEqual(snapshot["last_completed_output_source"], "unrecognized")

    def test_postgres_source_is_a_bounded_same_chat_latest_lookup(self):
        statements = []
        aggregate_row = (0, 0, 0, 0, 0) + (None, 0) * 4 + ("deterministic",)

        class Cursor:
            def fetchone(self):
                return aggregate_row

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, statement, _params=None):
                statements.append(statement)
                return Cursor()

        fake_psycopg = types.SimpleNamespace(
            OperationalError=OSError,
            errors=types.SimpleNamespace(UndefinedTable=RuntimeError, InsufficientPrivilege=PermissionError),
            connect=lambda _url: Connection(),
        )
        now = datetime(2026, 10, 12, 23, tzinfo=timezone.utc)
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            snapshot = read_snapshot("allowed-chat", now=now, database_url="postgresql://example", path=Path("unused"))
        query = statements[-1]
        self.assertIn("ORDER BY latest.completed_at DESC NULLS LAST LIMIT 1", query)
        self.assertNotIn("array_agg", query.lower())
        self.assertIn("WHERE document->>'chat_id'=%s", query)
        self.assertEqual(snapshot["last_completed_output_source"], "deterministic")


if __name__ == "__main__":
    unittest.main()
