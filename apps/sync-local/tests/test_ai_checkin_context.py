from __future__ import annotations

import unittest

from garmin_sync.ai_worker import _compact_injury_checkins, compact_context, prepare_text_for_tts


class AiCheckinContextTests(unittest.TestCase):
    def test_compact_context_keeps_only_effective_v2_wellness(self) -> None:
        context = {
            "sync": {
                "payload": {
                    "wellness": {
                        "schema_version": 2,
                        "timezone": "Europe/Madrid",
                        "effective": {"steps": {"value": 8231, "source": "zepp"}},
                        "garmin": {"2026-09-22": {"raw_detail": "do-not-send"}},
                        "zepp": {"2026-09-22": {"minute_hr": [1, 2, 3]}},
                        "history": {"2026-09-22": {"effective": {}}},
                    }
                }
            }
        }

        result = compact_context(context)

        wellness = result["extra_context"]["wellness"]
        self.assertEqual(wellness["effective"]["steps"]["source"], "zepp")
        self.assertNotIn("garmin", wellness)
        self.assertNotIn("zepp", wellness)
        self.assertNotIn("history", wellness)

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
        self.assertIn("umbral ritmo cuatro minutos y cincuenta segundos por kilómetro", result)

    def test_prepare_text_for_tts_expands_strength_terms(self) -> None:
        result = prepare_text_for_tts("Full body con hip thrust, split squat y RIR 2.")

        self.assertIn("cuerpo completo", result)
        self.assertIn("hip trust", result)
        self.assertIn("split escuat", result)
        self.assertIn("repeticiones en reserva dos", result)


if __name__ == "__main__":
    unittest.main()
