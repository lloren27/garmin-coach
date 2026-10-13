import asyncio
import os
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import delay_notices, main, store


class DelayNoticeConfigTests(unittest.TestCase):
    def test_parser_distinguishes_valid_disabled_and_invalid_values(self):
        for raw in (None, "", "  ", "0", " 0 "):
            with self.subTest(raw=raw):
                self.assertIsNone(delay_notices.parse_delay_notice_seconds(raw))
                self.assertTrue(delay_notices.is_delay_notice_disabled(raw))

        for raw in ("-1", "1.5", "abc", "604801", "00"):
            with self.subTest(raw=raw):
                self.assertIsNone(delay_notices.parse_delay_notice_seconds(raw))
                self.assertFalse(delay_notices.is_delay_notice_disabled(raw))

        self.assertEqual(delay_notices.parse_delay_notice_seconds("1"), 1)
        self.assertEqual(delay_notices.parse_delay_notice_seconds("604800"), 604800)


class DelayNoticeLifespanTests(unittest.TestCase):
    def app_settings(self, threshold, *, token="test-token", allowed="allowed"):
        return SimpleNamespace(
            coach_delay_notice_seconds=threshold,
            telegram_bot_token=token,
            telegram_allowed_user_id=allowed,
            sync_secret=None,
            public_base_url=None,
        )

    def test_disabled_and_invalid_config_keep_api_up_without_schema_probe(self):
        for raw, should_log in ((None, False), ("0", False), ("wrong", True)):
            with self.subTest(raw=raw):
                with patch.object(main, "settings", self.app_settings(raw)), patch.object(
                    main.store, "DATABASE_URL", "postgresql://local/test"
                ), patch.object(
                    main, "missing_delay_notice_columns", side_effect=AssertionError("probe")
                ), patch.object(
                    delay_notices, "run_delay_notice_sweep_once", side_effect=AssertionError("sweep")
                ):
                    if should_log:
                        with self.assertLogs(main.logger, level="ERROR") as logs:
                            with TestClient(main.app) as client:
                                self.assertEqual(client.get("/health").status_code, 200)
                        self.assertTrue(any("Invalid COACH_DELAY_NOTICE_SECONDS" in line for line in logs.output))
                    else:
                        with self.assertNoLogs(main.logger, level="ERROR"):
                            with TestClient(main.app) as client:
                                self.assertEqual(client.get("/health").status_code, 200)

    def test_json_backend_and_missing_schema_do_not_start_sweeper(self):
        with patch.object(main, "settings", self.app_settings("120")), patch.object(
            main.store, "DATABASE_URL", None
        ), patch.object(
            main, "missing_delay_notice_columns", side_effect=AssertionError("probe")
        ), patch.object(
            delay_notices, "run_delay_notice_sweep_once", side_effect=AssertionError("sweep")
        ):
            with TestClient(main.app) as client:
                self.assertEqual(client.get("/health").status_code, 200)

        with patch.object(main, "settings", self.app_settings("120")), patch.object(
            main.store, "DATABASE_URL", "postgresql://local/test"
        ), patch.object(
            main, "missing_delay_notice_columns", return_value=("delay_notice_attempts",)
        ), patch.object(
            delay_notices, "run_delay_notice_sweep_once", side_effect=AssertionError("sweep")
        ):
            with self.assertLogs(main.logger, level="ERROR") as logs:
                with TestClient(main.app) as client:
                    self.assertEqual(client.get("/health").status_code, 200)
            self.assertTrue(any("delay_notice_attempts" in line for line in logs.output))

        with patch.object(main, "settings", self.app_settings("120")), patch.object(
            main.store, "DATABASE_URL", "postgresql://local/test"
        ), patch.object(
            main, "missing_delay_notice_columns", side_effect=OSError("synthetic database outage")
        ), patch.object(
            delay_notices, "run_delay_notice_sweep_once", side_effect=AssertionError("sweep")
        ):
            with self.assertLogs(main.logger, level="ERROR"):
                with TestClient(main.app) as client:
                    self.assertEqual(client.get("/health").status_code, 200)

    def test_shutdown_signals_thread_and_webhook_remains_responsive(self):
        started = threading.Event()
        finished = threading.Event()
        stop_events = []

        def blocking_sweep(stop_event):
            stop_events.append(stop_event)
            started.set()
            stop_event.wait()
            finished.set()
            return 0

        with patch.object(main, "settings", self.app_settings("120")), patch.object(
            main.store, "DATABASE_URL", "postgresql://local/test"
        ), patch.object(main, "missing_delay_notice_columns", return_value=()), patch.object(
            delay_notices, "run_delay_notice_sweep_once", side_effect=blocking_sweep
        ), patch.object(main, "create_ai_job", return_value={"id": "synthetic"}), patch.object(
            main, "send_telegram_message", new_callable=AsyncMock
        ) as send:
            with TestClient(main.app) as client:
                self.assertTrue(started.wait(2))
                response = client.post(
                    "/telegram/webhook",
                    json={
                        "message": {
                            "text": "/help",
                            "chat": {"id": 12},
                            "from": {"id": "allowed"},
                        }
                    },
                )
                self.assertEqual(response.status_code, 200)
                send.assert_awaited_once()
                self.assertEqual(len(stop_events), 1)

        self.assertTrue(finished.wait(2))
        self.assertTrue(stop_events[0].is_set())


