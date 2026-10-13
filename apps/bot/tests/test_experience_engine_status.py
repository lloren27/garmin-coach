import unittest
from datetime import datetime, timezone

from app.experience import format_operational_status
from app.queue_status import empty_snapshot


class EngineStatusPresentationTests(unittest.TestCase):
    now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)

    def test_v3_source_is_visible_without_exposing_job_content(self):
        queue = empty_snapshot(True)
        queue["last_completed_output_source"] = "deterministic"
        result = format_operational_status(None, None, queue, now=self.now)
        self.assertIn("Origen de última respuesta: V3 determinista", result)
        self.assertNotIn("question", result)
        self.assertNotIn("answer", result)

    def test_unknown_source_is_rendered_as_unavailable(self):
        queue = empty_snapshot(True)
        queue["last_completed_output_source"] = "PRIVATE SOURCE"
        result = format_operational_status(None, None, queue, now=self.now)
        self.assertIn("Origen de última respuesta: no disponible", result)
        self.assertNotIn("PRIVATE SOURCE", result)


if __name__ == "__main__":
    unittest.main()
