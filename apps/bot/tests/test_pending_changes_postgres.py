"""Run only against an explicit disposable database: P03_TEST_DATABASE_URL."""
import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo
import uuid

from app import store
from app.proposal_repository import PostgresProposalRepository
from test_pending_changes import response


@unittest.skipUnless(os.getenv('P03_TEST_DATABASE_URL'), 'requires isolated P03_TEST_DATABASE_URL')
class PostgresProposalTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.url = os.environ['P03_TEST_DATABASE_URL']
        self.enterContext(patch.object(store, 'DATABASE_URL', self.url))
        self.owner = 'p03-test-' + str(uuid.uuid4())
        day = (datetime.now(ZoneInfo('Europe/Madrid')).date() + timedelta(days=1)).isoformat()
        self.plan = store.save_training_plan({'start_date': day, 'end_date': day,
            'sessions': [{'date': day, 'sport': 'running', 'session_type': 'easy_run',
                          'intensity': 'easy', 'duration_min': 45, 'duration_max': 55}]}, self.owner)
        self.job = store.create_ai_job(self.owner, '/ajustar mañana')
        store.prepare_proposal_context(self.job, {'training_plan'})
        self.payload = response(self.plan['sessions'][0]['id'])

    def complete(self):
        return store.complete_ai_job(self.job['id'], structured_output=self.payload,
                                     output_source='ollama', answer=self.payload['answer'])

    def sessions(self):
        with self.psycopg.connect(self.url) as conn:
            return conn.execute('select to_jsonb(s) from planned_sessions s where owner_id = %s', (self.owner,)).fetchall()

    def test_concurrent_retries_have_one_row_and_sessions_are_unchanged(self):
        before = self.sessions()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.complete(), range(8)))
        self.assertEqual(len({r['pending_change']['id'] for r in results}), 1)
        self.assertEqual(results[0]['pending_change']['status'], 'PENDING')
        self.assertEqual(self.sessions(), before)
        with self.psycopg.connect(self.url) as conn:
            count = conn.execute('select count(*) from pending_changes where source_job_id = %s', (self.job['id'],)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_transaction_rolls_back_insert_if_completion_fails(self):
        original = PostgresProposalRepository.insert
        def fail_after_insert(repository, document):
            original(repository, document)
            raise RuntimeError('crash after insert')
        with patch.object(PostgresProposalRepository, 'insert', fail_after_insert):
            with self.assertRaisesRegex(RuntimeError, 'crash'):
                self.complete()
        with self.psycopg.connect(self.url) as conn:
            self.assertIsNone(PostgresProposalRepository(conn).find(self.job['id']))
            status = conn.execute('select status from coach_ai_jobs where id = %s', (self.job['id'],)).fetchone()[0]
            self.assertEqual(status, 'pending')
        self.assertEqual(self.complete()['pending_change']['status'], 'PENDING')

    def test_stale_plan_is_invalid_and_schema_is_repeatable(self):
        with self.psycopg.connect(self.url) as conn:
            store.ensure_schema(conn)
            store.ensure_schema(conn)
            conn.execute('update training_plans set revision = revision + 1 where id = %s', (self.plan['id'],))
        before = self.sessions()
        self.assertEqual(store.load_active_training_plan(self.owner)['revision'], 2)
        proposal = self.complete()['pending_change']
        self.assertEqual(proposal['base_plan_revision'], 1)
        self.assertEqual(proposal['status'], 'INVALID')
        self.assertEqual(self.sessions(), before)

    def test_database_constraints_enforce_job_uniqueness_and_plan_reference(self):
        saved = self.complete()['pending_change']
        duplicate = {**saved, 'id': str(uuid.uuid4())}
        with self.assertRaises(self.psycopg.errors.UniqueViolation):
            with self.psycopg.connect(self.url) as conn:
                PostgresProposalRepository(conn).insert(duplicate)
        another_job = store.create_ai_job(self.owner, '/ajustar')
        invalid = {**duplicate, 'source_job_id': another_job['id'], 'training_plan_id': 'missing'}
        with self.assertRaises(self.psycopg.errors.ForeignKeyViolation):
            with self.psycopg.connect(self.url) as conn:
                PostgresProposalRepository(conn).insert(invalid)

    def test_migration_upgrades_old_rows_and_is_repeatable(self):
        from psycopg import sql
        schema = 'p03_migration_' + uuid.uuid4().hex
        with self.psycopg.connect(self.url) as conn:
            conn.execute(sql.SQL('create schema {}').format(sql.Identifier(schema)))
            conn.execute(sql.SQL('set local search_path to {}').format(sql.Identifier(schema)))
            store.ensure_schema(conn)
            # Reconstruct pre-P0.3 in this transaction-only namespace.
            conn.execute('drop table pending_changes')
            conn.execute('alter table training_plans drop column revision')
            conn.execute("""insert into training_plans
                (id, owner_id, status, start_date, end_date, document)
                values ('old-plan', 'owner', 'active', '2026-01-01', '2026-01-07', '{}')""")
            store.ensure_schema(conn)
            store.ensure_schema(conn)
            self.assertEqual(conn.execute("select revision from training_plans where id='old-plan'").fetchone()[0], 1)
            self.assertIsNotNone(conn.execute("select to_regclass('pending_changes')").fetchone()[0])
            conn.rollback()  # Entire test namespace is disposable and never committed.
