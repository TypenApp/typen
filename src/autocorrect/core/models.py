"""
Domain models for the OS-agnostic Core Autocorrection Engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from enum import Enum
from typing import Any

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
class CorrectionFeatures:
    """
    Every user-tunable correction behaviour, as one immutable bundle. Built
    from the settings store (`from_settings`), optionally overridden per
    application (`with_overrides`), and consulted by the session and the engine
    at each stage. Field names are the setting keys.
    """

    # Spelling
    enable_spelling: bool = True
    aggressiveness: float = 1.0  # 1.0 = standard conservative; <1.0 stricter; >1.0 more assertive
    min_correction_length: int = 4
    correct_all_caps: bool = False
    correct_titlecase_midsentence: bool = False
    # Capitalisation
    enable_auto_capitalise: bool = True
    cap_sentence: bool = True
    cap_pronoun_i: bool = True
    cap_after_newline: bool = True
    cap_brands: bool = True
    cap_double_initial: bool = True
    # Punctuation
    enable_punctuation_assist: bool = True
    enable_double_space_period: bool = True
    double_space_interval_ms: int = 2000
    enable_auto_space_after_sentence: bool = True
    enable_space_before_punct: bool = True
    enable_contractions: bool = True
    enable_missing_space: bool = True
    smart_quotes: bool = False
    # Context
    enable_confusion_sets: bool = True
    enable_grammar: bool = True
    enable_retroactive: bool = True
    # Undo
    undo_enabled: bool = True
    undo_window_ms: int = 2000
    undo_remembers: str = "session"  # never | session | always
    # Ignore rules (dictionary group, but they gate the engine)
    ignore_words_with_digits: bool = True
    ignore_acronyms: bool = True
    ignore_symbol_words: bool = True
    ignore_mentions: bool = True
    ignore_longer_than: int = 24
    # Language
    variant_enforcement: str = "prefer"  # off | prefer | strict
    uk_ize_spelling: bool = False

    # Derived conveniences ------------------------------------------------
    @property
    def capitalise_sentences(self) -> bool:
        return self.enable_auto_capitalise and self.cap_sentence

    @property
    def capitalise_pronoun_i(self) -> bool:
        return self.enable_auto_capitalise and self.cap_pronoun_i

    @property
    def fix_brand_casing(self) -> bool:
        return self.enable_auto_capitalise and self.cap_brands

    @property
    def fix_double_initial(self) -> bool:
        return self.enable_auto_capitalise and self.cap_double_initial

    @property
    def restore_contractions(self) -> bool:
        return self.enable_punctuation_assist and self.enable_contractions

    @property
    def double_space_period(self) -> bool:
        return self.enable_punctuation_assist and self.enable_double_space_period

    @property
    def auto_space(self) -> bool:
        return self.enable_punctuation_assist and self.enable_auto_space_after_sentence

    @property
    def space_before_punct(self) -> bool:
        return self.enable_punctuation_assist and self.enable_space_before_punct

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> CorrectionFeatures:
        """Build from a settings mapping; unknown keys are ignored, missing ones keep defaults."""
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in names})

    def with_overrides(self, overrides: Mapping[str, Any]) -> CorrectionFeatures:
        names = {f.name for f in fields(self)}
        return replace(self, **{k: v for k, v in overrides.items() if k in names and v is not None})

    def as_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


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
    # Full feature set; the three legacy flags above are kept in sync by `with_features`.
    features: CorrectionFeatures = CorrectionFeatures()

    @classmethod
    def with_features(cls, features: CorrectionFeatures, **kwargs: Any) -> EvaluationContext:
        kwargs.setdefault("enable_punctuation_assist", features.enable_punctuation_assist)
        kwargs.setdefault("enable_auto_capitalise", features.enable_auto_capitalise)
        kwargs.setdefault("aggressiveness", features.aggressiveness)
        return cls(features=features, **kwargs)


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
