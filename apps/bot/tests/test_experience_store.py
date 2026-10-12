import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from app import store

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def rows():
    return [
        {'chat_id': 'a', 'status': 'pending', 'created_at': '2026-10-10T10:00:00Z'},
        {'chat_id': 'a', 'status': 'pending', 'created_at': '2026-10-11T10:00:00+02:00'},
        {'chat_id': 'a', 'status': 'running', 'claimed_at': '2026-10-11T10:00:00+00:00'},
        {'chat_id': 'a', 'status': 'completed', 'completed_at': '2026-10-11T09:00:00Z'},
        {'chat_id': 'a', 'status': 'failed', 'completed_at': '2026-10-11T08:00:00Z'},
        {'chat_id': 'a', 'status': 'failed', 'completed_at': '2026-02-31T08:00:00Z'},
        {'chat_id': 'a', 'status': 'failed', 'completed_at': '2026-10-11T08:00:00'},
        {'chat_id': 'a', 'status': 'failed', 'completed_at': '2027-10-11T08:00:00Z'},
        {'chat_id': 'b', 'status': 'pending', 'created_at': '2020-01-01T00:00:00Z', 'text': 'PRIVATE'},
    ]


class QueueFileTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = root / 'jobs.json'
        self.enterContext(patch.object(store, 'DATABASE_URL', None))
        self.enterContext(patch.object(store, 'AI_JOBS_FILE', self.path))

    def test_aggregates_dates_and_never_writes(self):
        self.path.write_text(json.dumps(rows()))
        before = self.path.read_bytes()
        result = store.load_queue_snapshot('a', now=NOW)
        self.assertEqual(result['counts'], {'pending': 2, 'running': 1, 'completed': 1, 'failed': 4, 'unknown': 0})
        self.assertEqual(result['oldest_pending_at'], '2026-10-10T10:00:00+00:00')
        self.assertEqual(result['last_completed_at'], '2026-10-11T09:00:00+00:00')
        self.assertEqual(result['invalid_date_counts']['last_failed_at'], 3)
        self.assertNotIn('PRIVATE', str(result))
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_empty_invalid_and_no_chat(self):
        self.assertTrue(store.load_queue_snapshot('a', now=NOW)['available'])
        for raw in ('not json', '{}'):
            self.path.write_text(raw)
            self.assertFalse(store.load_queue_snapshot('a', now=NOW)['available'])
        self.assertFalse(store.load_queue_snapshot('', now=NOW)['available'])

    def test_file_writers_preserve_aware_utc(self):
        root = self.path.parent
        for name, value in vars(store).copy().items():
            if isinstance(value, Path) and (name.endswith('_FILE') or name == 'DATA_DIR'):
                self.enterContext(patch.object(store, name, root if name == 'DATA_DIR' else root/value.name))
        job = store.create_ai_job('writer', 'question')
        claimed = store.claim_next_ai_job()
        done = store.complete_ai_job(job['id'], answer='done')
        for row, key in [(job, 'created_at'), (claimed, 'claimed_at'), (done, 'completed_at')]:
            self.assertEqual(datetime.fromisoformat(row[key]).utcoffset().total_seconds(), 0)

    def test_calendar_offset_validation(self):
        values = ['2024-02-29T00:00:00Z', '2025-02-29T00:00:00Z', '2026-01-01T24:00:00Z',
                  '2026-01-01T00:00:00+14:01', '0000-01-01T00:00:00Z', '2026-01-01T00:00:60Z']
        self.path.write_text(json.dumps([{'chat_id': 'a', 'status': 'failed', 'completed_at': v} for v in values]))
        self.assertEqual(store.load_queue_snapshot('a', now=NOW)['invalid_date_counts']['last_failed_at'], 5)


