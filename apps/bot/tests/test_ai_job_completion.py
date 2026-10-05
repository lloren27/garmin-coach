from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import main


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
