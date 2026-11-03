"""
Real-Time Input Session Manager.
Coordinates keyboard event filtering, privacy/focus exclusions, word boundary
detection, two-word retroactive homophone checks, punctuation assistance,
sentence capitalisation, snippet expansion, and atomic suffix-diff replacement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

from autocorrect.core.capitalisation import SentenceCapitaliser
from autocorrect.core.confusion_sets import evaluate_retroactive_two_word_confusion
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import CorrectionDecision, CorrectionReason, EvaluationContext
from autocorrect.core.punctuation import (
    evaluate_double_space_period,
    evaluate_space_before_punctuation,
)
from autocorrect.input.diff_planner import ReplacementPlan, SuffixDiffPlanner
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent, TextInjectorPort
from autocorrect.input.transaction_ledger import TransactionLedger
from autocorrect.input.word_buffer import ActiveWordBuffer, ContextRingBuffer
from autocorrect.intelligence.schema import RegionFlag

WORD_BOUNDARY_PUNCTUATION: Final[frozenset[str]] = frozenset(
    {".", ",", "!", "?", ";", ":", ")", "]", "}", '"', "\n"}
)
PREFIX_SYMBOLS: Final[frozenset[str]] = frozenset({"-", "/", "\\", "@", "#", "$", "~", ".", ";"})
NAVIGATION_KEYS: Final[frozenset[str]] = frozenset(
    {
        "Left",
        "Right",
        "Up",
        "Down",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Tab",
        "Escape",
        "Delete",
        "Insert",
    }
)


class SnippetMatcherPort(Protocol):
    """Optional Pro snippet expansion interface."""

    def match_snippet(self, trigger_token: str) -> str | None: ...


class EntitlementCheckPort(Protocol):
    """Interface for checking whether typing assistance and Pro features are active."""

    def is_typing_assistance_enabled(self) -> bool: ...

    def is_pro_enabled(self) -> bool: ...


@dataclass(slots=True)
class SessionEventOutcome:
    """Result of processing a single KeyEvent through InputSessionManager."""

    action: KeyAction
    replacement_plan: ReplacementPlan | None = None
    decision: CorrectionDecision | None = None
    reverted_word: str | None = None
    sentence_completed_text: str | None = None  # Populated for Pro Layer 2 async trigger


class InputSessionManager:
    """
    Stateful, single-threaded automaton processing keystrokes, mouse clicks,
    and window focus switches.
    """

    def __init__(
        self,
        engine: AutocorrectEngine,
        injector: TextInjectorPort | None = None,
        snippet_matcher: SnippetMatcherPort | None = None,
        entitlement_gate: EntitlementCheckPort | None = None,
        active_region: RegionFlag = RegionFlag.EN_GB,
    ) -> None:
        self._engine = engine
        self._injector = injector
        self._snippet_matcher = snippet_matcher
        self._entitlement_gate = entitlement_gate
        self._active_region = active_region

        self._word_buffer = ActiveWordBuffer()
        self._context_ring = ContextRingBuffer()
        self._tx_ledger = TransactionLedger()
        self._capitaliser = SentenceCapitaliser(
            abbrev_set=engine.resource_manager.active_bundle.abbreviations
        )

        self._paused: bool = False
        self._focus_context = FocusContext()
        self._enable_punctuation_assist: bool = True
        self._enable_double_space_period: bool = True
        self._enable_auto_capitalise: bool = True
        self._aggressiveness: float = 1.0

        self._last_completed_word: str = ""
        self._last_space_timestamp_ms: float = 0.0
        self._preceded_by_space: bool = False
        # True only when the immediately preceding boundary was a word completed
        # by a Space (or a space re-typed right after deleting a trailing space).
        # Prevents double-space-period from firing after terminal punctuation
        # ('Hello.  ' must never become 'Hello.. ').
        self._double_space_eligible: bool = False
        self._just_deleted_trailing_space: bool = False
        self._current_sentence_tokens: list[str] = []
        # While True, `prime_from_text` is replaying text that is already in the
        # field: the state machine advances (context ring, sentence state, last
        # word) but nothing is ever corrected, expanded or injected.
        self._priming: bool = False

    @property
    def word_buffer(self) -> ActiveWordBuffer:
        return self._word_buffer

    @property
    def transaction_ledger(self) -> TransactionLedger:
        return self._tx_ledger

    @property
    def capitaliser(self) -> SentenceCapitaliser:
        return self._capitaliser

    @property
    def is_paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self.reset_all_state()

    def set_active_region(self, region: RegionFlag) -> None:
        self._active_region = region

    def configure_features(
        self,
        *,
        enable_punctuation_assist: bool | None = None,
        enable_double_space_period: bool | None = None,
        enable_auto_capitalise: bool | None = None,
        aggressiveness: float | None = None,
    ) -> None:
        if enable_punctuation_assist is not None:
            self._enable_punctuation_assist = enable_punctuation_assist
        if enable_double_space_period is not None:
            self._enable_double_space_period = enable_double_space_period
        if enable_auto_capitalise is not None:
            self._enable_auto_capitalise = enable_auto_capitalise
        if aggressiveness is not None:
            self._aggressiveness = aggressiveness

    def on_mouse_click_or_caret_move(self) -> None:
        """Invalidate word buffer, undo slot, and sentence state on mouse click."""
        self._word_buffer.mark_tainted()
        self._tx_ledger.clear_active()
        self._tx_ledger.clear_suppression()
        self._capitaliser.suppress()
        self._preceded_by_space = False
        self._double_space_eligible = False
        self._just_deleted_trailing_space = False
        self._last_completed_word = ""
        self._current_sentence_tokens.clear()

    def on_focus_changed(self, focus: FocusContext) -> None:
        """Flush all ephemeral buffers on window switch and update security/app profile flags."""
        self._focus_context = focus
        self.reset_all_state()

    def reset_all_state(self) -> None:
        self._word_buffer.clear_clean()
        self._context_ring.clear()
        self._tx_ledger.clear_active()
        self._tx_ledger.clear_suppression()
        self._capitaliser.reset_to_sentence_start()
        self._last_completed_word = ""
        self._last_space_timestamp_ms = 0.0
        self._preceded_by_space = False
        self._double_space_eligible = False
        self._just_deleted_trailing_space = False
        self._current_sentence_tokens.clear()

    def prime_from_text(self, text: str) -> None:
        """
        Rebuild the session state from text that is already in the field, as if
        it had been typed, without correcting any of it.

        Used when a session has to be reconstructed on a different process (the
        website demo runs on serverless instances that come and go) and when a
        field already contains text when it gains focus. Afterwards the context
        ring, sentence-start state and last completed word reflect `text`, so the
        next keystroke is evaluated with the right context; no replacement plan
        is produced and the undo ledger stays empty.
        """
        self.reset_all_state()
        if not text:
            return
        self._priming = True
        try:
            ts = 0.0
            for ch in text:
                ts += 250.0  # slow enough that no timing shortcut can arm
                if ch == "\n":
                    key_name = "Return"
                elif ch == " ":
                    key_name = "Space"
                elif ch in ("\t", "\r"):
                    continue
                else:
                    key_name = ch
                self.handle_key_event(KeyEvent(key_name=key_name, char=ch, timestamp_ms=ts))
        finally:
            self._priming = False
        # The field's existing text is not something the visitor can revert.
        self._tx_ledger.clear_active()
        self._tx_ledger.clear_suppression()

    def handle_key_event(
        self,
        event: KeyEvent,
        suppress_delimiter_on_replace: bool = True,
    ) -> SessionEventOutcome:
        """
        Process a single physical key event and return the required action and replacement plan.
        """
        # 1. Always ignore synthetic keystrokes injected by our own engine
        if event.is_injected:
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 2. Check commercial entitlement gate (e.g. expired 14-day trial)
        if self._entitlement_gate is not None and not self._entitlement_gate.is_typing_assistance_enabled():
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 3. Check pause state, password/secure fields, and excluded applications
        if self._paused or self._focus_context.is_password_or_secure or self._focus_context.is_excluded_app:
            self._word_buffer.clear_clean()
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 4. Any Ctrl, Alt, or Meta/Win/Cmd shortcut invalidates the active buffer
        if event.ctrl_pressed or event.alt_pressed or event.meta_pressed:
            self.on_mouse_click_or_caret_move()
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 5. Cursor navigation keys invalidate the active buffer
        if event.key_name in NAVIGATION_KEYS:
            self.on_mouse_click_or_caret_move()
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 6. Backspace handling: DELIBERATE double-Backspace correction reversal.
        # The first Backspace after a correction is an ordinary edit (it deletes
        # the trailing delimiter) so a fast typist's subconscious single press
        # never triggers an undo. Only the second consecutive Backspace restores
        # the original token; by then the delimiter is already gone, so the plan
        # transforms corrected_token -> original_token with no delimiter involved.
        # Any non-Backspace key event immediately disarms any pending undo so an
        # interrupted gesture (e.g. Backspace + Space + Backspace, or
        # Space + Space + Backspace) can NEVER trigger a botched revert.
        if event.key_name == "Backspace":
            self._double_space_eligible = False
            if self._tx_ledger.register_backspace(event.timestamp_ms):
                reversal = self._tx_ledger.consume_for_reversal(backspace_was_suppressed=False)
                if reversal is not None:
                    tx, plan = reversal
                    # Quietly note single-word reverts as 'Add to Dictionary' suggestions
                    prefs = self._engine.preferences
                    if prefs is not None and hasattr(prefs, "note_reverted_word"):
                        prefs.note_reverted_word(tx.original_token, tx.corrected_token)
                    # Restore only the final word of the reverted token into the
                    # active buffer (two-word retroactive transactions contain a
                    # space; the earlier word is no longer being edited).
                    restored_word = tx.original_token.rsplit(" ", 1)[-1]
                    if self._current_sentence_tokens:
                        self._current_sentence_tokens.pop()
                    self._word_buffer.clear_clean()
                    for ch in restored_word:
                        self._word_buffer.append_char(ch, event.timestamp_ms)
                    self._preceded_by_space = False
                    if self._injector is not None and not plan.is_noop:
                        self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
                    return SessionEventOutcome(
                        action=(
                            KeyAction.SUPPRESS_AND_INJECT
                            if suppress_delimiter_on_replace
                            else KeyAction.PASS_THROUGH
                        ),
                        replacement_plan=plan,
                        reverted_word=tx.original_token,
                    )

            if self._preceded_by_space and not self._word_buffer.current_word:
                # Deleting the single trailing space after a completed word leaves
                # the caret at the end of `_last_completed_word`; do not taint the
                # buffer yet so a subsequent Space + Space can still insert a period.
                self._preceded_by_space = False
                self._just_deleted_trailing_space = True
            else:
                self._word_buffer.handle_backspace(event.timestamp_ms)
                self._preceded_by_space = False
                self._just_deleted_trailing_space = False
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # Any non-Backspace key interrupts and cancels any armed double-Backspace undo!
        self._tx_ledger.clear_active()

        # 7. Return / Enter key: evaluate completed word + reset sentence state to SENTENCE_START
        if event.key_name in ("Return", "Enter") or event.char == "\n":
            outcome = self._evaluate_boundary(
                delimiter="\n",
                timestamp_ms=event.timestamp_ms,
                suppress_delimiter=suppress_delimiter_on_replace,
            )
            self._capitaliser.reset_to_sentence_start()
            self._preceded_by_space = False
            return outcome

        # 8. Spacebar handling
        if event.key_name == "Space" or event.char == " ":
            # 8a. Check double-space-to-period shortcut when buffer is empty after a space
            if (
                not self._word_buffer.current_word
                and self._preceded_by_space
                and self._double_space_eligible
                and self._enable_punctuation_assist
                and self._enable_double_space_period
                and not self._priming
            ):
                inter_ms = event.timestamp_ms - self._last_space_timestamp_ms
                adj = evaluate_double_space_period(
                    prev_token=self._last_completed_word,
                    inter_key_ms=inter_ms,
                    is_code_context=self._focus_context.is_terminal_or_code,
                )
                if adj.should_modify:
                    plan = ReplacementPlan(
                        backspaces_to_send=(
                            adj.backspaces_required - 1
                            if suppress_delimiter_on_replace
                            else adj.backspaces_required
                        ),
                        text_to_inject=adj.replacement_text,
                        common_prefix_len=0,
                        original_full="  ",
                        target_full=". ",
                    )
                    # Do not record a word-revert transaction for double-space period:
                    # ordinary Backspace already deletes the trailing space and period
                    # naturally, and `space + space + backspace` must never trigger a
                    # word revert.
                    self._tx_ledger.clear_active()
                    self._capitaliser.reset_to_sentence_start()
                    self._current_sentence_tokens.clear()
                    self._preceded_by_space = False
                    self._double_space_eligible = False
                    if self._injector is not None:
                        self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
                    return SessionEventOutcome(
                        action=(
                            KeyAction.SUPPRESS_AND_INJECT
                            if suppress_delimiter_on_replace
                            else KeyAction.PASS_THROUGH
                        ),
                        replacement_plan=plan,
                    )

            # 8b. Check space-before-punctuation transposition ('word , ' -> 'word, ')
            curr = self._word_buffer.current_word
            if (
                len(curr) == 1
                and curr in (",", ".", "!", "?")
                and self._preceded_by_space
                and self._enable_punctuation_assist
                and not self._priming
            ):
                adj = evaluate_space_before_punctuation(
                    prev_token=self._last_completed_word,
                    punct_char=curr,
                    trailing_space=" ",
                    is_code_context=self._focus_context.is_terminal_or_code,
                )
                if adj.should_modify:
                    plan = ReplacementPlan(
                        backspaces_to_send=(
                            adj.backspaces_required - 1
                            if suppress_delimiter_on_replace
                            else adj.backspaces_required
                        ),
                        text_to_inject=adj.replacement_text,
                        common_prefix_len=0,
                        original_full=f" {curr} ",
                        target_full=f"{curr} ",
                    )
                    self._word_buffer.clear_clean()
                    self._double_space_eligible = False
                    if adj.triggers_sentence_start:
                        self._capitaliser.reset_to_sentence_start()
                    if self._injector is not None:
                        self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
                    return SessionEventOutcome(
                        action=(
                            KeyAction.SUPPRESS_AND_INJECT
                            if suppress_delimiter_on_replace
                            else KeyAction.PASS_THROUGH
                        ),
                        replacement_plan=plan,
                    )

            outcome = self._evaluate_boundary(
                delimiter=" ",
                timestamp_ms=event.timestamp_ms,
                suppress_delimiter=suppress_delimiter_on_replace,
            )
            self._last_space_timestamp_ms = event.timestamp_ms
            self._preceded_by_space = True
            return outcome

        # 9. Punctuation word boundaries (when a word is currently being typed, or non-prefix punctuation)
        # A closing mark typed right after a Space ('word .') must enter this
        # branch even for '.' (normally a prefix symbol for decimals/files),
        # so the space-before-punctuation fix can run on the next Space.
        if event.char in WORD_BOUNDARY_PUNCTUATION and (
            self._word_buffer.is_clean_and_nonempty
            or event.char not in PREFIX_SYMBOLS
            or (
                event.char in (",", ".", "!", "?")
                and self._preceded_by_space
                and not self._word_buffer.current_word
            )
        ):
            # An internal dot or hyphen inside a word? Wait: if user types 'e.g.' or '3.14',
            # or a sentence-ending period after a word ('mesage.').
            # Evaluate the word before the punctuation mark!
            if self._word_buffer.is_clean_and_nonempty:
                outcome = self._evaluate_boundary(
                    delimiter=event.char,
                    timestamp_ms=event.timestamp_ms,
                    suppress_delimiter=suppress_delimiter_on_replace,
                )
                self._preceded_by_space = False
                return outcome
            else:
                # Punctuation typed when buffer is empty (e.g. after space: 'word ,')
                if event.char in (",", ".", "!", "?") and self._preceded_by_space:
                    self._word_buffer.append_char(event.char, event.timestamp_ms)
                    return SessionEventOutcome(action=KeyAction.PASS_THROUGH)
                self._capitaliser.on_word_completed("", event.char)
                self._word_buffer.clear_clean()
                self._double_space_eligible = False
                self._just_deleted_trailing_space = False
                return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 10. Printable word character (letters, digits, internal apostrophe/hyphen, or snippet prefix ';')
        if event.char:
            self._just_deleted_trailing_space = False
            self._tx_ledger.on_subsequent_char_typed()
            if not self._word_buffer.current_word and event.char in PREFIX_SYMBOLS:
                self._word_buffer.append_prefix_symbol(event.char, event.timestamp_ms)
            else:
                self._word_buffer.append_char(event.char, event.timestamp_ms)
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

    def _evaluate_boundary(
        self,
        delimiter: str,
        timestamp_ms: float,
        suppress_delimiter: bool,
    ) -> SessionEventOutcome:
        if not self._word_buffer.is_clean_and_nonempty:
            self._word_buffer.clear_clean()
            self._double_space_eligible = (
                delimiter == " "
                and self._just_deleted_trailing_space
                and bool(self._last_completed_word)
                and self._last_completed_word[-1].isalnum()
            )
            self._just_deleted_trailing_space = False
            self._capitaliser.on_word_completed("", delimiter)
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # Only a word completed by a Space arms the double-space-period shortcut.
        self._double_space_eligible = delimiter == " "
        self._just_deleted_trailing_space = False
        token = self._word_buffer.current_word
        leading_prefix = self._word_buffer.leading_prefix
        self._word_buffer.clear_clean()

        if self._priming:
            # Replaying existing text: advance context exactly as an accepted,
            # uncorrected word would, and never evaluate, expand or inject.
            self._context_ring.push(self._engine.resolve_word_id(token), token.lower())
            self._capitaliser.on_word_completed(token, delimiter)
            self._last_completed_word = token
            self._current_sentence_tokens.append(token)
            if delimiter in (".", "!", "?", "\n"):
                self._current_sentence_tokens.clear()
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # Check Pro Snippet Expansion first (e.g. ';sig', '@@email')
        pro_active = self._entitlement_gate is None or self._entitlement_gate.is_pro_enabled()
        if pro_active and self._snippet_matcher is not None:
            full_trigger = f"{leading_prefix}{token}" if leading_prefix else token
            expanded = self._snippet_matcher.match_snippet(full_trigger)
            if expanded is not None:
                orig_full = f"{full_trigger}{delimiter}"
                target_full = f"{expanded}{delimiter}"
                plan = SuffixDiffPlanner.plan(
                    original_full=orig_full,
                    target_full=target_full,
                    delimiter_was_suppressed=suppress_delimiter,
                )
                self._tx_ledger.record_correction(
                    original_token=full_trigger,
                    corrected_token=expanded,
                    delimiter=delimiter,
                    reason=CorrectionReason.SNIPPET_EXPANSION,
                    timestamp_ms=timestamp_ms,
                )
                if self._injector is not None and not plan.is_noop:
                    self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
                return SessionEventOutcome(
                    action=(KeyAction.SUPPRESS_AND_INJECT if suppress_delimiter else KeyAction.PASS_THROUGH),
                    replacement_plan=plan,
                )

        # Build evaluation context from the 5-token ID ring buffer
        p1 = self._context_ring.prev1()
        p2 = self._context_ring.prev2()
        eval_ctx = EvaluationContext(
            prev1_word=p1.normalized_in_vocab_word if p1 else None,
            prev2_word=p2.normalized_in_vocab_word if p2 else None,
            prev1_word_id=p1.word_id if p1 else None,
            prev2_word_id=p2.word_id if p2 else None,
            clause_tokens=tuple(self._current_sentence_tokens),
            is_sentence_start=self._capitaliser.is_sentence_start,
            leading_prefix=leading_prefix,
            trailing_delimiter=delimiter,
            active_region=self._active_region,
            is_code_or_terminal_app=self._focus_context.is_terminal_or_code,
            enable_punctuation_assist=self._enable_punctuation_assist,
            enable_auto_capitalise=self._enable_auto_capitalise,
            aggressiveness=self._aggressiveness,
        )

        decision = self._engine.evaluate_token(token, eval_ctx)

        # One-shot suppression: only if the user just restored THIS token
        # instance via double-Backspace and is immediately re-completing it.
        # Consumed on use/expired on any other token, so a later fresh instance
        # of the same misspelling is corrected normally.
        if decision.should_replace and self._tx_ledger.consume_one_shot_suppression(
            decision.original_token, decision.replacement_token
        ):
            decision = CorrectionDecision(
                original_token=decision.original_token,
                replacement_token=decision.original_token,
                original_delimiter=delimiter,
                replacement_delimiter=delimiter,
                should_replace=False,
                reason=CorrectionReason.USER_REJECTED,
                confidence=0.0,
                margin=0.0,
            )

        # Check retroactive 2-word confusion & grammar ('your welcome' -> "you're welcome",
        # 'a egg' -> 'an egg', 'a eggs' -> 'an egg', 'there is many' -> 'there are many')
        retro_plan: ReplacementPlan | None = None
        final_word = decision.replacement_token if decision.should_replace else token
        if not self._focus_context.is_terminal_or_code and self._last_completed_word and p1 is not None:
            retro_prev = evaluate_retroactive_two_word_confusion(
                self._last_completed_word,
                final_word,
                prev2_word=p2.normalized_in_vocab_word if p2 else None,
            )
            if retro_prev is not None:
                # Preserve original casing of the previous word
                from autocorrect.core.casing import apply_casing_transfer

                formatted_prev = apply_casing_transfer(
                    original=self._last_completed_word,
                    target_lower=retro_prev,
                )
                if not self._tx_ledger.is_suppressed_in_session(self._last_completed_word, formatted_prev):
                    orig_two = f"{self._last_completed_word} {token}{delimiter}"
                    target_two = f"{formatted_prev} {final_word}{delimiter}"
                    retro_plan = SuffixDiffPlanner.plan(
                        original_full=orig_two,
                        target_full=target_two,
                        delimiter_was_suppressed=suppress_delimiter,
                    )
                    self._tx_ledger.record_correction(
                        original_token=f"{self._last_completed_word} {token}",
                        corrected_token=f"{formatted_prev} {final_word}",
                        delimiter=delimiter,
                        reason=CorrectionReason.CONTEXTUAL_CONFUSION,
                        timestamp_ms=timestamp_ms,
                    )
                    prev_wid = self._engine.resolve_word_id(formatted_prev)
                    self._context_ring.replace_last(prev_wid, formatted_prev.lower())
                    if self._current_sentence_tokens:
                        self._current_sentence_tokens[-1] = formatted_prev

        # Advance context ring buffer and sentence boundary tracker
        final_wid = self._engine.resolve_word_id(final_word)
        self._context_ring.push(final_wid, final_word.lower())
        self._capitaliser.on_word_completed(final_word, delimiter)
        self._last_completed_word = final_word
        self._current_sentence_tokens.append(final_word)

        sentence_completed: str | None = None
        if delimiter in (".", "!", "?", "\n") and self._current_sentence_tokens:
            sentence_completed = " ".join(self._current_sentence_tokens) + (
                delimiter if delimiter != "\n" else ""
            )
            if self._capitaliser.is_sentence_start or delimiter in (".", "!", "?", "\n"):
                self._current_sentence_tokens.clear()

        if retro_plan is not None and not retro_plan.is_noop:
            if self._injector is not None:
                self._injector.execute_replacement(retro_plan.backspaces_to_send, retro_plan.text_to_inject)
            return SessionEventOutcome(
                action=(KeyAction.SUPPRESS_AND_INJECT if suppress_delimiter else KeyAction.PASS_THROUGH),
                replacement_plan=retro_plan,
                decision=decision,
                sentence_completed_text=sentence_completed,
            )

        if decision.should_replace:
            plan = SuffixDiffPlanner.plan(
                original_full=decision.full_original,
                target_full=decision.full_replacement,
                delimiter_was_suppressed=suppress_delimiter,
            )
            self._tx_ledger.record_correction(
                original_token=decision.original_token,
                corrected_token=decision.replacement_token,
                delimiter=decision.replacement_delimiter,
                reason=decision.reason,
                timestamp_ms=timestamp_ms,
            )
            if self._injector is not None and not plan.is_noop:
                self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
            return SessionEventOutcome(
                action=(KeyAction.SUPPRESS_AND_INJECT if suppress_delimiter else KeyAction.PASS_THROUGH),
                replacement_plan=plan,
                decision=decision,
                sentence_completed_text=sentence_completed,
            )

        # Any previous correction transaction expires once a subsequent word completes without correction
        self._tx_ledger.clear_active()
        return SessionEventOutcome(
            action=KeyAction.PASS_THROUGH,
            decision=decision,
            sentence_completed_text=sentence_completed,
        )
