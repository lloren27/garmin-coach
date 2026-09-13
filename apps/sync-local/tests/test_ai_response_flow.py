from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from garmin_sync import ai_worker as worker


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
        with patch.object(worker, "call_ollama", return_value=answer) as model, patch.object(worker, "deterministic_answer") as direct, patch.object(worker, "download_telegram_audio", return_value=Path("audio.ogg")), patch.object(worker, "transcribe_audio", return_value="¿Qué hago mañana?"), patch.object(worker, "synthesize_voice", return_value=Path("voice.ogg")) as synth, patch.object(worker, "send_telegram_voice"):
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
            with self.subTest(result=result), patch.object(worker, "call_ollama", return_value=answer), patch.object(worker, "synthesize_voice", side_effect=result if isinstance(result, Exception) else None, return_value=None):
                worker.process_job({"id": "voice", "text": "¿Qué hago?", "response_mode": "voice", "chat_id": "chat"}, {})
                payload = self.post.call_args.args[1]
                self.assertEqual(payload["answer"], answer)
                self.assertEqual(payload["response_mode"], "text")
                self.assertTrue(payload.get("notify_telegram", True))

    def test_model_analyses_then_writes_with_same_context_and_hides_internal_reasoning(self) -> None:
        response = Mock()
        response.json.return_value = {"message": {"thinking": "private reasoning", "content": "Hoy conviene reducir la carga para recuperar."}, "done_reason": "stop"}
        with patch.object(worker.httpx, "post", return_value=response) as post, patch.object(worker, "OLLAMA_THINK", True):
            result = worker.call_ollama("¿Qué hago?", {})
            self.assertEqual(post.call_count, 2)
            analysis_request = post.call_args_list[0].kwargs["json"]
            final_request = post.call_args_list[1].kwargs["json"]
            self.assertTrue(analysis_request["think"])
            self.assertFalse(final_request["think"])
            self.assertEqual(analysis_request["messages"][1], final_request["messages"][1])
            self.assertIn("Informe previo", final_request["messages"][2]["content"])
            self.assertGreaterEqual(final_request["options"]["num_predict"], 3072)
            self.assertNotIn("/no_think", str(final_request))
            self.assertNotIn("private reasoning", result)

    def test_truncated_or_empty_model_response_is_not_presented_as_complete(self) -> None:
        for content, reason in (("Hoy reduce la carga si", "length"), ("", "stop")):
            response = Mock()
            response.json.return_value = {"message": {"content": content, "thinking": "secret"}, "done_reason": reason}
            with patch.object(worker.httpx, "post", return_value=response):
                result = worker.call_ollama("¿Qué hago mañana?", worker.enrich_context_for_question("¿Qué hago mañana?", {}))
                self.assertIn("lectura básica", result)
                self.assertNotIn("secret", result)

    def test_incomplete_final_draft_is_not_sent_after_successful_analysis(self) -> None:
        report = {"message": {"content": "Hoy la carga es alta y conviene recuperar."}, "done_reason": "stop"}
        draft = {"message": {"content": "Hoy corre si", "thinking": "private"}, "done_reason": "length"}
        with patch.object(worker, "ollama_generate", side_effect=[report, draft]) as generate:
            result = worker.call_ollama("¿Qué hago mañana?", worker.enrich_context_for_question("¿Qué hago mañana?", {}))
            self.assertEqual(generate.call_count, 2)
            self.assertLessEqual(generate.call_args_list[1].kwargs["timeout_seconds"], generate.call_args_list[0].kwargs["timeout_seconds"])
            self.assertIn("lectura básica", result)
            self.assertNotIn("Hoy corre si", result)
            self.assertNotIn("private", result)

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
