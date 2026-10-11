import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import main, experience
from app.queue_status import empty_snapshot

NOW = datetime(2026,10,11,12,tzinfo=timezone.utc)

class StatusTests(unittest.TestCase):
    def test_factual_state_and_privacy(self):
        queue = empty_snapshot(True)
        queue['counts'].update(pending=2, running=1)
        queue.update(oldest_pending_at='2026-10-11T10:00:00+00:00', last_completed_at='2026-10-10T10:00:00+00:00', last_failed_at='2026-10-11T11:00:00+00:00')
        sync = {'received_at':'2026-10-11T12:00:00Z', 'payload': {'generated_at':'2026-10-10T10:00:00Z',
            'activity_provider_status': {'strava': {'status':'network_error', 'last_success_at':'2026-10-09T10:00:00Z', 'last_error':'SECRET'}},
            'wellness': {'provider_status':{'zepp':{'status':'ok','records_received':0}}}}}
        result = experience.format_operational_status(sync, {'status':'pending','last_error':'SECRET'}, queue, now=NOW)
        for word in ('Pendientes: 2', 'En ejecución: 1', '120 min', 'Strava', 'error del proveedor', 'sin datos', '10/10/2026 12:00', '11/10/2026 14:00'):
            self.assertIn(word, result)
        self.assertNotIn('SECRET',result)
        self.assertLess(len(result),4096)

    def test_unavailable_is_not_empty_and_bad_dates_stay_unknown(self):
        result = experience.format_operational_status(None,None,empty_snapshot(),now=NOW)
        self.assertIn('Cola no disponible',result)
        self.assertNotIn('Pendientes: 0',result)
        q=empty_snapshot(True)
        q['oldest_pending_at']='2027-01-01T00:00:00Z'
        q['invalid_date_counts']['oldest_pending_at']=1
        self.assertIn('no fiable',experience.format_operational_status(None,None,q,now=NOW))

    def test_dst_age_is_elapsed_utc_time(self):
        q=empty_snapshot(True)
        q['counts']['pending']=1
        q['oldest_pending_at']='2026-10-25T00:30:00+00:00'
        result=experience.format_operational_status(None,None,q,now=datetime(2026,10,25,1,30,tzinfo=timezone.utc))
        self.assertIn('60 min',result)

    def test_webhook_auth_and_missing_chat_before_reads(self):
        with patch.object(main,'settings',SimpleNamespace(telegram_allowed_user_id='allowed',telegram_bot_token=None)), patch.object(main,'load_operational_documents',side_effect=AssertionError('read')), patch.object(main,'load_queue_snapshot',side_effect=AssertionError('read')):
            with TestClient(main.app) as client:
                for message in ({'from':{'id':'other'},'chat':{'id':-10},'text':'/estado'}, {'from':{'id':'allowed'},'text':'/estado'}):
                    self.assertEqual(client.post('/telegram/webhook',json={'message':message}).status_code,200)

    def test_route_uses_group_chat_and_never_user_fallback(self):
        with patch.object(main,'load_operational_documents',return_value=(None,None)), patch.object(main,'load_profile',side_effect=AssertionError('profile')), patch.object(main,'load_queue_snapshot',return_value=empty_snapshot(True)) as load:
            main.route_message('/estado','u','-10')
            self.assertEqual(load.call_args.args[0],'-10')
            load.reset_mock()
            self.assertIn('Cola no disponible',main.route_message('/estado','u',None))
            load.assert_not_called()
            self.assertEqual(main.route_message('/estado extra','u','-10'),'Uso: /estado')
