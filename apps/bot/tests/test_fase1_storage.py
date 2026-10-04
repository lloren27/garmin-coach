import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main, store


class PhaseOneStorageTests(unittest.TestCase):
    def test_version_only_exposes_valid_commit(self):
        with patch.dict(os.environ, {'RAILWAY_GIT_COMMIT_SHA': 'a' * 40}):
            self.assertEqual(main.version()['commit'], 'a' * 40)
        with patch.dict(os.environ, {'RAILWAY_GIT_COMMIT_SHA': 'not-a-commit'}):
            self.assertIsNone(main.version()['commit'])

    def check_roundtrip(self):
        stamp = '2026-10-03T12:00:00+02:00'
        payload = {'generated_at': stamp, 'summary': {'activities': [
            {'id': 'strava:123', 'source': 'strava', 'source_activity_id': '123',
             'source_records': [{'source': 'strava', 'source_activity_id': '123', 'source_device': 'CMF'}]}]},
            'activity_provider_status': {'strava': {'status': 'ok', 'last_success_at': stamp}}}
        original = copy.deepcopy(payload)
        first = store.save_sync(payload)
        self.assertEqual(store.load_sync()['payload'], original)
        failed = copy.deepcopy(payload)
        failed['activity_provider_status']['strava'] = {'status': 'network_error', 'last_attempt_at': '2026-10-04T12:00:00+02:00'}
        store.save_sync(failed)
        self.assertEqual(store.load_sync()['payload']['activity_provider_status']['strava']['last_success_at'], stamp)
        self.assertNotIn('last_success_at', failed['activity_provider_status']['strava'])
        self.assertEqual(payload, original)
        self.assertTrue(any(row == first for row in store.load_sync_history(10)))

    def test_json_roundtrip_keeps_origins_history_and_success(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'DATABASE_URL', None):
            for name in ('DATA_DIR', 'SYNC_FILE', 'SYNC_HISTORY_FILE', 'WELLNESS_HISTORY_FILE'):
                path = Path(tmp) if name == 'DATA_DIR' else Path(tmp) / name
                self.enterContext(patch.object(store, name, path))
            self.check_roundtrip()

    @unittest.skipUnless(os.getenv('P03_TEST_DATABASE_URL'), 'requires isolated P03_TEST_DATABASE_URL')
    def test_postgres_roundtrip_keeps_origins_history_and_success(self):
        with patch.object(store, 'DATABASE_URL', os.environ['P03_TEST_DATABASE_URL']):
            self.check_roundtrip()
