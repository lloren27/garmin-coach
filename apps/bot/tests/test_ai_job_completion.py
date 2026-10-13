from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app import main
from app.response_timing import format_late_delivery


class AiJobCompletionTests(unittest.TestCase):
    def deterministic_payload(self):
        answer = 'No puedo valorar si es seguro hacerla. ¿La molestia continúa?'
        return {'status': 'completed', 'answer': answer, 'output_source': 'deterministic',
                'structured_output': {'response_type': 'information', 'answer': answer,
                    'decisions': [{'action': 'ask_user', 'source': 'deterministic',
                                   'reason': '¿La molestia continúa?'}]}}

    def test_accepts_read_only_deterministic_source(self):
        with patch.object(main, 'require_sync_secret'), patch.object(main, 'complete_ai_job', return_value={'id': 'job-1'}) as save:
            asyncio.run(main.complete_ai_job_endpoint('job-1', self.deterministic_payload()))
            self.assertEqual(save.call_args.kwargs['output_source'], 'deterministic')

    def test_engine_incompatibility_delivers_factual_view_in_the_job_scope(self):
        document = {
            'id': 'alias-job', 'chat_id': 'chat-1', 'created_at': '2026-10-11T11:00:00Z',
            'status': 'failed', 'error': 'COACH_ENGINE_REQUIREMENT_UNAVAILABLE',
            'required_engine': 'v3', 'factual_scope': 'today',
        }
        sync = {'payload': {'summary': {'activities': [
            {'date': '2026-10-11', 'sport': 'running', 'km': 8.0, 'source': 'garmin'},
            {'date': '2026-10-10', 'sport': 'cycling', 'km': 20.0, 'source': 'strava'},
        ]}}}
        with patch.object(main, 'require_sync_secret'), patch.object(
            main, 'complete_ai_job', return_value=document
        ), patch.object(main, 'load_sync', return_value=sync), patch.object(
            main, 'send_telegram_message', new_callable=AsyncMock
        ) as send:
            asyncio.run(main.complete_ai_job_endpoint(
                'alias-job', {'status': 'failed', 'error': 'COACH_ENGINE_REQUIREMENT_UNAVAILABLE'}
            ))
        delivered = send.await_args.args[1]
        self.assertIn('No se usó la ruta antigua', delivered)
        self.assertIn('Datos factuales del día consultado (2026-10-11)', delivered)
        self.assertIn('8.00 km', delivered)
        self.assertNotIn('20.00 km', delivered)

    def test_rejects_deterministic_prescription_before_saving(self):
        payload = self.deterministic_payload()
        payload['structured_output']['decisions'][0]['action'] = 'keep_plan'
        with patch.object(main, 'require_sync_secret'), patch.object(main, 'complete_ai_job') as save:
            with self.assertRaises(HTTPException):
                asyncio.run(main.complete_ai_job_endpoint('job-1', payload))
            save.assert_not_called()

    def test_rejects_mismatched_text_before_saving(self):
        payload = self.deterministic_payload()
        payload['answer'] = 'Haz la sesión de umbral sin problemas.'
        with patch.object(main, 'require_sync_secret'), patch.object(main, 'complete_ai_job') as save:
            with self.assertRaises(HTTPException):
                asyncio.run(main.complete_ai_job_endpoint('job-1', payload))
            save.assert_not_called()

    def test_store_rejects_deterministic_mutation_without_io(self):
        from app import store
        payload = self.deterministic_payload()
        payload['structured_output']['decisions'][0]['action'] = 'modify_session'
        with patch.object(store, 'DATABASE_URL', None), patch.object(store, 'load_ai_jobs_file') as load:
            with self.assertRaises(ValueError):
                store.complete_ai_job('job-1', **payload)
            load.assert_not_called()

    def test_ollama_source_requires_structured_output(self) -> None:
        payload = {
            "status": "completed",
            "answer": "Respuesta de prueba suficientemente larga.",
            "output_source": "ollama",
            "structured_output": None,
        }

        with patch.object(main, "require_sync_secret"), patch.object(
            main,
            "complete_ai_job",
            return_value={"id": "job-1"},
        ):
            with self.assertRaisesRegex(HTTPException, "structured_output"):
                asyncio.run(main.complete_ai_job_endpoint("job-1", payload))

    def test_fallback_source_rejects_structured_output(self) -> None:
        payload = {
            "status": "completed",
            "answer": "Respuesta de prueba suficientemente larga.",
            "output_source": "deterministic_fallback",
            "structured_output": {"response_type": "information"},
        }

        with patch.object(main, "require_sync_secret"), patch.object(
            main,
            "complete_ai_job",
            return_value={"id": "job-1"},
        ):
            with self.assertRaisesRegex(HTTPException, "structured_output"):
                asyncio.run(main.complete_ai_job_endpoint("job-1", payload))

    def test_completed_text_uses_late_note_for_delivery_but_stores_canonical_answer(self):
        answer = "Respuesta canónica."
        document = {
            "id": "job-1",
            "chat_id": "chat-1",
            "created_at": "2020-01-01T09:00:00+00:00",
            "answer": answer,
            "status": "completed",
        }
        with patch.object(main, "require_sync_secret"), patch.object(
            main, "complete_ai_job", return_value=document
        ) as save, patch.object(
            main, "send_telegram_message", new_callable=AsyncMock
        ) as send:
            asyncio.run(
                main.complete_ai_job_endpoint(
                    "job-1", {"status": "completed", "answer": answer}
                )
            )

        self.assertEqual(save.call_args.kwargs["answer"], answer)
        sent_text = send.await_args.args[1]
        self.assertTrue(sent_text.startswith("Respuesta tardía a tu consulta del 01/01/2020"))
        self.assertTrue(sent_text.endswith(answer))

    def test_recent_completed_text_is_sent_without_a_note(self):
        answer = "Respuesta canónica."
        document = {
            "id": "job-1",
            "chat_id": "chat-1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "answer": answer,
            "status": "completed",
        }
        with patch.object(main, "require_sync_secret"), patch.object(
            main, "complete_ai_job", return_value=document
        ), patch.object(main, "send_telegram_message", new_callable=AsyncMock) as send:
            asyncio.run(
                main.complete_ai_job_endpoint(
                    "job-1", {"status": "completed", "answer": answer}
                )
            )
        send.assert_awaited_once_with("chat-1", answer)

    def test_unreliable_creation_time_is_disclosed_and_failed_job_is_not_annotated(self):
        answer = "Respuesta canónica."
        for created_at in (None, "2026-10-11T10:00:00"):
            document = {
                "id": "job-1",
                "chat_id": "chat-1",
                "created_at": created_at,
                "answer": answer,
                "status": "completed",
            }
            with self.subTest(created_at=created_at), patch.object(
                main, "require_sync_secret"
            ), patch.object(main, "complete_ai_job", return_value=document), patch.object(
                main, "send_telegram_message", new_callable=AsyncMock
            ) as send:
                asyncio.run(
                    main.complete_ai_job_endpoint(
                        "job-1", {"status": "completed", "answer": answer}
                    )
                )
                sent_text = send.await_args.args[1]
                self.assertIn("vigencia temporal no confirmada", sent_text)
                self.assertIn(answer, sent_text)
                self.assertNotIn("2026-10-11 10:00", sent_text)

        failed_document = {
            "id": "job-1",
            "chat_id": "chat-1",
            "created_at": "2020-01-01T09:00:00+00:00",
            "status": "failed",
        }
        with patch.object(main, "require_sync_secret"), patch.object(
            main, "complete_ai_job", return_value=failed_document
        ), patch.object(main, "send_telegram_message", new_callable=AsyncMock) as send:
            asyncio.run(
                main.complete_ai_job_endpoint(
                    "job-1", {"status": "failed", "error": "local error"}
                )
            )
        send.assert_awaited_once()
        self.assertIn("No he podido procesarlo", send.await_args.args[1])
        self.assertNotIn("Respuesta tardía", send.await_args.args[1])

    def test_voice_completion_does_not_send_or_add_note_in_api(self):
        answer = "Respuesta canónica."
        document = {
            "id": "job-1",
            "chat_id": "chat-1",
            "created_at": "2020-01-01T09:00:00+00:00",
            "answer": answer,
            "status": "completed",
            "response_mode": "voice",
        }
        with patch.object(main, "require_sync_secret"), patch.object(
            main, "complete_ai_job", return_value=document
        ), patch.object(main, "send_telegram_message", new_callable=AsyncMock) as send:
            asyncio.run(
                main.complete_ai_job_endpoint(
                    "job-1",
                    {"status": "completed", "answer": answer, "notify_telegram": False,
                     "response_mode": "voice"},
                )
            )
        send.assert_not_awaited()

    def test_completed_answer_plus_note_stays_under_telegram_text_limit(self):
        answer = "A" * 3500
        document = {
            "id": "job-1",
            "chat_id": "chat-1",
            "created_at": "2020-01-01T09:00:00+00:00",
            "answer": answer,
            "status": "completed",
        }
        payload_answer = answer + "EXTRA MUST BE TRUNCATED"
        with patch.object(main, "require_sync_secret"), patch.object(
            main, "complete_ai_job", return_value=document
        ) as save, patch.object(
            main, "send_telegram_message", new_callable=AsyncMock
        ) as send:
            asyncio.run(
                main.complete_ai_job_endpoint(
                    "job-1", {"status": "completed", "answer": payload_answer}
                )
            )
        canonical = save.call_args.kwargs["answer"]
        delivered = send.await_args.args[1]
        self.assertEqual(len(canonical), 3500)
        self.assertNotIn("EXTRA MUST BE TRUNCATED", canonical)
        self.assertLessEqual(len(delivered), 4096)
        self.assertIn("Respuesta tardía", delivered)
        self.assertTrue(delivered.endswith(canonical))

    def test_send_telegram_message_sends_near_limit_text_in_one_request(self):
        sent = []

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json):
                sent.append((url, json))
                return SimpleNamespace(status_code=200)

        long_text = "x" * 4090
        client = FakeAsyncClient()
        with patch.object(main, "settings", SimpleNamespace(telegram_bot_token="test-token")), patch.object(
            main.httpx, "AsyncClient", return_value=client
        ):
            asyncio.run(main.send_telegram_message("chat-1", long_text))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]["text"], long_text)


