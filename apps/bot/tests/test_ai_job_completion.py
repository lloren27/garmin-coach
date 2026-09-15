from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import main


class AiJobCompletionTests(unittest.TestCase):
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
