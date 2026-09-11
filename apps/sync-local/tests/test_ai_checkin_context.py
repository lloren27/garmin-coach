from __future__ import annotations

import unittest

from garmin_sync.ai_worker import _compact_injury_checkins, prepare_text_for_tts


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

    def test_prepare_text_for_tts_expands_training_terms(self) -> None:
        result = prepare_text_for_tts(
            "Training load 7d alta: FTP 235 W, HRV estable, TSS 80, threshold pace 4:50/km."
        )

        self.assertIn("carga de entrenamiento siete dias", result)
        self.assertIn("efe te pe doscientos treinta y cinco vatios", result)
        self.assertIn("variabilidad de pulso estable", result)
        self.assertIn("te ese ese ochenta", result)
        self.assertIn("umbral ritmo cuatro cincuenta por kilometro", result)

    def test_prepare_text_for_tts_expands_strength_terms(self) -> None:
        result = prepare_text_for_tts("Full body con hip thrust, split squat y RIR 2.")

        self.assertIn("cuerpo completo", result)
        self.assertIn("hip trust", result)
        self.assertIn("split escuat", result)
        self.assertIn("repeticiones en reserva dos", result)


if __name__ == "__main__":
    unittest.main()
