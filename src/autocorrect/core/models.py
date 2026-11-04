"""
Domain models for the OS-agnostic Core Autocorrection Engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from autocorrect.intelligence.schema import RegionFlag


class CorrectionReason(str, Enum):
    """Reason a correction decision was made or suppressed."""

    NONE = "NONE"
    GUARD_EXCLUDED = "GUARD_EXCLUDED"
    USER_REJECTED = "USER_REJECTED"
    VALID_IN_VOCAB = "VALID_IN_VOCAB"
    DIRECT_TYPO = "DIRECT_TYPO"
    CONTRACTION_RESTORED = "CONTRACTION_RESTORED"
    SPELLING_OOV = "SPELLING_OOV"
    CONTEXTUAL_CONFUSION = "CONTEXTUAL_CONFUSION"
    GRAMMAR_AGREEMENT = "GRAMMAR_AGREEMENT"
    SENTENCE_CAPITALISATION = "SENTENCE_CAPITALISATION"
    PRONOUN_CAPITALISATION = "PRONOUN_CAPITALISATION"
    EXACT_BRAND_CASING = "EXACT_BRAND_CASING"
    PUNCTUATION_SPACING = "PUNCTUATION_SPACING"
    DOUBLE_SPACE_PERIOD = "DOUBLE_SPACE_PERIOD"
    SNIPPET_EXPANSION = "SNIPPET_EXPANSION"
    INSUFFICIENT_CONFIDENCE = "INSUFFICIENT_CONFIDENCE"


@dataclass(frozen=True, slots=True)
class CorrectionCandidate:
    """A scored candidate replacement for an input token."""

    word: str
    word_id: int
    edit_distance: int
    weighted_error_cost: float
    lm_log_prob: float
    confusion_boost: float
    composite_score: float
    is_direct_typo: bool = False


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Recent typing context passed to the core engine on word completion."""

    prev1_word: str | None = None
    prev2_word: str | None = None
    prev1_word_id: int | None = None
    prev2_word_id: int | None = None
    clause_tokens: tuple[str, ...] = ()
    is_sentence_start: bool = False
    leading_prefix: str = ""  # e.g. '--', '/', '@', '#', opening quote
    trailing_delimiter: str = " "  # e.g. ' ', '.', ',', '?', '!', '\n'
    active_region: RegionFlag = RegionFlag.EN_GB
    is_code_or_terminal_app: bool = False
    enable_punctuation_assist: bool = True
    enable_auto_capitalise: bool = True
    aggressiveness: float = 1.0  # 1.0 = standard conservative; <1.0 stricter; >1.0 more assertive


@dataclass(frozen=True, slots=True)
class CorrectionDecision:
    """Final decision returned by the Core Engine for a completed token."""

    original_token: str
    replacement_token: str
    original_delimiter: str
    replacement_delimiter: str
    should_replace: bool
    reason: CorrectionReason
    confidence: float
    margin: float
    candidates: tuple[CorrectionCandidate, ...] = field(default_factory=tuple)

    @property
    def full_original(self) -> str:
        return f"{self.original_token}{self.original_delimiter}"

    @property
    def full_replacement(self) -> str:
        return f"{self.replacement_token}{self.replacement_delimiter}"
