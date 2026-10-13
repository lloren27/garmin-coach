"""Integration tests for the additive delay-notice migration.

Run only against the explicit disposable database in P03_TEST_DATABASE_URL.
"""
import os
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.getenv("P03_TEST_DATABASE_URL"), "isolated PostgreSQL required")
class DelayNoticeMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        cls.psycopg = psycopg
        cls.database_url = os.environ["P03_TEST_DATABASE_URL"]
        cls.migration_path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20261012_add_delay_notice_columns.sql"
        )

    def snapshot(self, conn):
        jobs = conn.execute(
            """select id, status, created_at, md5(document::text)
               from coach_ai_jobs order by id"""
        ).fetchall()
        pending_changes = conn.execute(
            """select id, source_job_id, status, md5(document::text)
               from pending_changes order by id"""
        ).fetchall()
        return jobs, pending_changes

    def apply_migration(self, conn):
        conn.execute(self.migration_path.read_text(encoding="utf-8"))

    def reset_synthetic_job(self):
        with self.psycopg.connect(self.database_url) as conn:
            conn.execute(
                """update coach_ai_jobs
                   set status = 'pending',
                       document = jsonb_build_object(
                           'id', 'synthetic-f4-2b-pending',
                           'chat_id', 'synthetic-f4-2b',
                           'status', 'pending',
                           'created_at', created_at::text
                       ),
                       delay_notified_at = null,
                       delay_notice_claimed_at = null,
                       delay_notice_claim_token = null,
                       delay_notice_attempts = null,
                       updated_at = now()
                   where id = 'synthetic-f4-2b-pending'"""
            )

    def test_migration_is_additive_idempotent_and_preserves_existing_rows(self):
        with self.psycopg.connect(self.database_url) as conn:
            before = self.snapshot(conn)
            job_count = conn.execute("select count(*) from coach_ai_jobs").fetchone()[0]
            pending_change_count = conn.execute("select count(*) from pending_changes").fetchone()[0]
            synthetic = conn.execute(
                "select id, status from coach_ai_jobs where id = %s",
                ("synthetic-f4-2b-pending",),
            ).fetchone()
            self.assertEqual(synthetic, ("synthetic-f4-2b-pending", "pending"))

            self.apply_migration(conn)
            self.apply_migration(conn)

            columns = conn.execute(
                """select column_name, data_type
                   from information_schema.columns
                   where table_schema = current_schema()
                     and table_name = 'coach_ai_jobs'
                     and column_name in (
                       'delay_notified_at', 'delay_notice_claimed_at',
                       'delay_notice_claim_token', 'delay_notice_attempts'
                     )
                   order by column_name"""
            ).fetchall()
            self.assertEqual(
                columns,
                [
                    ("delay_notice_attempts", "integer"),
                    ("delay_notice_claim_token", "text"),
                    ("delay_notice_claimed_at", "timestamp with time zone"),
                    ("delay_notified_at", "timestamp with time zone"),
                ],
            )
            constraint = conn.execute(
                """select pg_get_constraintdef(oid)
                   from pg_constraint
                   where conrelid = 'coach_ai_jobs'::regclass
                     and conname = 'coach_ai_jobs_delay_notice_attempts_nonnegative'"""
            ).fetchone()
            self.assertIsNotNone(constraint)
            self.assertIn("delay_notice_attempts", constraint[0])
            self.assertIn(">= 0", constraint[0])
            self.assertEqual(self.snapshot(conn), before)
            self.assertEqual(conn.execute("select count(*) from coach_ai_jobs").fetchone()[0], job_count)
            self.assertEqual(
                conn.execute("select count(*) from pending_changes").fetchone()[0],
                pending_change_count,
            )
            self.assertEqual(
                conn.execute(
                    """select count(*) from coach_ai_jobs
                       where delay_notified_at is not null
                          or delay_notice_claimed_at is not null
                          or delay_notice_claim_token is not null
                          or delay_notice_attempts is not null"""
                ).fetchone()[0],
                0,
            )

            with self.assertRaises(self.psycopg.errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        "update coach_ai_jobs set delay_notice_attempts = -1 where id = %s",
                        ("synthetic-f4-2b-pending",),
                    )

    def test_existing_claim_and_completion_writers_preserve_notice_columns(self):
        from datetime import datetime, timezone

        from app import store

        self.addCleanup(self.reset_synthetic_job)
        with patch.object(store, "DATABASE_URL", self.database_url):
            with self.psycopg.connect(self.database_url) as conn:
                self.apply_migration(conn)
                store.ensure_schema(conn)
                conn.execute(
                    """update coach_ai_jobs
                       set delay_notice_claimed_at = %s,
                           delay_notice_claim_token = 'synthetic-claim-token',
                           delay_notice_attempts = 2
                       where id = %s""",
                    (datetime.now(timezone.utc), "synthetic-f4-2b-pending"),
                )

            claimed = store.claim_next_ai_job_postgres()
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed["id"], "synthetic-f4-2b-pending")
            self.assertFalse(any(key.startswith("delay_notice") for key in claimed))
            with self.psycopg.connect(self.database_url) as conn:
                marks = conn.execute(
                    """select delay_notice_claim_token, delay_notice_attempts,
                              delay_notice_claimed_at, delay_notified_at
                       from coach_ai_jobs where id = %s""",
                    ("synthetic-f4-2b-pending",),
                ).fetchone()
                self.assertEqual(marks[0:2], ("synthetic-claim-token", 2))
                self.assertIsNotNone(marks[2])
                self.assertIsNone(marks[3])

            queue_view = store.load_queue_snapshot(
                "synthetic-f4-2b", now=datetime.now(timezone.utc)
            )
            self.assertTrue(queue_view["available"])
            self.assertNotIn("jobs", queue_view)
            with self.psycopg.connect(self.database_url) as conn:
                self.assertEqual(
                    conn.execute(
                        """select delay_notice_claim_token, delay_notice_attempts,
                                  delay_notice_claimed_at, delay_notified_at
                           from coach_ai_jobs where id = %s""",
                        ("synthetic-f4-2b-pending",),
                    ).fetchone(),
                    marks,
                )

            completed = store.complete_ai_job_postgres(
                "synthetic-f4-2b-pending", "completed", "synthetic answer", None
            )
            self.assertEqual(completed["status"], "completed")
            self.assertFalse(any(key.startswith("delay_notice") for key in completed))
            with self.psycopg.connect(self.database_url) as conn:
                marks_after = conn.execute(
                    """select delay_notice_claim_token, delay_notice_attempts,
                              delay_notice_claimed_at, delay_notified_at
                       from coach_ai_jobs where id = %s""",
                    ("synthetic-f4-2b-pending",),
                ).fetchone()
            self.assertEqual(marks_after, marks)


if __name__ == "__main__":
    unittest.main()
