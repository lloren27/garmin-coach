"""Shared wire contracts live in the deployable backend package (no I/O)."""
from pathlib import Path
import sys

_bot = str(Path(__file__).resolve().parents[2] / 'bot')
if _bot not in sys.path:
    sys.path.insert(0, _bot)

from app.ai_contracts import (  # noqa: E402,F401
    CoachDecision, CoachEvidence, CoachStructuredResponse, DecisionAction,
    DecisionSource, Intensity, ResponseType, Sport, ChangeOperation,
    ProposedValues, SessionChange, StructuredChangeProposal,
)
