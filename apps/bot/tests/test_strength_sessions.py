from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.coach import format_feedback, format_load, format_natural_coach
from app.strength import (
    handle_strength_command,
    parse_strength_entry,
    strength_context_for_date,
    summarize_strength_load,
)


SYNC = {
    "received_at": "2026-09-09T19:15:00+00:00",
    "payload": {
        "generated_at": "2026-09-09T21:15:00+02:00",
        "summary": {
            "activities": [
                {
                    "id": "run-1",
                    "date": "2026-09-09",
                    "sport": "running",
                    "km": 8,
                    "duration_s": 2700,
                    "pace": "5:37/km",
                    "running_load": 70,
                }
            ],
            "week": {
                "hours": 4,
                "km": 35,
                "by_sport": {
                    "running": {"sessions": 3, "km": 35},
                    "cycling": {"sessions": 0, "hours": 0},
                    "strength": {"sessions": 1, "hours": 0.7},
                },
            },
            "sports": {
                "running": {"sessions_7d": 3, "km_7d": 35, "hours_7d": 3.2},
                "cycling": {"sessions_7d": 0, "km_7d": 0, "hours_7d": 0},
                "strength": {"sessions_7d": 1, "hours_7d": 0.7},
            },
            "fatigue": {"level": "baja", "acute_chronic_ratio": 0.9},
            "next_workout": {"title": "Rodaje facil", "details": "45 min suave."},
        },
    },
}