class DelayNoticeSweepTests(unittest.TestCase):
    def settings(self, threshold="120", token="test-token"):
        return SimpleNamespace(
            coach_delay_notice_seconds=threshold,
            telegram_bot_token=token,
        )

    def claim(self, job_id):
        from datetime import datetime, timezone

        return {
            "job_id": job_id,
            "chat_id": "synthetic-chat",
            "source_kind": "text",
            "created_at": datetime.now(timezone.utc),
            "claimed_at": datetime.now(timezone.utc),
            "claim_token": f"token-{job_id}",
            "factual_scope": "today",
        }

    def test_stop_signal_is_checked_before_each_claim(self):
        stop = threading.Event()
        claim_calls = []
        sent = []

        def claim_next(*, threshold_seconds):
            claim_calls.append(threshold_seconds)
            return self.claim(f"job-{len(claim_calls)}")

        def send(chat_id, text):
            sent.append(text)
            stop.set()
            return True

        with patch.object(delay_notices, "settings", self.settings()), patch.object(
            store, "DATABASE_URL", "postgresql://local/test"
        ), patch.object(store, "claim_next_delay_notice_job", side_effect=claim_next), patch.object(
            store, "prepare_delay_notice_send", side_effect=lambda job_id, token: self.claim(job_id)
        ), patch.object(store, "load_sync", return_value=None), patch.object(
            delay_notices, "format_delay_notice", return_value="synthetic notice"
        ), patch.object(delay_notices, "send_delay_notice", side_effect=send), patch.object(
            store, "mark_delay_notice_sent", return_value=True
        ) as mark:
            result = delay_notices.run_delay_notice_sweep_once(stop)

        self.assertEqual(result, 1)
        self.assertEqual(claim_calls, [120])
        self.assertEqual(len(sent), 1)
        mark.assert_called_once()

    def test_sweep_passes_persisted_scope_to_delay_notice_formatter(self):
        claim = {**self.claim("scoped-job"), "factual_scope": "today"}
        with patch.object(delay_notices, "settings", self.settings()), patch.object(
            store, "DATABASE_URL", "postgresql://local/test"
        ), patch.object(store, "claim_next_delay_notice_job", side_effect=[claim, None]), patch.object(
            store, "prepare_delay_notice_send", return_value=claim
        ), patch.object(store, "load_sync", return_value={}), patch.object(
            delay_notices, "format_delay_notice", return_value="notice"
        ) as format_notice, patch.object(
            delay_notices, "send_delay_notice", return_value=True
        ), patch.object(store, "mark_delay_notice_sent", return_value=True):
            self.assertEqual(delay_notices.run_delay_notice_sweep_once(), 1)
        self.assertEqual(format_notice.call_args.args[0]["factual_scope"], "today")

    def test_large_slow_batch_claims_and_finishes_one_job_at_a_time(self):
        events = []
        next_job = 0
        in_flight = False
        sent_count = 0
        virtual_elapsed = 0

        def claim_next(*, threshold_seconds):
            nonlocal next_job, in_flight
            self.assertFalse(in_flight, "a previous message must finish before another claim")
            if next_job >= 21:
                return None
            next_job += 1
            in_flight = True
            events.append(("claim", next_job))
            return self.claim(f"job-{next_job}")

        def send(_chat_id, _text):
            nonlocal in_flight, sent_count, virtual_elapsed
            events.append(("send-start", next_job))
            # Virtual clock: model Telegram taking its full 15-second allowance.
            virtual_elapsed += 15
            sent_count += 1
            in_flight = False
            events.append(("send-end", next_job))
            return True

        def mark(_job_id, _token):
            events.append(("confirm", next_job))
            return True

        with patch.object(delay_notices, "settings", self.settings()), patch.object(
            store, "DATABASE_URL", "postgresql://local/test"
        ), patch.object(store, "claim_next_delay_notice_job", side_effect=claim_next), patch.object(
            store, "prepare_delay_notice_send", side_effect=lambda job_id, token: self.claim(job_id)
        ), patch.object(store, "load_sync", return_value=None), patch.object(
            delay_notices, "format_delay_notice", return_value="synthetic notice"
        ), patch.object(delay_notices, "send_delay_notice", side_effect=send), patch.object(
            store, "mark_delay_notice_sent", side_effect=mark
        ):
            result = delay_notices.run_delay_notice_sweep_once()

        self.assertEqual(result, 20)
        self.assertEqual(next_job, 20)
        self.assertEqual(sent_count, 20)
        self.assertEqual(virtual_elapsed, 300)
        self.assertFalse(in_flight)
        self.assertEqual(
            [event[0] for event in events],
            ["claim", "send-start", "send-end", "confirm"] * 20,
        )

    def test_accepted_message_without_persisted_confirmation_is_not_retried_in_cycle(self):
        claimed = []
        sent = []

        def claim_next(*, threshold_seconds):
            if claimed:
                return None
            claimed.append("job-once")
            return self.claim("job-once")

        with patch.object(delay_notices, "settings", self.settings()), patch.object(
            store, "DATABASE_URL", "postgresql://local/test"
        ), patch.object(store, "claim_next_delay_notice_job", side_effect=claim_next), patch.object(
            store, "prepare_delay_notice_send", side_effect=lambda job_id, token: self.claim(job_id)
        ), patch.object(store, "load_sync", return_value=None), patch.object(
            delay_notices, "format_delay_notice", return_value="synthetic notice"
        ), patch.object(
            delay_notices, "send_delay_notice", side_effect=lambda *args: sent.append(args) or True
        ), patch.object(store, "mark_delay_notice_sent", return_value=False) as mark:
            result = delay_notices.run_delay_notice_sweep_once()

        self.assertEqual(result, 0)
        self.assertEqual(claimed, ["job-once"])
        self.assertEqual(len(sent), 1)
        mark.assert_called_once()

    def test_disabled_or_file_backend_never_claims(self):
        for settings, database_url in (
            (self.settings("0"), "postgresql://local/test"),
            (self.settings("120"), None),
            (self.settings("invalid"), "postgresql://local/test"),
            (self.settings("120", token=None), "postgresql://local/test"),
        ):
            with self.subTest(settings=settings, database_url=database_url), patch.object(
                delay_notices, "settings", settings
            ), patch.object(store, "DATABASE_URL", database_url), patch.object(
                store, "claim_next_delay_notice_job", side_effect=AssertionError("claim")
            ):
                self.assertEqual(delay_notices.run_delay_notice_sweep_once(), 0)


class DelayNoticeTransportTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch.object(delay_notices, "settings", SimpleNamespace(telegram_bot_token="fake-token"))
        )

    def send_with_handler(self, handler, *, timeout=1.0):
        actual_client = httpx.AsyncClient
        transport = httpx.MockTransport(handler)
        with patch.object(
            delay_notices.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: actual_client(transport=transport, **kwargs),
        ):
            return delay_notices.send_delay_notice(
                "123", "synthetic notice", total_timeout_seconds=timeout
            )

    def test_only_2xx_json_ok_true_confirms_delivery(self):
        self.assertTrue(
            self.send_with_handler(
                lambda _request: httpx.Response(200, json={"ok": True})
            )
        )
        self.assertFalse(
            self.send_with_handler(
                lambda _request: httpx.Response(200, json={"ok": False})
            )
        )
        self.assertFalse(
            self.send_with_handler(
                lambda _request: httpx.Response(429, json={"ok": False})
            )
        )

    def test_gently_dripping_response_is_cancelled_by_total_deadline(self):
        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                await asyncio.sleep(0.04)
                yield b'{"ok":'
                await asyncio.sleep(0.04)
                yield b'true}'

        started = time.monotonic()
        sent = self.send_with_handler(
            lambda _request: httpx.Response(200, stream=SlowBody()), timeout=0.06
        )
        elapsed = time.monotonic() - started
        self.assertFalse(sent)
        self.assertLess(elapsed, 0.2)

    def test_network_error_is_not_retried_internally(self):
        calls = []

        def fail(request):
            calls.append(request)
            raise httpx.ConnectError("synthetic network failure", request=request)

        self.assertFalse(self.send_with_handler(fail))
        self.assertEqual(len(calls), 1)

    def test_missing_token_does_not_make_a_request(self):
        with patch.object(delay_notices, "settings", SimpleNamespace(telegram_bot_token=None)), patch.object(
            delay_notices.httpx, "AsyncClient", side_effect=AssertionError("request")
        ):
            self.assertFalse(delay_notices.send_delay_notice("123", "synthetic notice"))


