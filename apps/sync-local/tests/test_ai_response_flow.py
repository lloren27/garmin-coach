from __future__ import annotations

import io
import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from garmin_sync import ai_worker as worker


def structured_response(
    answer: str,
    *,
    response_type: str = "single_session",
    decisions: list[dict] | None = None,
    evidence: list[dict] | None = None,
) -> str:
    return json.dumps(
        {
            "response_type": response_type,
            "answer": answer,
            "decisions": decisions or [],
            "evidence": evidence or [],
            "warnings": [],
            "missing_data": [],
        }
    )


def ollama_result(answer: str) -> worker.CoachRunResult:
    return worker.CoachRunResult(
        answer=answer,
        structured_output={"answer": answer},
        source="ollama",
    )


class ResponseFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.tmp = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.object(worker, "VOICE_DIR", Path(self.tmp)))
        stack.enter_context(patch.object(worker, "fetch_wattwise_context", return_value=None))
        stack.enter_context(redirect_stdout(io.StringIO()))
        self.post = stack.enter_context(patch.object(worker, "post_json"))

    def test_text_and_voice_use_model_and_same_answer_without_voice_truncation(self) -> None:
        answer = "Hoy te recomiendo un rodaje suave para facilitar la recuperación. " * 20
        captured = []
        with patch.object(worker, "call_ollama", return_value=ollama_result(answer)) as model, patch.object(worker, "deterministic_answer") as direct, patch.object(worker, "download_telegram_audio", return_value=Path("audio.ogg")), patch.object(worker, "transcribe_audio", return_value="¿Qué hago mañana?"), patch.object(worker, "synthesize_voice", return_value=Path("voice.ogg")) as synth, patch.object(worker, "send_telegram_voice"):
            for job in ({"id": "text", "text": "¿Qué hago mañana?"}, {"id": "voice", "audio_file_id": "audio", "response_mode": "voice", "chat_id": "chat"}):
                worker.process_job(job, {})
                captured.append(self.post.call_args.args[1])
            self.assertEqual(model.call_count, 2)
            self.assertEqual(model.call_args_list[0].args[0], model.call_args_list[1].args[0])
            self.assertEqual(model.call_args_list[0].args[1], model.call_args_list[1].args[1])
            direct.assert_not_called()
            self.assertEqual([item["answer"] for item in captured], [answer, answer])
            self.assertEqual(synth.call_args.args[0], answer)
            self.assertTrue(captured[1]["notify_telegram"])
            self.assertEqual(captured[1]["transcript"], "¿Qué hago mañana?")

    def test_model_unavailable_returns_labelled_basic_reading(self) -> None:
        with patch.object(worker, "call_ollama", side_effect=httpx.ConnectError("offline")), patch.object(worker, "deterministic_answer", return_value="Hoy mantén la carga suave."):
            worker.process_job({"id": "text", "text": "¿Qué hago mañana?"}, {})
            payload = self.post.call_args.args[1]
            self.assertEqual(payload["status"], "completed")
            self.assertIn("lectura básica", payload["answer"])
            self.assertIn("Hoy mantén la carga suave.", payload["answer"])

    def test_voice_failure_preserves_full_answer_as_text(self) -> None:
        answer = "Hoy te recomiendo descansar para recuperar. " * 30
        for result in (None, RuntimeError("Piper unavailable")):
            with self.subTest(result=result), patch.object(worker, "call_ollama", return_value=ollama_result(answer)), patch.object(worker, "synthesize_voice", side_effect=result if isinstance(result, Exception) else None, return_value=None):
                worker.process_job({"id": "voice", "text": "¿Qué hago?", "response_mode": "voice", "chat_id": "chat"}, {})
                payload = self.post.call_args.args[1]
                self.assertEqual(payload["answer"], answer)
                self.assertEqual(payload["response_mode"], "text")
                self.assertTrue(payload.get("notify_telegram", True))

    def test_processing_indicator_repeats_typing_until_stopped(self) -> None:
        calls = []

        def fake_telegram(method, payload):
            calls.append((method, payload))
            return {"ok": True}

        def slow_answer(_question, _context):
            time.sleep(0.04)
            return ollama_result("Hoy descansa.")

        with patch.object(worker, "TELEGRAM_BOT_TOKEN", "token"), patch.object(worker, "TELEGRAM_ACTION_INTERVAL_SECONDS", 0.01, create=True), patch.object(worker, "telegram_api", side_effect=fake_telegram), patch.object(worker, "call_ollama", side_effect=slow_answer):
            worker.process_job({"id": "text", "chat_id": "chat", "text": "¿Qué hago?"}, {})
            count_after_stop = len(calls)
            time.sleep(0.03)

        self.assertGreaterEqual(count_after_stop, 2)
        self.assertEqual(len(calls), count_after_stop)
        self.assertTrue(all(call == ("sendChatAction", {"chat_id": "chat", "action": "typing"}) for call in calls))

    def test_simple_question_uses_one_concise_generation_and_hides_internal_reasoning(self) -> None:
        response = Mock()
        response.json.return_value = {"message": {"thinking": "private reasoning", "content": structured_response("Hoy conviene reducir la carga para recuperar.")}, "done_reason": "stop"}
        with patch.object(worker.httpx, "post", return_value=response) as post:
            result = worker.call_ollama("¿Qué hago?", {})
            self.assertEqual(post.call_count, 1)
            request = post.call_args.kwargs["json"]
            self.assertFalse(request["think"])
            self.assertLessEqual(request["options"]["num_predict"], 1024)
            self.assertLessEqual(request["options"]["temperature"], 0.3)
            self.assertIn("100 y 180 palabras", str(request["messages"]))
            self.assertNotIn("/no_think", str(request))
            self.assertNotIn("private reasoning", result.answer)
            self.assertEqual(result.source, "ollama")
            self.assertEqual(result.structured_output["response_type"], "single_session")

    def test_valid_structured_response_is_sent_with_auditable_output(self) -> None:
        draft = {
            "message": {
                "content": structured_response(
                    "Hoy realiza treinta minutos muy suaves y para si aparece dolor.",
                )
            },
            "done_reason": "stop",
        }

        with patch.object(worker, "ollama_generate", return_value=draft):
            worker.process_job({"id": "job", "text": "¿Qué me recomiendas?"}, {})

        payload = self.post.call_args.args[1]
        self.assertEqual(payload["output_source"], "ollama")
        self.assertEqual(payload["structured_output"]["response_type"], "single_session")
        self.assertEqual(
            payload["structured_output"]["answer"],
            "Hoy realiza treinta minutos muy suaves y para si aparece dolor.",
        )

    def test_weekly_plan_uses_one_generation_with_more_room_than_a_simple_answer(self) -> None:
        response = Mock()
        response.json.return_value = {"message": {"content": structured_response("Lunes descansa y el martes haz un rodaje suave de cuarenta minutos. El resto de la semana mantén la carga moderada y ajusta si aparecen molestias.", response_type="weekly_plan")}, "done_reason": "stop"}
        with patch.object(worker.httpx, "post", return_value=response) as post:
            worker.call_ollama("Prepárame el plan de esta semana, día por día", {})
            request = post.call_args.kwargs["json"]
            self.assertEqual(post.call_count, 1)
            self.assertGreater(request["options"]["num_predict"], 1024)
            self.assertLessEqual(request["options"]["num_predict"], 1600)
            self.assertIn("todos los días", str(request["messages"]))
            self.assertIn("día y fecha exacta", str(request["messages"]))

    def test_tomorrow_target_is_explicitly_sent_to_ollama(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        answer = (
            "Mañana toca un rodaje fácil de 40 a 55 minutos, según el plan vigente. "
            "Mantén una intensidad fácil porque la carga reciente aconseja un entrenamiento suave."
        )
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": structured_response(
                    answer,
                    decisions=[
                        {
                            "action": "keep_plan",
                            "reason": "El plan vigente sigue siendo adecuado.",
                            "date": tomorrow.isoformat(),
                            "sport": "running",
                            "session_type": "easy_run",
                            "intensity": "easy",
                            "duration_min": 40,
                            "duration_max_min": 55,
                        }
                    ],
                )
            },
            "done_reason": "stop",
        }
        context = {
            "training_plan": {
                "sessions": [
                    {
                        "date": tomorrow.isoformat(),
                        "sport": "running",
                        "session_type": "easy_run",
                        "intensity": "easy",
                        "duration_min": 40,
                        "duration_max": 55,
                    }
                ]
            }
        }

        with patch.object(worker.httpx, "post", return_value=response) as post:
            worker.call_ollama("¿Qué entrenamiento debería hacer mañana?", context)

        request = post.call_args.kwargs["json"]
        self.assertIn("question_target", str(request["messages"]))
        self.assertIn(tomorrow.isoformat(), str(request["messages"]))

    def test_tomorrow_schema_and_repair_require_the_plan_session_type(self) -> None:
        tomorrow = datetime.now(ZoneInfo("Europe/Madrid")).date() + timedelta(days=1)
        answer = (
            "Mañana toca un rodaje fácil de 40 a 55 minutos, según el plan vigente. "
            "Mantén una intensidad fácil porque la carga reciente aconseja un entrenamiento suave."
        )
        invalid = Mock()
        invalid.json.return_value = {
            "message": {
                "content": structured_response(
                    answer,
                    decisions=[
                        {
                            "action": "keep_plan",
                            "reason": "El plan vigente sigue siendo adecuado.",
                            "date": tomorrow.isoformat(),
                            "sport": "running",
                            "session_type": "running",
                            "intensity": "easy",
                            "duration_min": 40,
                            "duration_max_min": 55,
                        }
                    ],
                )
            },
            "done_reason": "stop",
        }
        repaired = Mock()
        repaired.json.return_value = {
            "message": {
                "content": structured_response(
                    answer,
                    decisions=[
                        {
                            "action": "keep_plan",
                            "reason": "El plan vigente sigue siendo adecuado.",
                            "date": tomorrow.isoformat(),
                            "sport": "running",
                            "session_type": "easy_run",
                            "intensity": "easy",
                            "duration_min": 40,
                            "duration_max_min": 55,
                        }
                    ],
                )
            },
            "done_reason": "stop",
        }
        context = {
            "training_plan": {
                "sessions": [
                    {
                        "date": tomorrow.isoformat(),
                        "sport": "running",
                        "session_type": "easy_run",
                        "intensity": "easy",
                        "duration_min": 40,
                        "duration_max": 55,
                    }
                ]
            }
        }

        with patch.object(worker.httpx, "post", side_effect=[invalid, repaired]) as post:
            result = worker.call_ollama("¿Qué entrenamiento debería hacer mañana?", context)

        self.assertEqual(result.source, "ollama")
        schema = post.call_args_list[0].kwargs["json"]["format"]
        decision_schema = schema["$defs"]["CoachDecision"]
        session_type = decision_schema["properties"]["session_type"]
        self.assertEqual(session_type["enum"], ["easy_run"])
        self.assertIn("session_type", decision_schema["required"])
        repair_prompt = post.call_args_list[1].kwargs["json"]["messages"][-1]["content"]
        self.assertIn("expected 'easy_run', got 'running'", repair_prompt)

    def test_prompt_exposes_only_available_evidence_sources(self) -> None:
        answer = "Hoy mantén la carga suave porque no hay datos adicionales para elevar la intensidad."
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": structured_response(
                    answer,
                    evidence=[{"source": "backend", "fact": "No hay datos adicionales."}],
                )
            },
            "done_reason": "stop",
        }

        with patch.object(worker.httpx, "post", return_value=response) as post:
            worker.call_ollama("¿Qué hago?", {})

        prompt = str(post.call_args.kwargs["json"]["messages"])
        self.assertIn("allowed_evidence_sources", prompt)
        self.assertIn("backend", prompt)
        self.assertNotIn("'checkin'", prompt)

    def test_validation_failure_is_repaired_once_with_allowed_sources(self) -> None:
        answer = "Hoy mantén la carga suave porque los datos disponibles no justifican más intensidad."
        invalid = Mock()
        invalid.json.return_value = {
            "message": {
                "content": structured_response(
                    answer,
                    evidence=[{"source": "checkin", "fact": "No hay molestias registradas."}],
                )
            },
            "done_reason": "stop",
        }
        repaired = Mock()
        repaired.json.return_value = {
            "message": {
                "content": structured_response(
                    answer,
                    evidence=[{"source": "backend", "fact": "No hay datos adicionales."}],
                )
            },
            "done_reason": "stop",
        }

        with patch.object(worker.httpx, "post", side_effect=[invalid, repaired]) as post:
            result = worker.call_ollama("¿Qué hago?", {})

        self.assertEqual(result.source, "ollama")
        self.assertEqual(post.call_count, 2)
        repair_prompt = post.call_args_list[1].kwargs["json"]["messages"][-1]["content"]
        self.assertIn("Evidence references unavailable source: checkin", repair_prompt)
        self.assertIn("backend", repair_prompt)

    def test_http_failure_is_not_retried_as_a_validation_repair(self) -> None:
        with patch.object(worker.httpx, "post", side_effect=httpx.ConnectError("offline")) as post:
            with self.assertRaises(httpx.ConnectError):
                worker.call_ollama("¿Qué hago?", {})

        self.assertEqual(post.call_count, 1)

    def test_truncated_or_empty_model_response_falls_back(self) -> None:
        for content, reason in (("Hoy reduce la carga si", "length"), ("", "stop")):
            draft = {"message": {"content": content, "thinking": "secret"}, "done_reason": reason}
            with self.subTest(reason=reason), patch.object(worker, "ollama_generate", return_value=draft):
                worker.process_job({"id": "job", "text": "¿Qué hago mañana?"}, {})
                payload = self.post.call_args.args[1]
                self.assertIn("lectura básica", payload["answer"])
                self.assertIsNone(payload["structured_output"])
                self.assertEqual(payload["output_source"], "deterministic_fallback")

    def test_incomplete_single_draft_is_not_sent(self) -> None:
        draft = {"message": {"content": "Hoy corre si", "thinking": "private"}, "done_reason": "length"}
        with patch.object(worker, "ollama_generate", return_value=draft) as generate:
            worker.process_job({"id": "job", "text": "¿Qué hago mañana?"}, {})
            self.assertEqual(generate.call_count, 2)
            payload = self.post.call_args.args[1]
            self.assertIn("lectura básica", payload["answer"])
            self.assertNotIn("Hoy corre si", payload["answer"])
            self.assertIsNone(payload["structured_output"])

    def test_context_retains_activities_history_strength_and_source_dates(self) -> None:
        activities = [{"id": i, "sport": "cycling" if i % 2 else "running"} for i in range(25)]
        context = {"sync": {"received_at": "2026-09-10", "payload": {"summary": {"activities": activities, "weekly": [{"km": 42}]}}}, "history": [{"received_at": str(i), "payload": {"wellness": {"sleep": i}}} for i in range(28)], "coach_brief": {"strength_load": {"load_score_7d": 88}}, "wattwise": {"received_at": "2026-09-09"}, "wattwise_live": {"status": "unavailable"}, "lab_tests": [{"status": "applied"}, {"status": "pending"}]}
        extra = worker.compact_context(context)["extra_context"]
        self.assertEqual(extra["recent_activities"], activities)
        self.assertEqual(len(extra["history"]), 28)
        self.assertEqual(extra["history"][-1]["wellness"], {"sleep": 27})
        self.assertEqual(extra["summary"]["weekly"], [{"km": 42}])
        self.assertEqual(extra["strength_manual"], {"load_score_7d": 88})
        self.assertEqual(extra["wattwise_snapshot"]["received_at"], "2026-09-09")
        self.assertEqual(extra["applied_lab_tests"], [{"status": "applied"}])
        self.assertIn("current_time", extra)

    def test_history_uses_latest_snapshot_per_day(self) -> None:
        result = worker.compact_history([
            {"received_at": "2026-09-09T08:00:00+02:00", "payload": {"wellness": {"sleep": 5}}},
            {"received_at": "2026-09-09T20:00:00+02:00", "payload": {"wellness": {"sleep": 6}}},
            {"received_at": "2026-09-10T08:00:00+02:00", "payload": {"wellness": {"sleep": 7}}},
        ])
        self.assertEqual(len(result), 2)
        self.assertEqual([item["wellness"]["sleep"] for item in result], [6, 7])

    def test_stale_generated_date_is_not_hidden_by_recent_upload(self) -> None:
        now = datetime(2026, 9, 13, 12, tzinfo=ZoneInfo("Europe/Madrid"))
        sync = {"received_at": now.isoformat(), "payload": {"generated_at": "2026-09-09T21:00:00+02:00"}}
        freshness = worker.sync_freshness(sync, now)
        self.assertEqual(freshness["age_days"], 4)
        result = worker.finish_coach_answer("Ese día acumulaste carga.", {"extra_context": {"data_freshness": freshness}})
        self.assertIn("9 de septiembre de 2026", result)
        self.assertIn("no confirmar cómo estás hoy", result)
        self.assertIn("Ese día acumulaste carga.", result)

    def test_freshness_distinguishes_current_missing_and_future_dates(self) -> None:
        now = datetime(2026, 9, 13, 12, tzinfo=ZoneInfo("Europe/Madrid"))
        self.assertEqual(worker.sync_freshness({"received_at": now.isoformat()}, now)["status"], "current")
        self.assertEqual(worker.sync_freshness({}, now)["status"], "unknown")
        self.assertEqual(worker.sync_freshness({"received_at": "2026-09-15"}, now)["status"], "future")

    def test_latest_no_soreness_checkin_is_kept(self) -> None:
        context = worker._compact_injury_checkins([{"created_at": "yesterday", "checkin": {"pain": "gemelo"}}, {"created_at": "today", "checkin": {"soreness": "no", "energy": 2}}])
        self.assertEqual(len(context), 2)
        self.assertEqual(context[-1]["soreness"], "no")
        self.assertNotIn("energy", context[-1])

    def test_punctuation_decimals_percentages_and_paces_are_readable(self) -> None:
        result = worker.prepare_text_for_tts("Hoy, corre 30 min\nDespués, recupera\nRitmo 5:00–5:30 min/km. Carga 100%, ratio 1.05.")
        self.assertIn("Hoy, corre treinta minutos. Después, recupera.", result)
        self.assertIn("cinco minutos por kilómetro a cinco minutos y treinta segundos por kilómetro", result)
        self.assertIn("cien por ciento", result)
        self.assertIn("uno coma cero cinco", result)
        self.assertNotIn("ciento cero", result)

    def test_dates_are_read_as_dates_not_ratios(self) -> None:
        for stamp in ("09/09/2026", "2026-09-09"):
            result = worker.prepare_text_for_tts(f"La actividad es del {stamp}.")
            self.assertIn("nueve de septiembre de dos mil veintiseis", result)
            self.assertNotIn("sobre", result)

    def test_shared_pace_unit_in_prose_does_not_become_clock_time(self) -> None:
        result = worker.prepare_text_for_tts("Corre entre 5:30 y 6:00 min/km, si no tienes molestias.")
        self.assertIn("entre cinco minutos y treinta segundos por kilómetro y seis minutos por kilómetro,", result)
        self.assertNotIn("horas", result)

    def test_cross_sport_paragraph_does_not_corrupt_running_pace(self) -> None:
        text = "El running fue a 5:30/km y la bici a 25 km/h."
        self.assertEqual(worker.polish_coach_answer(text), text)

    def test_trim_ends_at_sentence_not_decimal_and_keeps_paragraphs(self) -> None:
        text = "Hoy descansa. La carga fue 12.5 y necesita valoración."
        self.assertEqual(worker.trim_answer(text, 30), "Hoy descansa.")
        self.assertEqual(worker.polish_coach_answer("Hoy, descansa\n\nMañana revisamos"), "Hoy, descansa.\n\nMañana revisamos.")
        self.assertNotIn("secret", worker.clean_answer("<think>secret"))


if __name__ == "__main__":
    unittest.main()
