"""
Local Typing Insights.
Stores strictly aggregate counters (words evaluated, corrections applied,
reversals triggered, estimated keystrokes saved).
Never records individual words, sentences, or timestamps of typing activity.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TypingInsightsSummary:
    """Privacy-preserving aggregate typing statistics."""

    words_evaluated: int
    spelling_corrections: int
    contextual_corrections: int
    punctuation_and_caps_fixes: int
    snippets_expanded: int
    corrections_undone: int
    keystrokes_saved: int


class LocalInsightsStore:
    """In-memory / local aggregate counter store with opt-in toggle and reset."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._words_evaluated = 0
        self._spelling_corrections = 0
        self._contextual_corrections = 0
        self._punctuation_and_caps = 0
        self._snippets_expanded = 0
        self._corrections_undone = 0
        self._keystrokes_saved = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def record_word_evaluated(self) -> None:
        if self._enabled:
            self._words_evaluated += 1

    def record_spelling_correction(self, chars_saved: int = 1) -> None:
        if self._enabled:
            self._spelling_corrections += 1
            self._keystrokes_saved += max(1, chars_saved)

    def record_contextual_correction(self) -> None:
        if self._enabled:
            self._contextual_corrections += 1
            self._keystrokes_saved += 2

    def record_punctuation_or_caps(self) -> None:
        if self._enabled:
            self._punctuation_and_caps += 1
            self._keystrokes_saved += 1

    def record_snippet_expansion(self, trigger_len: int, expanded_len: int) -> None:
        if self._enabled:
            self._snippets_expanded += 1
            self._keystrokes_saved += max(0, expanded_len - trigger_len)

    def record_undo(self) -> None:
        if self._enabled:
            self._corrections_undone += 1

    def get_summary(self) -> TypingInsightsSummary:
        return TypingInsightsSummary(
            words_evaluated=self._words_evaluated,
            spelling_corrections=self._spelling_corrections,
            contextual_corrections=self._contextual_corrections,
            punctuation_and_caps_fixes=self._punctuation_and_caps,
            snippets_expanded=self._snippets_expanded,
            corrections_undone=self._corrections_undone,
            keystrokes_saved=self._keystrokes_saved,
        )

    def reset(self) -> None:
        self._words_evaluated = 0
        self._spelling_corrections = 0
        self._contextual_corrections = 0
        self._punctuation_and_caps = 0
        self._snippets_expanded = 0
        self._corrections_undone = 0
        self._keystrokes_saved = 0
