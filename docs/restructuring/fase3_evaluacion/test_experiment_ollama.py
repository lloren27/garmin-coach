import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx

import experiment as ex
import experiment_ollama as ollama


class OllamaTests(unittest.TestCase):
    def handler(self, request):
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name':'garmin-coach:9b','digest':'abc123'}]})
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'parameters':'temperature 0.2', 'template':'template', 'system':'system', 'model_info':{}})
        payload = json.loads(request.content)
        self.calls.append(payload)
        self.assertEqual(payload['options']['temperature'], 0)
        self.assertEqual(payload['options']['num_predict'], 900)
        self.assertEqual(payload['model'], 'garmin-coach:9b')
        self.assertFalse(payload['stream'])
        self.assertEqual(request.extensions['timeout']['read'], 600)
        self.assertTrue((self.output / 'baseline.json').exists())
        self.assertTrue((self.output / 'manifest.json').exists())
        return httpx.Response(200, json={'message': {'content':self.reply}})

    def setup_transport(self, tmp, reply='not json'):
        self.output = Path(tmp) / 'run'
        self.reply = reply; self.calls = []
        original = httpx.Client
        return patch.object(ollama, 'client', side_effect=lambda **kw: original(transport=httpx.MockTransport(self.handler), **kw))

    def test_one_call_each_and_invalid_is_not_repaired(self):
        with tempfile.TemporaryDirectory() as tmp, self.setup_transport(tmp):
            result = ex.run_experiment(ex.DEFAULT, self.output, 'http://localhost:11434')
            self.assertEqual(len(self.calls), 15)
            self.assertEqual(result['status'], 'generated')
            rows = json.loads((self.output / 'results.json').read_text())
            self.assertEqual(len(rows), 15)
            self.assertTrue(all(r['model']['status'] == 'invalid_selection' for r in rows))
            self.assertTrue(all(r['model']['answer'] is None for r in rows))
            logs = (self.output / 'events.jsonl').read_text()
            self.assertNotIn('not json', logs)
            self.assertNotIn('¿qué tal', logs)
            with self.assertRaises(FileExistsError):
                ex.run_experiment(ex.DEFAULT, self.output, 'http://localhost:11434')
            self.assertEqual(len(self.calls), 15)

    def test_timeout_is_not_evaluated_and_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp, self.setup_transport(tmp):
            original = self.handler
            def timeout(request):
                if request.url.path == '/api/chat':
                    self.calls.append(1)
                    raise httpx.ReadTimeout('secret raw question', request=request)
                return original(request)
            self.handler = timeout
            ex.run_experiment(ex.DEFAULT, self.output, 'http://localhost:11434')
            rows = json.loads((self.output / 'results.json').read_text())
            self.assertEqual(len(self.calls), 15)
            self.assertTrue(all(r['model']['status'] == 'no_evaluado' for r in rows))
            self.assertNotIn('secret raw', (self.output / 'events.jsonl').read_text())

    def test_digest_drift_stops_before_next_generation(self):
        with tempfile.TemporaryDirectory() as tmp, self.setup_transport(tmp):
            original = self.handler
            def drift(request):
                if request.url.path == '/api/tags' and self.calls:
                    return httpx.Response(200, json={'models':[{'name':'garmin-coach:9b','digest':'changed'}]})
                return original(request)
            self.handler = drift
            result = ex.run_experiment(ex.DEFAULT, self.output, 'http://localhost:11434')
            self.assertEqual(result['status'], 'aborted')
            self.assertEqual(len(self.calls), 1)
            self.assertTrue((self.output / 'case-E01-pace.json').exists())

    def test_interruption_keeps_started_case_without_retry(self):
        with tempfile.TemporaryDirectory() as tmp, self.setup_transport(tmp):
            original = self.handler
            def interrupt(request):
                if request.url.path == '/api/chat':
                    raise KeyboardInterrupt()
                return original(request)
            self.handler = interrupt
            with self.assertRaises(KeyboardInterrupt):
                ex.run_experiment(ex.DEFAULT, self.output, 'http://localhost:11434')
            row = json.loads((self.output / 'case-E01-pace.json').read_text())
            self.assertEqual(row['model']['status'], 'started')
            with self.assertRaises(FileExistsError):
                ex.run_experiment(ex.DEFAULT, self.output, 'http://localhost:11434')

    def test_mixed_payload_has_all_components_and_explicit_followup_rules(self):
        c = next(c for c in ex.prepare_cases() if c['id'] == 'E10-mixto')
        payload = ollama.make_payload(c)
        context = json.loads(payload['messages'][1]['content'])
        self.assertEqual(len(context['components']), 2)
        self.assertEqual(context['question'], c['question'])
        self.assertIn('CLARIFY_SYMPTOM_CONTEXT', payload['messages'][0]['content'])
        self.assertNotIn('expected_checks', payload['messages'][1]['content'])

if __name__ == '__main__':
    unittest.main()
