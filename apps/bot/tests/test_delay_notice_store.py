"""Atomic delay-notice store integration tests for isolated PostgreSQL."""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.getenv("P03_TEST_DATABASE_URL"), "isolated PostgreSQL required")
class DelayNoticeStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        cls.psycopg = psycopg
        cls.base_url = os.environ["P03_TEST_DATABASE_URL"]
        cls.migration_sql = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261012_add_delay_notice_columns.sql"
        ).read_text(encoding="utf-8")

    def setUp(self):
        from psycopg import sql
        from app import store

        self.schema = "delay_notice_" + uuid.uuid4().hex
        with self.psycopg.connect(self.base_url, autocommit=True) as conn:
            conn.execute(sql.SQL("create schema {}").format(sql.Identifier(self.schema)))
            conn.execute(sql.SQL("set search_path to {}").format(sql.Identifier(self.schema)))
            conn.execute(
                """create table coach_ai_jobs (
                       id text primary key,
                       status text not null,
                       document jsonb not null,
                       created_at timestamptz not null default now(),
                       updated_at timestamptz not null default now()
                   )"""
            )
            conn.execute(self.migration_sql)

        self.database_url = self.base_url + "?options=-csearch_path%3D" + self.schema
        self.enterContext(patch.object(store, "DATABASE_URL", self.database_url))
        self.store = store
        self.addCleanup(self.drop_schema)

    def drop_schema(self):
        from psycopg import sql

        with self.psycopg.connect(self.base_url, autocommit=True) as conn:
            conn.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(self.schema)))

    def add_job(
        self,
        job_id,
        *,
        status="pending",
        seconds_ago=600,
        source_kind="text",
        chat_id="test-chat",
        include_chat=True,
    ):
        from psycopg.types.json import Jsonb

        document = {"id": job_id, "status": status, "source_kind": source_kind}
        if include_chat:
            document["chat_id"] = chat_id
        with self.psycopg.connect(self.database_url) as conn:
            conn.execute(
                """insert into coach_ai_jobs (id,status,document,created_at)
                   values (%s,%s,%s,now() - make_interval(secs => %s))""",
                (job_id, status, Jsonb(document), seconds_ago),
            )

    def marks(self, job_id):
        with self.psycopg.connect(self.database_url) as conn:
            return conn.execute(
                """select delay_notified_at, delay_notice_claimed_at,
                          delay_notice_claim_token, delay_notice_attempts
                   from coach_ai_jobs where id = %s""",
                (job_id,),
            ).fetchone()

    def test_delay_notice_database_connection_sets_finite_query_deadlines(self):
        with self.store._connect_delay_notice_postgres() as conn:
            statement_timeout = conn.execute("show statement_timeout").fetchone()[0]
            lock_timeout = conn.execute("show lock_timeout").fetchone()[0]

        self.assertEqual(statement_timeout, "10s")
        self.assertEqual(lock_timeout, "5s")

    def test_load_sync_can_use_bounded_postgres_connection(self):
        with self.psycopg.connect(self.database_url) as conn:
            conn.execute("create table sync_state (key text primary key, document jsonb not null)")
            conn.execute("insert into sync_state (key,document) values ('latest','{}')")
        with patch.object(self.store, "DATABASE_URL", self.database_url):
            self.assertEqual(self.store.load_sync(delay_notice_timeout=True), {})

    def test_claims_one_oldest_job_at_threshold_and_excludes_other_kinds(self):
        self.add_job("eligible-older", seconds_ago=121)
        self.add_job("eligible-boundary", seconds_ago=120)
        self.add_job("too-young", seconds_ago=119)
        self.add_job("completed", status="completed", seconds_ago=500)
        self.add_job("failed", status="failed", seconds_ago=500)
        self.add_job("lab-test", source_kind="lab_test", seconds_ago=500)
        self.add_job("missing-chat", include_chat=False, seconds_ago=500)

        claimed = self.store.claim_next_delay_notice_job(threshold_seconds=120)

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["job_id"], "eligible-older")
        self.assertEqual(claimed["chat_id"], "test-chat")
        self.assertEqual(claimed["source_kind"], "text")
        self.assertIsInstance(claimed["created_at"], datetime)
        self.assertIsInstance(claimed["claimed_at"], datetime)
        self.assertTrue(claimed["claim_token"])
        self.assertEqual(self.marks("eligible-older")[3], 1)
        boundary_claim = self.store.claim_next_delay_notice_job(threshold_seconds=120)
        self.assertIsNotNone(boundary_claim)
        self.assertEqual(boundary_claim["job_id"], "eligible-boundary")
        self.assertEqual(self.marks("eligible-boundary")[3], 1)
        self.assertIsNone(self.store.claim_next_delay_notice_job(threshold_seconds=120))

    def test_claim_uses_database_time_and_retries_expired_lease_at_most_three_times(self):
        self.add_job("retry-me")
        claims = []
        for expected_attempt in (1, 2, 3):
            claim = self.store.claim_next_delay_notice_job(threshold_seconds=120)
            self.assertIsNotNone(claim)
            claims.append(claim)
            self.assertEqual(self.marks("retry-me")[3], expected_attempt)
            if expected_attempt < 3:
                with self.psycopg.connect(self.database_url) as conn:
                    conn.execute(
                        "update coach_ai_jobs set delay_notice_claimed_at = now() - interval '120 seconds' where id = %s",
                        ("retry-me",),
                    )

        self.assertEqual(len({claim["claim_token"] for claim in claims}), 3)
        self.assertIsNone(self.store.claim_next_delay_notice_job(threshold_seconds=120))
        self.assertEqual(self.marks("retry-me")[3], 3)

    def test_prepare_requires_current_token_open_job_and_fifteen_seconds_remaining(self):
        self.add_job("prepare-me")
        claim = self.store.claim_next_delay_notice_job(threshold_seconds=120)
        self.assertIsNotNone(claim)

        self.assertIsNone(
            self.store.prepare_delay_notice_send("prepare-me", "not-the-owner")
        )
        prepared = self.store.prepare_delay_notice_send("prepare-me", claim["claim_token"])
        self.assertIsNotNone(prepared)
        self.assertEqual(prepared["job_id"], "prepare-me")

        with self.psycopg.connect(self.database_url) as conn:
            conn.execute(
                "update coach_ai_jobs set delay_notice_claimed_at = now() - interval '106 seconds' where id = %s",
                ("prepare-me",),
            )
        self.assertIsNone(
            self.store.prepare_delay_notice_send("prepare-me", claim["claim_token"])
        )
        self.assertEqual(self.marks("prepare-me")[3], 1)

    def test_mark_requires_owner_and_still_open_job(self):
        self.add_job("mark-me")
        claim = self.store.claim_next_delay_notice_job(threshold_seconds=120)
        self.assertIsNotNone(claim)

        self.assertFalse(self.store.mark_delay_notice_sent("mark-me", "stale-token"))
        self.assertTrue(self.store.mark_delay_notice_sent("mark-me", claim["claim_token"]))
        marks = self.marks("mark-me")
        self.assertIsNotNone(marks[0])
        self.assertIsNone(marks[1])
        self.assertIsNone(marks[2])
        self.assertEqual(marks[3], 1)
        self.assertFalse(self.store.mark_delay_notice_sent("mark-me", claim["claim_token"]))

    def test_completion_after_claim_prevents_prepare_and_confirmation(self):
        self.add_job("race-me")
        claim = self.store.claim_next_delay_notice_job(threshold_seconds=120)
        self.assertIsNotNone(claim)
        with self.psycopg.connect(self.database_url) as conn:
            conn.execute("update coach_ai_jobs set status='completed' where id='race-me'")

        self.assertIsNone(
            self.store.prepare_delay_notice_send("race-me", claim["claim_token"])
        )
        self.assertFalse(self.store.mark_delay_notice_sent("race-me", claim["claim_token"]))
        self.assertIsNone(self.marks("race-me")[0])

    def test_concurrent_sweep_claims_never_duplicate_a_job(self):
        self.add_job("concurrent-once")

        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(
                pool.map(
                    lambda _: self.store.claim_next_delay_notice_job(threshold_seconds=120),
                    range(8),
                )
            )

        winners = [claim for claim in claims if claim is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["job_id"], "concurrent-once")
        self.assertEqual(self.marks("concurrent-once")[3], 1)

    def test_invalid_threshold_is_rejected_and_file_backend_does_not_claim(self):
        for threshold in (0, -1):
            with self.assertRaises(ValueError):
                self.store.claim_next_delay_notice_job(threshold_seconds=threshold)

        with patch.object(self.store, "DATABASE_URL", None):
            with self.assertRaises(RuntimeError):
                self.store.claim_next_delay_notice_job(threshold_seconds=120)


if __name__ == "__main__":
    unittest.main()