class CompletionTimestampBackendTests(unittest.TestCase):
    def test_json_backend_returns_iso_created_at_string_through_completion(self):
        from app import store

        with tempfile.TemporaryDirectory() as directory, patch.object(
            store, "DATABASE_URL", None
        ), patch.object(
            store, "AI_JOBS_FILE", Path(directory) / "jobs.json"
        ), patch.object(store, "load_active_training_plan", return_value=None):
            job = store.create_ai_job("chat-json", "pregunta")
            completed = store.complete_ai_job(job["id"], answer="respuesta")

        self.assertIsInstance(completed["created_at"], str)
        parsed = datetime.fromisoformat(completed["created_at"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertIsNotNone(parsed.utcoffset())
        self.assertIn("respuesta", format_late_delivery(
            completed["answer"], completed["created_at"], now=datetime.now(timezone.utc)
        ))

    @unittest.skipUnless(os.getenv("P03_TEST_DATABASE_URL"), "isolated PostgreSQL required")
    def test_postgres_backend_returns_json_timestamp_string_not_column_datetime(self):
        import psycopg
        from app import store

        url = os.environ["P03_TEST_DATABASE_URL"]
        schema = "f4_2a_" + uuid.uuid4().hex
        conn = psycopg.connect(url, autocommit=True)
        self.addCleanup(conn.close)
        conn.execute("CREATE SCHEMA " + schema)
        self.addCleanup(lambda: conn.execute("DROP SCHEMA " + schema + " CASCADE"))
        conn.execute("SET search_path TO " + schema)
        store.ensure_schema(conn)
        database_url = url + "?options=-csearch_path%3D" + schema

        with patch.object(store, "DATABASE_URL", database_url), patch.object(
            store, "load_active_training_plan", return_value=None
        ):
            job = store.create_ai_job("chat-postgres", "pregunta")
            completed = store.complete_ai_job(job["id"], answer="respuesta")

        self.assertIsInstance(completed["created_at"], str)
        parsed = datetime.fromisoformat(completed["created_at"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertIsNotNone(parsed.utcoffset())
        column_type = conn.execute(
            "SELECT pg_typeof(created_at)::text FROM coach_ai_jobs WHERE id = %s",
            (job["id"],),
        ).fetchone()[0]
        self.assertEqual(column_type, "timestamp with time zone")
        delivered = format_late_delivery(
            completed["answer"], completed["created_at"], now=datetime.now(timezone.utc)
        )
        self.assertIn("respuesta", delivered)
