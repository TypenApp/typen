"""
OS-Agnostic Core Autocorrection Engine.
Provides Layer 1 statistical spelling, contextual confusion-set resolution,
intelligent punctuation assistance, and automatic sentence capitalisation.
"""

from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import (
    CorrectionCandidate,
    CorrectionDecision,
    CorrectionReason,
    EvaluationContext,
)

__all__ = [
    "AutocorrectEngine",
    "CorrectionCandidate",
    "CorrectionDecision",
    "CorrectionReason",
    "EvaluationContext",
]