@unittest.skipUnless(os.getenv('P03_TEST_DATABASE_URL'), 'isolated PostgreSQL required')
class QueuePostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.url = os.environ['P03_TEST_DATABASE_URL']
        self.schema = 'f4_' + uuid.uuid4().hex
        self.conn = psycopg.connect(self.url, autocommit=True)
        self.addCleanup(self.conn.close)
        self.conn.execute('CREATE SCHEMA ' + self.schema)
        self.addCleanup(lambda: self.conn.execute('DROP SCHEMA ' + self.schema + ' CASCADE'))
        self.conn.execute('SET search_path TO ' + self.schema)
        store.ensure_schema(self.conn)
        self.enterContext(patch.object(store, 'DATABASE_URL', self.url + '?options=-csearch_path%3D' + self.schema))

    def test_aggregate_matches_files_at_scale_and_is_read_only(self):
        from psycopg.types.json import Jsonb
        data = rows()
        data += [{'chat_id': 'a', 'status': 'completed', 'completed_at': '2026-01-01T00:00:00Z'} for _ in range(10000)]
        with self.conn.cursor() as cur:
            cur.executemany('INSERT INTO coach_ai_jobs (id,status,document,created_at) VALUES (%s,%s,%s,%s)',
                [(str(i), r['status'], Jsonb(r), r.get('created_at', '2026-01-01T00:00:00Z')) for i,r in enumerate(data)])
        result = store.load_queue_snapshot('a', now=NOW)
        self.assertEqual(result['counts']['completed'], 10001)
        self.assertEqual(result['counts']['pending'], 2)
        self.assertEqual(result['invalid_date_counts']['last_failed_at'], 3)
        self.assertEqual(result['last_completed_at'], '2026-10-11T09:00:00+00:00')
        self.assertNotIn('jobs', result)
        with tempfile.TemporaryDirectory() as root, patch.object(store, 'DATABASE_URL', None), patch.object(store, 'AI_JOBS_FILE', Path(root)/'jobs.json'):
            store.AI_JOBS_FILE.write_text(json.dumps(data))
            self.assertEqual(result, store.load_queue_snapshot('a', now=NOW))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM coach_ai_jobs').fetchone()[0], 10009)

    def test_absent_table_does_not_create_it(self):
        self.conn.execute('DROP TABLE coach_ai_jobs CASCADE')
        self.assertFalse(store.load_queue_snapshot('a', now=NOW)['available'])
        self.assertIsNone(self.conn.execute("SELECT to_regclass('coach_ai_jobs')").fetchone()[0])

    def test_operational_documents_are_read_without_schema_initialization(self):
        from psycopg.types.json import Jsonb
        for key in ('latest','sync_request'):
            self.conn.execute('INSERT INTO sync_state(key,document) VALUES (%s,%s)', (key,Jsonb({'status':'pending'})))
        with patch.object(store,'ensure_schema',side_effect=AssertionError('DDL')):
            self.assertEqual(store.load_operational_documents(), ({'status':'pending'},{'status':'pending'}))

    def test_writers_use_aware_utc_and_snapshot_is_read_only(self):
        from datetime import datetime
        job=store.create_ai_job('writer','question')
        claimed=store.claim_next_ai_job()
        done=store.complete_ai_job(job['id'],answer='done')
        for row,key in [(job,'created_at'),(claimed,'claimed_at'),(done,'completed_at')]:
            self.assertEqual(datetime.fromisoformat(row[key]).utcoffset().total_seconds(),0)
        before=self.conn.execute('SELECT document FROM coach_ai_jobs').fetchall()
        store.load_queue_snapshot('writer',now=datetime.now(timezone.utc))
        self.assertEqual(before,self.conn.execute('SELECT document FROM coach_ai_jobs').fetchall())

    def test_bad_calendar_shapes_do_not_break_sql(self):
        from psycopg.types.json import Jsonb
        values=['bad','2026-02-31T00:00:00Z','2025-02-29T00:00:00Z','2026-01-01T24:00:00Z',
                '2026-01-01T00:00:00+14:01','0000-01-01T00:00:00Z','2026-01-01T00:00:60Z',
                '2026-01-01T00:00:00.500000Z','2026-01-01T00:00:00Z']
        for i,value in enumerate(values):
            self.conn.execute('INSERT INTO coach_ai_jobs(id,status,document) VALUES (%s,%s,%s)',(str(i),'completed',Jsonb({'chat_id':'a','completed_at':value})))
        q=store.load_queue_snapshot('a',now=NOW)
        self.assertEqual(q['invalid_date_counts']['last_completed_at'],7)
        self.assertEqual(q['last_completed_at'],'2026-01-01T00:00:00.500000+00:00')
