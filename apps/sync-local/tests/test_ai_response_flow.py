from __future__ import annotations

import io
import copy
import json
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from garmin_sync import ai_worker as worker

JOB_CREATED_AT = '2026-10-03T21:50:00+00:00'


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
        voice_sends = []
        telegram_sends = []

        def capture_voice(chat_id, path, caption):
            voice_sends.append((chat_id, path, caption))

        def capture_telegram(method, payload):
            telegram_sends.append((method, payload))
            return {"ok": True}

        with patch.object(worker, "call_ollama", return_value=ollama_result(answer)) as model, patch.object(worker, "deterministic_answer") as direct, patch.object(worker, "download_telegram_audio", return_value=Path("audio.ogg")), patch.object(worker, "transcribe_audio", return_value="¿Qué hago mañana?"), patch.object(worker, "synthesize_voice", return_value=Path("voice.ogg")) as synth, patch.object(worker, "send_telegram_voice", side_effect=capture_voice), patch.object(worker, "telegram_api", side_effect=capture_telegram):
            for job in ({"id": "text", "text": "¿Qué hago mañana?", "created_at": JOB_CREATED_AT}, {"id": "voice", "audio_file_id": "audio", "response_mode": "voice", "chat_id": "chat", "created_at": JOB_CREATED_AT}):
                worker.process_job(job, {})
                captured.append(self.post.call_args.args[1])
            self.assertEqual(model.call_count, 2)
            self.assertEqual(model.call_args_list[0].args[0], model.call_args_list[1].args[0])
            self.assertEqual(model.call_args_list[0].args[1], model.call_args_list[1].args[1])
            direct.assert_not_called()
            self.assertEqual([item["answer"] for item in captured], [answer, answer])
            self.assertIn("Respuesta tardía", synth.call_args.args[0])
            self.assertTrue(synth.call_args.args[0].endswith(answer))
            self.assertEqual(captured[1]["notify_telegram"], False)
            self.assertEqual(captured[1]["transcript"], "¿Qué hago mañana?")
            self.assertEqual(voice_sends[0][0], "chat")
            self.assertIn("Respuesta tardía", voice_sends[0][2])
            backups = [item for item in telegram_sends if item[0] == "sendMessage"]
            self.assertEqual(len(backups), 1)
            self.assertIn("Respuesta tardía", backups[0][1]["text"])
            self.assertTrue(backups[0][1]["text"].endswith(answer))

    def test_model_unavailable_returns_labelled_basic_reading(self) -> None:
        with patch.object(worker, "call_ollama", side_effect=httpx.ConnectError("offline")), patch.object(worker, "deterministic_answer", return_value="Hoy mantén la carga suave."):
            worker.process_job({"id": "text", "text": "¿Qué hago mañana?", "created_at": JOB_CREATED_AT}, {})
            payload = self.post.call_args.args[1]
            self.assertEqual(payload["status"], "completed")
            self.assertIn("lectura básica", payload["answer"])
            self.assertIn("Hoy mantén la carga suave.", payload["answer"])

    def test_v3_text_voice_share_canonical_response_without_model(self):
        question = 'analiza hoy y dime qué hacer mañana'
        compact = {'extra_context': {'checkins': [{'date': '2026-10-03', 'pain': True}]}}
        with patch.object(worker, 'COACH_ANALYSIS_V3_ENABLED', True), patch.object(worker, 'compact_context', return_value=compact), patch.object(worker, 'call_ollama') as model, patch.object(worker, 'download_telegram_audio', return_value=Path('audio.ogg')), patch.object(worker, 'transcribe_audio', return_value=question), patch.object(worker, 'synthesize_voice', return_value=Path('voice.ogg')) as synth, patch.object(worker, 'send_telegram_voice'):
            outputs = []
            for job in ({'id': 'v3-text', 'text': question},
                        {'id': 'v3-voice', 'audio_file_id': 'audio', 'response_mode': 'voice', 'chat_id': 'chat'}):
                worker.process_job({**job, 'created_at': JOB_CREATED_AT}, {})
                outputs.append(self.post.call_args.args[1])
            model.assert_not_called()
            self.assertEqual(outputs[0]['answer'], outputs[1]['answer'])
            self.assertEqual(outputs[0]['structured_output'], outputs[1]['structured_output'])
            self.assertEqual(outputs[0]['output_source'], 'deterministic')
            self.assertIn('Respuesta tardía', synth.call_args.args[0])
            self.assertTrue(synth.call_args.args[0].endswith(outputs[0]['answer']))

    def test_shared_late_response_fixture_matches_worker_classification(self):
        from garmin_sync.coach_job_time import job_created_at

        details = getattr(worker, "late_response_details", None)
        self.assertIsNotNone(details, "worker must expose its delivery timing classification")
        fixture_path = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "late_response_cases.json"
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["id"]):
                now = datetime.fromisoformat(case["now"])
                outcome, _full_note, _spoken_note = details(
                    {"created_at": case.get("created_at")}, now=now
                )
                self.assertEqual(outcome, case["expected"])

        with self.assertRaises(ValueError):
            job_created_at({"created_at": "2026-10-11T10:00:00"})
        self.assertIsNotNone(job_created_at({"created_at": "2026-10-11T10:00:00Z"}).tzinfo)

    def test_recent_voice_is_sent_without_late_note(self):
        answer = "Respuesta reciente."
        created_at = datetime.now(timezone.utc).isoformat()
        voice_sends = []
        with patch.object(worker, "call_ollama", return_value=ollama_result(answer)), patch.object(
            worker, "synthesize_voice", return_value=Path("voice.ogg")
        ) as synth, patch.object(
            worker, "send_telegram_voice", side_effect=lambda chat, path, caption: voice_sends.append(caption)
        ), patch.object(worker, "telegram_api"):
            worker.process_job(
                {"id": "recent-voice", "text": "¿Qué hago?", "response_mode": "voice",
                 "chat_id": "chat", "created_at": created_at},
                {},
            )

        self.assertEqual(synth.call_args.args[0], answer)
        self.assertEqual(voice_sends, [answer])
        self.assertEqual(self.post.call_args.args[1]["answer"], answer)
        self.assertFalse(self.post.call_args.args[1]["notify_telegram"])

    def test_long_late_voice_caption_and_text_backup_keep_full_answer(self):
        answer = "R" * 3500
        telegram_sends = []

        def capture_telegram(method, payload):
            telegram_sends.append((method, payload))
            return {"ok": True}

        with patch.object(worker, "call_ollama", return_value=ollama_result(answer)), patch.object(
            worker, "synthesize_voice", return_value=Path("voice.ogg")
        ) as synth, patch.object(worker, "send_telegram_voice") as send_voice, patch.object(
            worker, "telegram_api", side_effect=capture_telegram
        ):
            worker.process_job(
                {"id": "late-long-voice", "text": "¿Qué hago?", "response_mode": "voice",
                 "chat_id": "chat", "created_at": JOB_CREATED_AT},
                {},
            )

        payload = self.post.call_args.args[1]
        self.assertEqual(payload["answer"], answer)
        self.assertFalse(payload["notify_telegram"])
        caption = send_voice.call_args.args[2]
        self.assertLessEqual(len(caption), 1024)
        self.assertIn("Respuesta tardía", caption)
        self.assertTrue(synth.call_args.args[0].endswith(answer))
        backups = [item for item in telegram_sends if item[0] == "sendMessage"]
        self.assertEqual(len(backups), 1)
        text = backups[0][1]["text"]
        self.assertIn("Respuesta tardía a tu consulta", text)
        self.assertTrue(text.endswith(answer))
        self.assertLessEqual(len(text), 4096)

    def test_old_and_new_api_worker_models_never_duplicate_full_late_note(self):
        from app.response_timing import format_late_delivery

        job = {"created_at": JOB_CREATED_AT}
        now = datetime.now(timezone.utc)
        outcome, full_note, spoken_note = worker.late_response_details(job, now=now)
        self.assertEqual(outcome, "late")
        self.assertIsNotNone(full_note)

        for api_new in (False, True):
            for worker_new in (False, True):
                for mode in ("text", "voice"):
                    for answer in ("Respuesta breve.", "R" * 3500):
                        with self.subTest(api_new=api_new, worker_new=worker_new,
                                          mode=mode, length=len(answer)):
                            delivered = []
                            if mode == "text":
                                delivered.append(
                                    format_late_delivery(answer, job["created_at"], now=now)
                                    if api_new else answer
                                )
                            elif worker_new:
                                # The worker adds a short spoken note and either a full
                                # caption or one full text backup; API sends nothing.
                                delivered.append(f"{spoken_note}{answer}")
                                if len(full_note + answer) <= 1000:
                                    delivered.append(f"{full_note}{answer}")
                                else:
                                    delivered.append(f"{full_note}{answer}")
                            else:
                                # The legacy worker sends voice without a note and
                                # requests text fallback only for a long answer.
                                delivered.append(answer)
                                if len(answer) > 1000:
                                    delivered.append(
                                        format_late_delivery(answer, job["created_at"], now=now)
                                        if api_new else answer
                                    )

                            complete_note_count = sum(
                                text.count(full_note.strip()) for text in delivered
                            )
                            self.assertLessEqual(complete_note_count, 1)
                            if api_new and worker_new:
                                self.assertEqual(complete_note_count, 1)

    def test_voice_failure_preserves_full_answer_as_text(self) -> None:
        answer = "Hoy te recomiendo descansar para recuperar. " * 30
        for result in (None, RuntimeError("Piper unavailable")):
            with self.subTest(result=result), patch.object(worker, "call_ollama", return_value=ollama_result(answer)), patch.object(worker, "synthesize_voice", side_effect=result if isinstance(result, Exception) else None, return_value=None):
                worker.process_job({"id": "voice", "text": "¿Qué hago?", "response_mode": "voice", "chat_id": "chat", "created_at": JOB_CREATED_AT}, {})
                payload = self.post.call_args.args[1]
                self.assertEqual(payload["answer"], answer)
                self.assertEqual(payload["response_mode"], "text")
                self.assertTrue(payload.get("notify_telegram", True))

    def test_processing_indicator_repeats_typing_until_stopped(self) -> None:
        calls = []

        def fake_telegram(method, payload):
            calls.append((method, payload))
            return {"ok": True}

        def slow_answer(_question, _context, **kwargs):
            time.sleep(0.04)
            return ollama_result("Hoy descansa.")

        with patch.object(worker, "TELEGRAM_BOT_TOKEN", "token"), patch.object(worker, "TELEGRAM_ACTION_INTERVAL_SECONDS", 0.01, create=True), patch.object(worker, "telegram_api", side_effect=fake_telegram), patch.object(worker, "call_ollama", side_effect=slow_answer):
            worker.process_job({"id": "text", "chat_id": "chat", "text": "¿Qué hago?", "created_at": JOB_CREATED_AT}, {})
            count_after_stop = len(calls)
            time.sleep(0.03)

        self.assertGreaterEqual(count_after_stop, 2)
        self.assertEqual(len(calls), count_after_stop)
        self.assertTrue(all(call == ("sendChatAction", {"chat_id": "chat", "action": "typing"}) for call in calls))

    def _generation_transport(self, requests, decisions=None, mutate=None):
        def post(*args, **kwargs):
            request = kwargs['json']
            requests.append(request)
            schema = request['format']
            raw = dict(schema_version='1', context_snapshot_id=schema['properties']['context_snapshot_id']['const'],
                       response_type='single_session', decisions=copy.deepcopy(decisions) if decisions else [{'action': 'ask_user'}],
                       conclusions=[], evidence_refs=[])
            if mutate: mutate(raw, len(requests))
            reply = Mock()
            reply.json.return_value = {'message': {'content': json.dumps(raw), 'thinking': 'private reasoning'},
                                       'done_reason': 'stop'}
            return reply
        return post

    def test_simple_generation_uses_internal_contract_and_hides_reasoning(self):
        requests = []
        with patch.object(worker.httpx, 'post', side_effect=self._generation_transport(requests)):
            result = worker.call_ollama('¿Qué hago?', {})
        self.assertEqual(len(requests), 1)
        self.assertFalse(requests[0]['think'])
        self.assertLessEqual(requests[0]['options']['temperature'], 0.3)
        self.assertNotIn('answer', requests[0]['format']['properties'])
        self.assertNotIn('private reasoning', result.answer)
        self.assertEqual(result.source, 'ollama')
        self.assertEqual(result.answer, result.structured_output['answer'])

    def test_weekly_generation_has_more_token_room(self):
        requests = []
        with patch.object(worker.httpx, 'post', side_effect=self._generation_transport(requests)):
            worker.call_ollama('¿Qué hago?', {})
            worker.call_ollama('Plan de esta semana', {})
        self.assertGreater(requests[1]['options']['num_predict'], requests[0]['options']['num_predict'])

    def test_planned_tomorrow_resolves_dose_and_rejects_model_duplicates(self):
        tomorrow = (datetime.now(ZoneInfo('Europe/Madrid')).date() + timedelta(days=1)).isoformat()
        context = {'training_plan': {'sessions': [{'id': 'run', 'date': tomorrow, 'sport': 'running',
            'session_type': 'easy_run', 'intensity': 'easy', 'duration_min': 40, 'duration_max': 55}]}}
        requests = []
        def mutate(raw, attempt):
            if attempt == 1: raw['decisions'][0]['duration_min'] = 30
        with patch.object(worker.httpx, 'post', side_effect=self._generation_transport(requests,
                          [{'action': 'keep_plan', 'session_id': 'run'}], mutate)):
            result = worker.call_ollama('¿Qué hago mañana?', context)
        self.assertEqual(len(requests), 2)
        decision = result.structured_output['decisions'][0]
        self.assertEqual(decision['date'], tomorrow)
        self.assertEqual(decision['source'], 'training_plan')
        self.assertEqual(decision['duration_min'], 40)
        self.assertIn('40 a 55 minutos', result.answer)
        self.assertNotIn('30 minutos', result.answer)

    def test_catalog_and_repair_do_not_invent_checkin(self):
        requests = []
        def mutate(raw, attempt):
            if attempt == 1: raw['evidence_refs'] = ['checkin:fake']
        with patch.object(worker.httpx, 'post', side_effect=self._generation_transport(requests, mutate=mutate)):
            result = worker.call_ollama('¿Qué hago?', {})
        catalog = json.loads(requests[0]['messages'][1]['content'])['context']['available_evidence']
        self.assertEqual(catalog, [])
        repair = json.loads(requests[1]['messages'][-1]['content'])
        self.assertEqual(repair['validation_errors'][0]['code'], 'UNKNOWN_EVIDENCE_REF')
        self.assertEqual(result.structured_output['evidence'], [])

    def test_process_job_sends_canonical_answer_and_auditable_output(self):
        requests = []
        with patch.object(worker, 'ollama_generate') as generate:
            def answer(messages, **kwargs):
                raw = dict(schema_version='1', context_snapshot_id=kwargs['response_schema']['properties']['context_snapshot_id']['const'],
                           response_type='information', decisions=[{'action': 'ask_user'}], conclusions=[], evidence_refs=[])
                return {'message': {'content': json.dumps(raw)}}
            generate.side_effect = answer
            worker.process_job({'id': 'job', 'text': '¿Qué hago?', 'created_at': '2026-10-03T21:50:00+00:00'}, {})
        payload = self.post.call_args.args[1]
        self.assertEqual(payload['output_source'], 'ollama')
        self.assertEqual(payload['answer'], payload['structured_output']['answer'])
        self.assertEqual(payload['structured_output']['decisions'][0]['action'], 'ask_user')

    def test_process_job_uses_enqueue_timestamp_instead_of_worker_time(self):
        enqueued = '2026-10-03T21:50:00+00:00'
        with patch.object(worker, 'call_ollama', return_value=ollama_result('respuesta')) as model:
            worker.process_job({'id': 'job', 'text': '¿Qué hago mañana?', 'created_at': enqueued}, {})

        self.assertEqual(model.call_args.kwargs['now'], datetime.fromisoformat(enqueued))

    def test_process_job_without_trusted_enqueue_timestamp_fails_closed(self):
        with patch.object(worker, 'call_ollama') as model, self.assertRaises(ValueError):
            worker.process_job({'id': 'job', 'text': '¿Qué hago mañana?'}, {})

        model.assert_not_called()
        self.assertEqual(self.post.call_args.args[1]['status'], 'failed')

    def test_http_failure_is_not_retried_as_a_validation_repair(self) -> None:
        with patch.object(worker.httpx, "post", side_effect=httpx.ConnectError("offline")) as post:
            with self.assertRaises(httpx.ConnectError):
                worker.call_ollama("¿Qué hago?", {})

        self.assertEqual(post.call_count, 1)

    def test_truncated_or_empty_model_response_falls_back(self) -> None:
        for content, reason in (("Hoy reduce la carga si", "length"), ("", "stop")):
            draft = {"message": {"content": content, "thinking": "secret"}, "done_reason": reason}
            with self.subTest(reason=reason), patch.object(worker, "ollama_generate", return_value=draft):
                worker.process_job({"id": "job", "text": "¿Qué hago mañana?", "created_at": JOB_CREATED_AT}, {})
                payload = self.post.call_args.args[1]
                self.assertIn("lectura básica", payload["answer"])
                self.assertIsNone(payload["structured_output"])
                self.assertEqual(payload["output_source"], "deterministic_fallback")

    def test_incomplete_single_draft_is_not_sent(self) -> None:
        draft = {"message": {"content": "Hoy corre si", "thinking": "private"}, "done_reason": "length"}
        with patch.object(worker, "ollama_generate", return_value=draft) as generate:
            worker.process_job({"id": "job", "text": "¿Qué hago mañana?", "created_at": JOB_CREATED_AT}, {})
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
