from pathlib import Path
import unittest

class GuardSmokeTests(unittest.TestCase):
    def test_authorized_write(self):
        root = Path(__file__).resolve().parent / "fixtures"
        self.assertEqual(
            (root / "guard-allowed.txt").read_text().strip(),
            "PRUEBA_AUTORIZADA",
        )
        self.assertFalse((root / "guard-forbidden.txt").exists())

if __name__ == "__main__":
    unittest.main()
