"""Phase 3 file/PostgreSQL authorization and local-alias acceptance."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

from app import main, store, pending_changes

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = json.loads((ROOT/'docs/restructuring/fase3_evaluacion/v1/fixtures.json').read_text())['base_fixtures']


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        now = datetime.fromisoformat('2026-10-03T22:00:00+02:00')
        return now.astimezone(tz) if tz else now.replace(tzinfo=None)


class Phase3ClosureTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for module in (store, pending_changes):
            self.enterContext(patch.object(module, 'datetime', FrozenDatetime))
        self.enterContext(patch.object(store, 'DATABASE_URL', None))
        for key, value in list(vars(store).items()):
            if isinstance(value, Path) and (key.endswith('_FILE') or key == 'DATA_DIR'):
                self.enterContext(patch.object(store, key, root if key == 'DATA_DIR' else root/value.name))

    def check_authorization(self):
        for name in ('E15a', 'E15b'):
            row = FIXTURES[name]['estado_inicial']
            owner = 'fase3-'+uuid.uuid4().hex
            day = row['plan']['date']
            plan = store.save_training_plan({'start_date':day,'end_date':day,'sessions':[row['plan']]},owner)
            job = store.create_ai_job(owner, '/ajustar mañana' if row['explicit'] else '¿Cómo estoy recuperando?')
            store.prepare_proposal_context(job, {'training_plan'})
            payload = {'response_type':'analysis','answer':'Propuesta pendiente de aprobación.',
                'change_proposal':{'reason':'Solicitud explícita','confidence':0.8,'evidence':[],
                'changes':[{'operation':'ADJUST_DURATION','session_id':plan['sessions'][0]['id'],
                    'proposed_values':{'duration_min':30,'duration_max':40},'reason':'Reducir duración'}]}}
            before = copy.deepcopy(store.load_active_training_plan(owner))
            if row['explicit']:
                result = store.complete_ai_job(job['id'], structured_output=payload, output_source='ollama',answer=payload['answer'])
                self.assertEqual(result['pending_change']['status'], 'PENDING')
            else:
                with self.assertRaisesRegex(ValueError, 'not authorized'):
                    store.complete_ai_job(job['id'], structured_output=payload, output_source='ollama',answer=payload['answer'])
                payload.pop('change_proposal')
                result = store.complete_ai_job(job['id'], structured_output=payload,output_source='ollama',answer=payload['answer'])
                self.assertEqual(result['status'],'completed')
                self.assertFalse(result.get('pending_change'))
                if store.DATABASE_URL:
                    import psycopg
                    with psycopg.connect(store.DATABASE_URL) as conn:
                        self.assertEqual(conn.execute('select count(*) from pending_changes where source_job_id=%s',(job['id'],)).fetchone()[0],0)
                else:
                    proposal_path = store.DATA_DIR/'pending_changes.json'
                    self.assertFalse(proposal_path.exists())
            self.assertEqual(store.load_active_training_plan(owner), before)

    def test_e15_files(self):
        self.check_authorization()

    @unittest.skipUnless(os.getenv('P03_TEST_DATABASE_URL'), 'isolated PostgreSQL required')
    def test_e15_postgres(self):
        with patch.object(store,'DATABASE_URL',os.environ['P03_TEST_DATABASE_URL']):
            self.check_authorization()

    def test_e14_real_aliases_remain_local_for_all_flags(self):
        for name in ('load_sync','load_profile','load_wattwise','load_strength_state'):
            self.enterContext(patch.object(main,name,return_value={}))
        self.enterContext(patch.object(main,'load_checkins',return_value=[]))
        with patch.object(main,'create_ai_job',side_effect=AssertionError('worker unavailable')):
            for v3 in ('off','on'):
                for enforcement in ('off','on'):
                    with patch.dict(os.environ,{'COACH_ANALYSIS_V3_ENABLED':v3,'COACH_INTENT_ENFORCEMENT':enforcement}):
                        for command in ('/feedback','/semana','/proximo'):
                            self.assertTrue(main.route_message(command,'fase3','fase3'))


if __name__ == '__main__': unittest.main()
