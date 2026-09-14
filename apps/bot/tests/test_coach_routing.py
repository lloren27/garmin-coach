from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app import main
from app.coach import COACH_QUESTIONS, build_ai_brief


class CoachRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("load_sync", "load_profile", "load_wattwise", "load_strength_state"):
            stack.enter_context(patch.object(main, name, return_value={}))
        self.queue = stack.enter_context(patch.object(main, "create_ai_job", return_value={"id": "job"}))

    def test_coaching_commands_and_free_text_all_enter_queue(self) -> None:
        for text in [*COACH_QUESTIONS, "/fuerza", "/coach ¿Qué hago mañana?", "¿Qué hago mañana?"]:
            with self.subTest(text=text):
                self.queue.reset_mock()
                response = main.route_message(text, "user", "chat")
                self.queue.assert_called_once()
                self.assertEqual(self.queue.call_args.kwargs["chat_id"], "chat")
                self.assertIn("análisis", response)
                self.assertIn("40 y 70 segundos", response)

    def test_command_arguments_survive_and_bot_suffix_is_supported(self) -> None:
        main.route_message("/ajustar@MyBot dolor gemelo derecho", "user", "chat")
        self.assertIn("dolor gemelo derecho", self.queue.call_args.kwargs["text"])

    def test_strength_logging_stays_transactional(self) -> None:
        with patch.object(main, "handle_strength_command", return_value=("Guardado", {"sessions": []}, True)) as handle, patch.object(main, "save_strength_state") as save:
            self.assertEqual(main.route_message("/fuerza add sentadilla 60kg 8/8 rir2", "user", "chat"), "Guardado")
            self.assertEqual(handle.call_args.args[0], "add sentadilla 60kg 8/8 rir2")
            save.assert_called_once_with({"sessions": []})
            self.queue.assert_not_called()

    def test_profile_updates_stay_transactional(self) -> None:
        with patch.object(main, "save_profile", return_value={"profile": {"weight_kg": 72}}) as save:
            main.route_message("/perfil peso 72", "user", "chat")
            save.assert_called_once()
            self.queue.assert_not_called()

    def test_every_brief_includes_cross_sport_readings(self) -> None:
        for question in ("¿Qué hago mañana?", "¿Cómo fue la bici?", "Plan semanal", "¿Cómo mejoro?"):
            with self.subTest(question=question):
                brief = build_ai_brief(question, None)
                titles = [section["title"] for section in brief["sections"]]
                self.assertTrue({"salud", "carga", "running", "tendencia"}.issubset(titles))
                self.assertEqual(len(titles), len(set(titles)))
                self.assertIn("strength_load", brief)

    def test_latest_feedback_with_no_garmin_data_remains_usable(self) -> None:
        brief = build_ai_brief("feedback de mi última actividad", None, strength_state={"sessions": []})
        self.assertIn("ultima_actividad", [item["title"] for item in brief["sections"]])
        self.assertIn("strength_load_current", brief)

    def test_job_context_includes_only_applied_lab_tests(self) -> None:
        with patch.object(main, "require_sync_secret"), patch.object(main, "claim_next_ai_job", return_value={"id": "job", "text": "¿Qué hago?"}), patch.object(main, "load_checkins", return_value=[]), patch.object(main, "load_sync_history", return_value=[]) as history, patch.object(main, "load_lab_tests", return_value=[{"id": "a", "status": "applied", "extracted": {"max_hr": 180}, "source": {"file_id": "private"}}, {"id": "b", "status": "pending"}]):
            result = main.next_ai_job()
            history.assert_called_once_with(28)
            tests = result["context"]["lab_tests"]
            self.assertEqual([item["id"] for item in tests], ["a"])
            self.assertNotIn("source", tests[0])


if __name__ == "__main__":
    unittest.main()