@unittest.skipUnless(os.getenv("P03_TEST_DATABASE_URL"), "isolated PostgreSQL required")
class DelayNoticeSchemaProbeTests(unittest.TestCase):
    def test_probe_reports_missing_columns_without_reading_job_values(self):
        import psycopg
        from psycopg import sql
        from pathlib import Path

        schema = "notice_probe_" + uuid.uuid4().hex
        base_url = os.environ["P03_TEST_DATABASE_URL"]
        try:
            with psycopg.connect(base_url, autocommit=True) as conn:
                conn.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
                conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(schema)))
                conn.execute(
                    "create table coach_ai_jobs (id text, status text, document jsonb, created_at timestamptz)"
                )
                probe_url = base_url + "?options=-csearch_path%3D" + schema
                with patch.object(store, "DATABASE_URL", probe_url):
                    self.assertEqual(
                        delay_notices.missing_delay_notice_columns(),
                        delay_notices.DELAY_NOTICE_COLUMNS,
                    )
                    migration = (
                        Path(__file__).resolve().parents[1]
                        / "migrations"
                        / "20261012_add_delay_notice_columns.sql"
                    ).read_text(encoding="utf-8")
                    conn.execute(migration)
                    self.assertEqual(delay_notices.missing_delay_notice_columns(), ())
        finally:
            with psycopg.connect(base_url, autocommit=True) as conn:
                conn.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))


