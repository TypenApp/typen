"""
Bounded Correction Transaction Ledger (Depth = 1).
Supports deliberate Double-Backspace reversal of any correction (spelling,
punctuation, sentence capitalisation, or snippet expansion). The first
Backspace is an ordinary edit (it deletes the trailing delimiter); only the
second consecutive Backspace restores the user's original token.

A reversal registers only a ONE-SHOT suppression: if the user immediately
re-completes that same restored token (e.g. presses Space on it), it is not
fought once. A later, fresh instance of the same misspelling is corrected
normally - a reverted word is never treated as correct for the session.
Only an explicit custom-dictionary entry makes a word permanently accepted.
"""

from __future__ import annotations

from dataclasses import dataclass

from autocorrect.core.models import CorrectionReason
from autocorrect.input.diff_planner import ReplacementPlan, SuffixDiffPlanner


@dataclass(slots=True)
class ActiveTransaction:
    """Single bounded undo record for the most recent automatic modification."""

    original_token: str
    corrected_token: str
    delimiter: str
    reason: CorrectionReason
    timestamp_ms: float
    post_chars_typed: int = 0
    backspaces_seen: int = 0
    first_backspace_ms: float = 0.0


# Number of consecutive Backspace presses required to trigger a reversal.
BACKSPACES_TO_REVERT: int = 2
MAX_DOUBLE_BACKSPACE_GAP_MS: float = 2000.0


class TransactionLedger:
    """
    Maintains at most 1 active correction transaction, a one-shot
    post-reversal suppression for the restored token instance only,
    and a non-intrusive list of suggested 'Add to Dictionary' words from reverts.
    """

    def __init__(self, max_session_suppressions: int = 256) -> None:
        self._active: ActiveTransaction | None = None
        # One-shot suppression for the single token instance the user just
        # restored via double-Backspace. Consumed the first time that token
        # is re-completed; never a blanket "this word is correct" signal.
        self._one_shot_suppression: tuple[str, str] | None = None
        self._suggested_words: dict[str, dict[str, object]] = {}
        self._max_suppressions = max_session_suppressions
        self._undo_window_ms: float = MAX_DOUBLE_BACKSPACE_GAP_MS

    def set_undo_window_ms(self, window_ms: float) -> None:
        """Longest pause allowed between the two Backspaces of an undo gesture."""
        self._undo_window_ms = max(100.0, float(window_ms))

    @property
    def suggested_dictionary_words(self) -> list[dict[str, object]]:
        """Words the user reverted, surfaced quietly as 'Add to Dictionary' suggestions."""
        return [dict(v) for v in self._suggested_words.values()]

    @property
    def active_transaction(self) -> ActiveTransaction | None:
        return self._active

    def record_correction(
        self,
        original_token: str,
        corrected_token: str,
        delimiter: str,
        reason: CorrectionReason,
        timestamp_ms: float,
    ) -> None:
        """Store the latest correction in the single bounded slot."""
        self._active = ActiveTransaction(
            original_token=original_token,
            corrected_token=corrected_token,
            delimiter=delimiter,
            reason=reason,
            timestamp_ms=timestamp_ms,
            post_chars_typed=0,
            backspaces_seen=0,
        )

    def on_subsequent_char_typed(self) -> None:
        """
        Once the user begins typing the next word, the immediate-reversal window closes
        so pressing Backspace later only deletes ordinary characters.
        """
        if self._active is not None:
            self._active.post_chars_typed += 1
            if self._active.post_chars_typed > 0:
                self._active = None

    def clear_active(self) -> None:
        """Clear the active undo slot (e.g. on mouse click, arrow key, or focus switch)."""
        self._active = None

    def clear_suppression(self) -> None:
        """Drop any pending one-shot suppression (focus change, reset, navigation)."""
        self._one_shot_suppression = None

    def can_revert_on_backspace(self) -> bool:
        """Return True if a transaction is armed for the double-Backspace gesture."""
        return self._active is not None and self._active.post_chars_typed == 0

    def register_backspace(self, timestamp_ms: float = 0.0) -> bool:
        """
        Count one Backspace press against the armed transaction.

        Returns True only when this press is the second consecutive Backspace
        (without an intervening pause > MAX_DOUBLE_BACKSPACE_GAP_MS),
        meaning the caller must perform the reversal instead of letting the
        press delete another character of the corrected token. The first
        press returns False and must pass through as an ordinary deletion
        (it removes the trailing delimiter).
        """
        if not self.can_revert_on_backspace():
            return False
        assert self._active is not None
        if self._active.backspaces_seen == 0:
            self._active.backspaces_seen = 1
            self._active.first_backspace_ms = timestamp_ms
            return False

        if (
            timestamp_ms > 0.0
            and self._active.first_backspace_ms > 0.0
            and (timestamp_ms - self._active.first_backspace_ms) > self._undo_window_ms
        ):
            # Too long a pause between first and second Backspace: disarm undo.
            self._active = None
            return False

        self._active.backspaces_seen += 1
        return self._active.backspaces_seen >= BACKSPACES_TO_REVERT

    def consume_for_reversal(
        self, backspace_was_suppressed: bool = True
    ) -> tuple[ActiveTransaction, ReplacementPlan] | None:
        """
        Consume the active transaction to restore `original_token`.

        Also registers:
        1. A ONE-SHOT suppression for this restored token instance:
           re-completing the very same token once will not be fought,
           but any later fresh instance of the same misspelling corrects again.
        2. A non-intrusive 'Add to Dictionary' suggestion for single-word
           reverts (no popup while typing).
        """
        if not self.can_revert_on_backspace():
            return None

        tx = self._active
        assert tx is not None
        self._active = None

        # One-shot suppression for this restored instance only.
        self._one_shot_suppression = (tx.original_token.lower(), tx.corrected_token.lower())

        # Note single-token reverts in the suggested 'Add to Dictionary' list
        orig_clean = tx.original_token.strip()
        corr_clean = tx.corrected_token.strip()
        if orig_clean and " " not in orig_clean and orig_clean.lower() != corr_clean.lower():
            low = orig_clean.lower()
            prev = self._suggested_words.get(low)
            prev_count = int(str(prev["revert_count"])) if prev is not None else 0
            self._suggested_words[low] = {
                "word": orig_clean,
                "corrected_to": corr_clean,
                "revert_count": prev_count + 1,
            }

        current_in_field = (
            f"{tx.corrected_token}{tx.delimiter}" if backspace_was_suppressed else tx.corrected_token
        )
        target_restored = tx.original_token

        plan = SuffixDiffPlanner.plan(
            original_full=current_in_field,
            target_full=target_restored,
            delimiter_was_suppressed=False,
        )
        return tx, plan

    def consume_one_shot_suppression(self, original: str, candidate: str) -> bool:
        """
        Return True (and consume the suppression) if this exact token instance
        is the one the user just restored via double-Backspace. Any different
        token expires the suppression so it can never leak into later words.
        """
        if self._one_shot_suppression is None:
            return False
        pending_original, pending_corrected = self._one_shot_suppression
        if original.lower() != pending_original:
            self._one_shot_suppression = None
            return False
        self._one_shot_suppression = None
        return candidate.lower() == pending_corrected

    def is_suppressed_in_session(self, original: str, candidate: str) -> bool:
        """Peek (without consuming) whether the pending one-shot suppression matches."""
        if self._one_shot_suppression is None:
            return False
        pending_original, pending_corrected = self._one_shot_suppression
        return original.lower() == pending_original and candidate.lower() == pending_corrected
