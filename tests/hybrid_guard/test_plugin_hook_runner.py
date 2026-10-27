from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ActualOpenCodeHookTests(unittest.TestCase):
    def test_node_executes_actual_plugin_hook_integration_suite(self):
        result = subprocess.run(
            ["node", "--test", "tests/hybrid_guard/test_plugin_hook.mjs"],
            cwd=ROOT, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        counts = {}
        for label in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
            match = re.search(rf"^ℹ {label} (\d+)$", result.stdout, re.MULTILINE)
            self.assertIsNotNone(match, f"missing Node test summary count {label}: {result.stdout}")
            counts[label] = int(match.group(1))

        self.assertGreaterEqual(counts["tests"], 18)
        self.assertEqual(counts["fail"], 0, result.stdout)
        self.assertEqual(
            counts["tests"],
            counts["pass"] + counts["fail"] + counts["cancelled"] + counts["skipped"] + counts["todo"],
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