@unittest.skipUnless(os.getenv("P03_TEST_DATABASE_URL"), "isolated PostgreSQL required")
class ConcurrentDelayNoticeSweepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        cls.psycopg = psycopg
        cls.base_url = os.environ["P03_TEST_DATABASE_URL"]

    def test_two_sweeps_accept_each_notice_once_across_multiple_jobs(self):
        from pathlib import Path
        from psycopg import sql
        from psycopg.types.json import Jsonb

        schema = "concurrent_notice_" + uuid.uuid4().hex
        database_url = self.base_url + "?options=-csearch_path%3D" + schema
        accepted = []
        accepted_lock = threading.Lock()
        barrier = threading.Barrier(2)
        try:
            with self.psycopg.connect(self.base_url, autocommit=True) as conn:
                conn.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
                conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(schema)))
                conn.execute(
                    """create table coach_ai_jobs (
                           id text primary key, status text not null, document jsonb not null,
                           created_at timestamptz not null, updated_at timestamptz not null default now()
                       )"""
                )
                migration = (
                    Path(__file__).resolve().parents[1]
                    / "migrations"
                    / "20261012_add_delay_notice_columns.sql"
                ).read_text(encoding="utf-8")
                conn.execute(migration)
                for index in range(3):
                    job_id = f"parallel-{index}"
                    conn.execute(
                        """insert into coach_ai_jobs (id,status,document,created_at)
                           values (%s,'pending',%s,now()-interval '10 minutes')""",
                        (
                            job_id,
                            Jsonb({
                                "id": job_id,
                                "status": "pending",
                                "chat_id": f"chat-{job_id}",
                                "source_kind": "text",
                            }),
                        ),
                    )

            def send(chat_id, _text):
                with accepted_lock:
                    accepted.append(chat_id)
                return True

            def run_sweep():
                barrier.wait(timeout=2)
                return delay_notices.run_delay_notice_sweep_once()

            with patch.object(delay_notices, "settings", SimpleNamespace(
                coach_delay_notice_seconds="120", telegram_bot_token="fake-token"
            )), patch.object(store, "DATABASE_URL", database_url), patch.object(
                store, "load_sync", return_value=None
            ), patch.object(delay_notices, "format_delay_notice", return_value="notice"), patch.object(
                delay_notices, "send_delay_notice", side_effect=send
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: run_sweep(), range(2)))

            self.assertEqual(sum(results), 3)
            self.assertEqual(sorted(accepted), ["chat-parallel-0", "chat-parallel-1", "chat-parallel-2"])
            self.assertEqual(len(set(accepted)), 3)
            with self.psycopg.connect(database_url) as conn:
                state = conn.execute(
                    """select count(*), count(*) filter (where delay_notice_attempts=1),
                              count(*) filter (where delay_notified_at is not null)
                       from coach_ai_jobs"""
                ).fetchone()
            self.assertEqual(state, (3, 3, 3))
        finally:
            with self.psycopg.connect(self.base_url, autocommit=True) as conn:
                conn.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))

    def test_shutdown_finishes_when_claim_is_blocked_by_database_lock(self):
        from pathlib import Path
        from psycopg import sql

        schema = "shutdown_notice_" + uuid.uuid4().hex
        database_url = self.base_url + "?options=-csearch_path%3D" + schema
        started = threading.Event()
        finished = threading.Event()
        stop_event = threading.Event()
        outcomes = []
        lock_conn = None
        try:
            with self.psycopg.connect(self.base_url, autocommit=True) as conn:
                conn.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
                conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(schema)))
                conn.execute(
                    """create table coach_ai_jobs (
                           id text primary key, status text not null, document jsonb not null,
                           created_at timestamptz not null default now(), updated_at timestamptz not null default now()
                       )"""
                )
                migration = (
                    Path(__file__).resolve().parents[1]
                    / "migrations"
                    / "20261012_add_delay_notice_columns.sql"
                ).read_text(encoding="utf-8")
                conn.execute(migration)

            lock_conn = self.psycopg.connect(database_url)
            lock_conn.execute("lock table coach_ai_jobs in access exclusive mode")
            original_claim = store.claim_next_delay_notice_job

            def tracked_claim(**kwargs):
                started.set()
                return original_claim(**kwargs)

            def run_sweep():
                with patch.object(delay_notices, "settings", SimpleNamespace(
                    coach_delay_notice_seconds="120", telegram_bot_token="fake-token"
                )), patch.object(store, "DATABASE_URL", database_url), patch.object(
                    store, "claim_next_delay_notice_job", side_effect=tracked_claim
                ):
                    outcomes.append(delay_notices.run_delay_notice_sweep_once(stop_event))
                finished.set()

            thread = threading.Thread(target=run_sweep, daemon=True)
            thread.start()
            self.assertTrue(started.wait(2), "sweep did not start its blocked claim")
            stop_event.set()
            self.assertTrue(
                finished.wait(7),
                "sweep did not stop after PostgreSQL lock timeout",
            )
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcomes, [0])
        finally:
            if lock_conn is not None:
                lock_conn.rollback()
                lock_conn.close()
            with self.psycopg.connect(self.base_url, autocommit=True) as conn:
                conn.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))


if __name__ == "__main__":
    unittest.main()