class StrengthSessionTests(unittest.TestCase):
    def test_circuit_letter_previews_exercises_without_starting_session(self) -> None:
        response, state, changed = handle_strength_command("A", None, {}, "user-1")

        self.assertFalse(changed)
        self.assertIn("Circuito A", response)
        self.assertIn("sentadilla", response)
        self.assertEqual(state["active_sessions"], {})

    def test_explicit_start_command_starts_session(self) -> None:
        response, state, changed = handle_strength_command("iniciar A", None, {}, "user-1")

        self.assertTrue(changed)
        self.assertIn("Sesion de fuerza iniciada: circuito A", response)
        self.assertEqual(state["active_sessions"]["user-1"]["circuit"], "A")

    def test_parse_strength_entry_reads_weight_reps_and_rir(self) -> None:
        entry = parse_strength_entry("sentadilla 60kg 8/8 rir2", "A")

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["exercise_id"], "sentadilla")
        self.assertEqual(entry["weight_kg"], 60)
        self.assertEqual(entry["reps"], [8, 8])
        self.assertEqual(entry["sets"], 2)
        self.assertEqual(entry["rir"], 2)
        self.assertEqual(entry["volume_kg"], 960)

    def test_parse_strength_entry_accepts_single_set_shorthand(self) -> None:
        entry = parse_strength_entry("sentadilla 60kg 8 rir2", "A")

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["reps"], [8])
        self.assertEqual(entry["sets"], 1)
        self.assertEqual(entry["volume_kg"], 480)

    def test_strength_command_starts_logs_and_finishes_session(self) -> None:
        state = {}

        response, state, changed = handle_strength_command("iniciar A", None, state, "user-1")
        self.assertTrue(changed)
        self.assertIn("circuito A", response)

        response, state, changed = handle_strength_command("add sentadilla 60kg 8/8 rir2", None, state, "user-1")
        self.assertTrue(changed)
        self.assertIn("Guardado: - sentadilla", response)

        response, state, changed = handle_strength_command("fin", None, state, "user-1")
        self.assertTrue(changed)
        self.assertIn("Sesion de fuerza cerrada: circuito A", response)
        self.assertIn("2 series", response)
        self.assertIn("960 kg", response)

    def test_strength_state_persists_between_messages(self) -> None:
        from app import store

        original_data_dir = store.DATA_DIR
        with tempfile.TemporaryDirectory() as tmp:
            store.DATA_DIR = Path(tmp)
            try:
                response, state, changed = handle_strength_command(
                    "iniciar A", None, store.load_strength_state(), "chat-1"
                )
                self.assertTrue(changed)
                self.assertIn("Sesion de fuerza iniciada", response)
                store.save_strength_state(state)

                response, state, changed = handle_strength_command(
                    "add sentadilla 60kg 8/8 rir2",
                    None,
                    store.load_strength_state(),
                    "chat-1",
                )
                self.assertTrue(changed)
                self.assertIn("Guardado: - sentadilla", response)
                store.save_strength_state(state)

                response, state, changed = handle_strength_command("fin", None, store.load_strength_state(), "chat-1")
                self.assertTrue(changed)
                self.assertIn("Sesion de fuerza cerrada", response)
                store.save_strength_state(state)

                response, _, changed = handle_strength_command("historial", None, store.load_strength_state(), "chat-1")
                self.assertFalse(changed)
                self.assertIn("circuito A", response)
            finally:
                store.DATA_DIR = original_data_dir

    def test_fin_discards_empty_session_instead_of_saving_it(self) -> None:
        _, state, _ = handle_strength_command("iniciar A", None, {}, "user-1")

        response, state, changed = handle_strength_command("fin", None, state, "user-1")

        self.assertTrue(changed)
        self.assertIn("vacia", response)
        self.assertIn("no se ha guardado", response)
        self.assertEqual(state["active_sessions"], {})
        self.assertEqual(state["sessions"], [])

    def test_cancel_discards_active_session_even_when_it_has_entries(self) -> None:
        _, state, _ = handle_strength_command("iniciar A", None, {}, "user-1")
        _, state, _ = handle_strength_command("add sentadilla 60kg 8/8 rir2", None, state, "user-1")

        response, state, changed = handle_strength_command("cancelar", None, state, "user-1")

        self.assertTrue(changed)
        self.assertIn("cancelada", response)
        self.assertIn("no se ha guardado", response)
        self.assertEqual(state["active_sessions"], {})
        self.assertEqual(state["sessions"], [])

    def test_history_lists_short_ids_and_delete_removes_selected_owned_session(self) -> None:
        state = {
            "active_sessions": {},
            "sessions": [
                {
                    "id": "7c9d15a4-8fb1-4f47-8a71-2e0db978c647",
                    "owner_id": "user-1",
                    "circuit": "A",
                    "status": "completed",
                    "completed_at": "2026-09-16T08:00:00+00:00",
                    "entries": [],
                },
                {
                    "id": "a82f04c1-1111-4222-8333-123456789abc",
                    "owner_id": "user-1",
                    "circuit": "B",
                    "status": "completed",
                    "completed_at": "2026-09-15T08:00:00+00:00",
                    "entries": [],
                },
                {
                    "id": "7c9d15a4-aaaa-4bbb-8ccc-987654321def",
                    "owner_id": "user-2",
                    "circuit": "A",
                    "status": "completed",
                    "completed_at": "2026-09-14T08:00:00+00:00",
                    "entries": [],
                },
            ],
        }

        response, _, changed = handle_strength_command("historial", None, state, "user-1")
        self.assertFalse(changed)
        self.assertIn("7c9d15a4", response)
        self.assertIn("a82f04c1", response)
        self.assertNotIn("987654321def", response)

        response, state, changed = handle_strength_command("borrar 7c9d15a4", None, state, "user-1")

        self.assertTrue(changed)
        self.assertIn("7c9d15a4", response)
        self.assertEqual(
            [session["id"] for session in state["sessions"]],
            ["a82f04c1-1111-4222-8333-123456789abc", "7c9d15a4-aaaa-4bbb-8ccc-987654321def"],
        )

    def test_delete_rejects_ambiguous_session_prefix(self) -> None:
        state = {
            "active_sessions": {},
            "sessions": [
                {"id": "abcd1234-one", "owner_id": "user-1", "circuit": "A", "entries": []},
                {"id": "abcd1234-two", "owner_id": "user-1", "circuit": "B", "entries": []},
            ],
        }

        response, state, changed = handle_strength_command("borrar abcd", None, state, "user-1")

        self.assertFalse(changed)
        self.assertIn("varias sesiones", response)
        self.assertEqual(len(state["sessions"]), 2)

    def test_delete_ultima_removes_latest_owned_session(self) -> None:
        state = {
            "active_sessions": {},
            "sessions": [
                {"id": "first-session", "owner_id": "user-1", "circuit": "A", "entries": []},
                {"id": "other-session", "owner_id": "user-2", "circuit": "A", "entries": []},
                {"id": "last-session", "owner_id": "user-1", "circuit": "B", "entries": []},
            ],
        }

        response, state, changed = handle_strength_command("borrar ultima", None, state, "user-1")

        self.assertTrue(changed)
        self.assertIn("last-ses", response)
        self.assertEqual(
            [session["id"] for session in state["sessions"]],
            ["first-session", "other-session"],
        )

    def test_strength_load_summary_scores_muscular_work(self) -> None:
        state = _strength_state_with_leg_work()

        summary = summarize_strength_load(state, "user-1", date(2026, 9, 9))

        self.assertEqual(summary["sessions_7d"], 1)
        self.assertEqual(summary["sets_7d"], 12)
        self.assertEqual(summary["lower_sets_7d"], 8)
        self.assertGreater(summary["load_score_7d"], 16)
        self.assertEqual(summary["level"], "alta")

    def test_feedback_uses_manual_strength_context(self) -> None:
        state = _strength_state_with_leg_work()
        context = strength_context_for_date(state, "user-1", "2026-09-09")
        load = summarize_strength_load(state, "user-1", date(2026, 9, 9))

        answer = format_feedback(SYNC, strength_context=context, strength_load=load)

        self.assertIn("Fuerza registrada: 1 sesion", answer)
        self.assertIn("running y fuerza de pierna concentraron carga muscular", answer)
        self.assertIn("Impacto semanal: la fuerza registrada anade carga muscular", answer)

    def test_load_command_reports_manual_strength_load(self) -> None:
        load = summarize_strength_load(_strength_state_with_leg_work(), "user-1", date(2026, 9, 9))

        answer = format_load(SYNC, strength_load=load)

        self.assertIn("Fuerza registrada 7d: 1 sesiones, 12 series", answer)
        self.assertIn("Lectura fuerza: alta", answer)

    def test_natural_feedback_question_uses_all_current_day_context(self) -> None:
        answer = format_natural_coach(
            "que feedback me das del entreno de hoy",
            SYNC,
            strength_state=_strength_state_with_leg_work(),
            strength_owner_id="user-1",
        )

        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIn("Sobre la actividad solicitada", answer)
        self.assertIn("running 8 km", answer)
        self.assertIn("Fuerza registrada: 1 sesion", answer)
        self.assertNotIn("Para manana", answer)


def _strength_state_with_leg_work() -> dict:
    entries = [
        parse_strength_entry("sentadilla 60kg 8/8 rir1", "A"),
        parse_strength_entry("peso muerto rumano 70kg 8/8 rir1", "A"),
        parse_strength_entry("zancada 30kg 10/10 rir2", "B"),
        parse_strength_entry("hip thrust 80kg 8/8 rir2", "B"),
        parse_strength_entry("remo 45kg 8/8 rir2", "A"),
        parse_strength_entry("press 35kg 8/8 rir2", "A"),
    ]
    return {
        "active_sessions": {},
        "sessions": [
            {
                "owner_id": "user-1",
                "circuit": "A",
                "status": "completed",
                "completed_at": "2026-09-09T20:00:00+00:00",
                "entries": [entry for entry in entries if entry],
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
