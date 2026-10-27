from __future__ import annotations

import unittest
import asyncio
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app import main
from app.coach import (
    build_ai_brief,
    format_ai_queued,
    format_voice_queued,
    format_week_plan,
)


class _TelegramUpdate:
    def __init__(self, message):
        self.message = message

    async def json(self):
        return {"message": self.message}


class CoachRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in ("load_sync", "load_profile", "load_wattwise", "load_strength_state"):
            stack.enter_context(patch.object(main, name, return_value={}))
        self.queue = stack.enter_context(patch.object(main, "create_ai_job", return_value={"id": "job"}))

    def test_free_text_and_coach_questions_enter_the_queue(self) -> None:
        for text in ("/coach ¿Qué hago mañana?", "¿Qué hago mañana?"):
            with self.subTest(text=text):
                self.queue.reset_mock()
                response = main.route_message(text, "user", "chat")
                self.queue.assert_called_once()
                self.assertEqual(self.queue.call_args.kwargs["chat_id"], "chat")
                self.assertEqual(
                    response,
                    "Consulta recibida; te respondo en cuanto esté lista. Puedes consultar /estado",
                )

    def test_text_acknowledgement_has_no_timing_promise(self):
        self.assertEqual(
            format_ai_queued({}),
            "Consulta recibida; te respondo en cuanto esté lista. Puedes consultar /estado",
        )
        self.assertNotIn("segundos", format_ai_queued({}))
        self.assertNotIn("escribiendo", format_ai_queued({}))

    def test_voice_acknowledgement_keeps_audio_duration_and_queue_context(self):
        response = format_voice_queued({"audio_duration": 12})
        self.assertIn("Audio recibido (12 s)", response)
        self.assertIn("transcripción y análisis", response)
        self.assertIn("/estado", response)
        self.assertNotIn("40 y 70 segundos", response)

    def test_webhook_sends_one_ack_after_enqueue_for_text_voice_and_audio(self):
        for message in (
            {"text": "¿Qué hago mañana?"},
            {"voice": {"file_id": "voice-file", "duration": 12}},
            {"audio": {"file_id": "audio-file", "duration": 12}},
        ):
            with self.subTest(message=message):
                events = []

                def create_job(**kwargs):
                    events.append(("create", kwargs))
                    return {"id": "job", "audio_duration": kwargs.get("audio_duration")}

                async def send_message(chat_id, text):
                    events.append(("send", chat_id, text))

                update = _TelegramUpdate(
                    {
                        **message,
                        "chat": {"id": 99},
                        "from": {"id": 42},
                    }
                )
                with patch.object(main, "create_ai_job", side_effect=create_job), patch.object(
                    main, "send_telegram_message", new_callable=AsyncMock,
                    side_effect=send_message,
                ):
                    asyncio.run(main.telegram_webhook(update))

                self.assertEqual([event[0] for event in events], ["create", "send"])
                self.assertEqual(events[1][1], 99)
                self.assertIn("/estado", events[1][2])
                self.assertEqual(events[1][2].count("Consulta recibida"), 1)

    def test_lab_test_document_keeps_its_specific_single_ack(self):
        events = []

        def create_job(**kwargs):
            events.append(("create", kwargs))
            return {"id": "job", "document_name": "test.pdf"}

        async def send_message(chat_id, text):
            events.append(("send", chat_id, text))

        update = _TelegramUpdate({
            "document": {"file_id": "pdf-file", "file_name": "test.pdf", "mime_type": "application/pdf"},
            "chat": {"id": 99},
            "from": {"id": 42},
        })
        with patch.object(main, "create_ai_job", side_effect=create_job), patch.object(
            main, "send_telegram_message", new_callable=AsyncMock,
            side_effect=send_message,
        ):
            asyncio.run(main.telegram_webhook(update))

        self.assertEqual([event[0] for event in events], ["create", "send"])
        self.assertEqual(events[0][1]["source_kind"], "lab_test")
        self.assertIn("Prueba de esfuerzo recibida", events[1][2])
        self.assertNotIn("Consulta recibida", events[1][2])

    def test_help_reading_commands_respond_without_waiting_for_the_local_coach(self) -> None:
        """A command advertised by /help must not collapse into a generic AI reply."""
        sync = {"payload": {"summary": {}, "wellness": {}}}
        direct_commands = (
            "/hoy", "/semana", "/ultima", "/proximo", "/fatiga", "/salud",
            "/carga", "/running", "/correr", "/carga_running", "/tendencia",
            "/feedback", "/bici", "/potencia", "/wattwise", "/malaga",
            "/fuerza",
        )
        with patch.object(main, "load_sync", return_value=sync), patch.object(main, "load_checkins", return_value=[]), patch.object(main, "load_sync_history", return_value=[]):
            for command in direct_commands:
                with self.subTest(command=command):
                    self.queue.reset_mock()

                    response = main.route_message(command, "user", "chat")

                    self.assertNotIn("Consulta recibida", response)
                    self.queue.assert_not_called()

    def test_week_plan_commands_persist_and_return_the_saved_plan(self) -> None:
        plan = {
            "start_date": "2026-09-14",
            "end_date": "2026-09-20",
            "sessions": [],
        }
        with (
            patch.object(main, "load_sync", return_value={"payload": {}}),
            patch.object(main, "load_checkins", return_value=[]),
            patch.object(main, "build_week_plan", return_value=plan) as build,
            patch.object(main, "save_training_plan") as save,
        ):
            for command in ("/plan_semana nuevo", "/plan nuevo"):
                with self.subTest(command=command):
                    self.queue.reset_mock()
                    build.reset_mock()
                    save.reset_mock()

                    response = main.route_message(command, "user", "chat")

                    build.assert_called_once_with(
                        sync={"payload": {}},
                        profile={},
                        checkins=[],
                        owner_id="chat",
                    )
                    save.assert_called_once_with(plan, "chat")
                    self.queue.assert_not_called()
                    self.assertIn("Plan 7 dias", response)

    def test_plan_read_is_not_a_creation_even_without_sync(self):
        plan = {'id':'stable', 'revision':3, 'start_date':'2026-10-04', 'end_date':'2026-10-10', 'sessions':[]}
        with patch.object(main, 'load_active_training_plan', return_value=plan) as load, \
             patch.object(main, 'build_week_plan') as build, patch.object(main, 'save_training_plan') as save, \
             patch.object(main, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 10, 12, tzinfo=ZoneInfo('Europe/Madrid'))
            for command in ('/plan','/plan_semana','/plan@bot'):
                self.assertIn('Plan 7 dias', main.route_message(command,'user','chat'))
            load.assert_called_with('chat')
            build.assert_not_called()
            save.assert_not_called()
        with patch.object(main, 'load_active_training_plan', return_value=None):
            self.assertIn('/plan nuevo', main.route_message('/plan','user','chat'))

    def test_plan_read_marks_expired_plan_without_creating_another(self):
        plan = {'id': 'old', 'start_date': '2026-10-03', 'end_date': '2026-10-09', 'sessions': []}
        with patch.object(main, 'load_active_training_plan', return_value=plan), \
             patch.object(main, 'build_week_plan') as build, \
             patch.object(main, 'save_training_plan') as save, \
             patch.object(main, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 27, 21, tzinfo=ZoneInfo('Europe/Madrid'))
            answer = main.route_message('/plan', 'user', 'chat')

        self.assertIn('terminó el 09/10/2026', answer)
        self.assertIn('No hay un plan vigente', answer)
        self.assertIn('/plan nuevo', answer)
        self.assertNotIn('el plan es la referencia vigente', answer)
        build.assert_not_called()
        save.assert_not_called()

    def test_command_arguments_survive_and_bot_suffix_is_supported(self) -> None:
        main.route_message("/coach@MyBot dolor gemelo derecho", "user", "chat")
        self.assertIn("dolor gemelo derecho", self.queue.call_args.kwargs["text"])

    def test_sync_zepp_command_persists_activity_mode_and_rejects_extra_arguments(self) -> None:
        document = {"requested_at": "2026-09-24T07:00:00+00:00", "mode": "zepp_activities"}
        with patch.object(main, "save_sync_request", return_value=document) as save:
            response = main.route_message("/sync zepp", "user", "chat")

        save.assert_called_once_with("user", mode="zepp_activities")
        self.assertIn("actividades Zepp", response)

        with patch.object(main, "save_sync_request") as save:
            response = main.route_message("/sync zepp ahora", "user", "chat")

        save.assert_not_called()
        self.assertEqual(response, "Uso: /sync, /sync zepp o /sync cmf")

    def test_sync_cmf_command_persists_strava_activity_mode(self) -> None:
        document = {"requested_at": "2026-09-29T07:00:00+00:00", "mode": "strava_activities"}
        with patch.object(main, "save_sync_request", return_value=document) as save:
            response = main.route_message("/sync cmf", "user", "chat")

        save.assert_called_once_with("user", mode="strava_activities")
        self.assertIn("actividades CMF via Strava", response)

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
        self.enterContext(patch.object(main, 'prepare_proposal_context', return_value={
            'training_plan': None, 'change_proposal_allowed_now': False}))
        with patch.object(main, "require_sync_secret"), patch.object(main, "claim_next_ai_job", return_value={"id": "job", "text": "¿Qué hago?"}), patch.object(main, "load_checkins", return_value=[]), patch.object(main, "load_sync_history", return_value=[]) as history, patch.object(main, "load_lab_tests", return_value=[{"id": "a", "status": "applied", "extracted": {"max_hr": 180}, "source": {"file_id": "private"}}, {"id": "b", "status": "pending"}]):
            result = main.next_ai_job()
            history.assert_called_once_with(28)
            tests = result["context"]["lab_tests"]
            self.assertEqual([item["id"] for item in tests], ["a"])
            self.assertNotIn("source", tests[0])

    def test_format_week_plan_uses_persisted_training_plan(self) -> None:
        training_plan = {
            "id": "plan-1",
            "owner_id": "123",
            "status": "active",
            "start_date": "2026-09-15",
            "end_date": "2026-09-21",
            "objective": "Maraton objetivo 3:40",
            "mode": "normal",
            "sessions": [
                {
                    "date": "2026-09-15",
                    "sequence": 0,
                    "sport": "running",
                    "session_type": "quality",
                    "title": "Calidad a ritmo maratón",
                    "description": "3 x 2 km a ritmo maratón.",
                    "intensity": "marathon_pace",
                    "target_pace": "5:13/km",
                    "optional": False,
                    "status": "planned",
                },
                {
                    "date": "2026-09-16",
                    "sequence": 0,
                    "sport": "running",
                    "session_type": "easy",
                    "title": "Rodaje fácil",
                    "description": "Running fácil.",
                    "duration_min": 40,
                    "duration_max": 50,
                    "intensity": "easy",
                    "optional": False,
                    "status": "planned",
                },
                {
                    "date": "2026-09-16",
                    "sequence": 1,
                    "sport": "strength",
                    "session_type": "full_body_a",
                    "title": "Fuerza full body A",
                    "description": "Sesión de fuerza full body A.",
                    "duration_min": 35,
                    "duration_max": 40,
                    "intensity": "moderate",
                    "optional": False,
                    "status": "planned",
                },
            ],
        }

        text = format_week_plan(None, training_plan=training_plan)

        assert "15/09/2026" in text
        assert "21/09/2026" in text
        assert "Calidad a ritmo maratón" in text
        assert "Rodaje fácil" in text
        assert "Fuerza full body A" in text
        assert "40-50 min" in text

if __name__ == "__main__":
    unittest.main()
