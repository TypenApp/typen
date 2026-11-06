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
from autocorrect.core.models import (
    CorrectionDecision,
    CorrectionFeatures,
    CorrectionReason,
    EvaluationContext,
)
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
# Delimiters after which the n-gram / grammar context is reset: the next word
# starts a new clause, so the word before the mark is not its grammatical neighbour.
CLAUSE_BOUNDARY_DELIMITERS: Final[frozenset[str]] = frozenset({".", ",", "!", "?", ";", ":", "\n"})
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
    # Why a plan without a CorrectionDecision was produced (punctuation assist,
    # snippet expansion); `decision.reason` covers word corrections.
    reason_tag: str | None = None


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
        self._features: CorrectionFeatures = CorrectionFeatures()

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
        # Set after the session itself inserted the space that follows a
        # sentence terminator ('word.' -> 'word. '); the user's own following
        # Space is then swallowed, and a second closing mark re-attaches.
        self._auto_space_pending: bool = False

    @property
    def word_buffer(self) -> ActiveWordBuffer:
        return self._word_buffer

    @property
    def features(self) -> CorrectionFeatures:
        return self._features

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

    def abandon_last_correction(self) -> None:
        """
        The caller decided not to apply the replacement plan it was just given
        (e.g. the user had already moved the caret). Forget the undo
        transaction so a double-Backspace can never 'revert' text that was
        never changed. The field is left exactly as the user typed it.
        """
        self._tx_ledger.clear_active()
        self._auto_space_pending = False

    def configure_features(
        self,
        features: CorrectionFeatures | None = None,
        *,
        enable_auto_space: bool | None = None,
        **overrides: object,
    ) -> None:
        """
        Replace the active feature set (`features`) and/or override individual
        fields by setting-key (`configure_features(enable_grammar=False)`).
        `enable_auto_space` is accepted as a short alias for
        `enable_auto_space_after_sentence`.
        """
        base = features if features is not None else self._features
        if enable_auto_space is not None:
            overrides["enable_auto_space_after_sentence"] = enable_auto_space
        self._features = base.with_overrides(overrides)
        self._tx_ledger.set_undo_window_ms(self._features.undo_window_ms)

    def on_mouse_click_or_caret_move(self, caret_text_before: str | None = None) -> None:
        """
        Invalidate word buffer, undo slot and sentence state after a mouse click
        or caret move.

        `caret_text_before`, when the platform can read it (Windows UI
        Automation probe), is the text immediately before the new caret
        position; the sentence state is then rebuilt from it so the first word
        typed after a click is capitalised exactly when it should be. Without
        it the capitaliser is suppressed (never wrongly capitalise mid-sentence).
        """
        self._word_buffer.mark_tainted()
        self._tx_ledger.clear_active()
        self._tx_ledger.clear_suppression()
        self._preceded_by_space = False
        self._double_space_eligible = False
        self._just_deleted_trailing_space = False
        self._last_completed_word = ""
        self._current_sentence_tokens.clear()
        self._auto_space_pending = False
        if caret_text_before is None:
            self._capitaliser.suppress()
        else:
            self.resync_from_caret(caret_text_before)

    def resync_from_caret(self, text_before: str) -> None:
        """
        Rebuild sentence/context state from the text before the caret (field
        gained focus, click, Tab). Empty text or text ending in a sentence
        terminator (+ optional whitespace) means the next word starts a
        sentence; anything else is mid-sentence. The word buffer is left empty
        and tainted-free so the next word is evaluated normally.
        """
        tail = text_before[-256:]
        self.prime_from_text(tail)
        if not tail.strip():
            self._word_buffer.clear_clean()
            self._capitaliser.reset_to_sentence_start()
            return
        if tail != tail.rstrip():
            # Caret sits after whitespace: the state machine has already seen
            # the delimiter, so `is_sentence_start` is correct as is.
            self._word_buffer.clear_clean()
            return
        # Caret directly after a non-space character ('Hello wor|ld'): the user
        # may be inside a word we cannot see the end of. Never correct that
        # word and never capitalise what they type next; the delimiter they
        # eventually type still advances the sentence state machine.
        self._word_buffer.mark_tainted()
        self._capitaliser.suppress()

    def on_focus_changed(self, focus: FocusContext, caret_text_before: str | None = None) -> None:
        """Flush all ephemeral buffers on window switch and update security/app profile flags."""
        self._focus_context = focus
        self.reset_all_state()
        if caret_text_before is not None:
            self.resync_from_caret(caret_text_before)

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
        self._auto_space_pending = False

    def prime_from_text(self, text: str, typed_at_ms: float | None = None) -> None:
        """
        Rebuild the session state from text that is already in the field, as if
        it had been typed, without correcting any of it.

        Used when a session has to be reconstructed on a different process (the
        website demo runs on serverless instances that come and go) and when a
        field already contains text when it gains focus. Afterwards the context
        ring, sentence-start state and last completed word reflect `text`, so the
        next keystroke is evaluated with the right context; no replacement plan
        is produced and the undo ledger stays empty.

        `typed_at_ms`, when known, is when the last character of `text` was
        typed, on the same clock as the key events that follow. It lets the
        double-space full stop survive a change of process: the second Space is
        only honoured within two seconds of the first, and without a real time
        for that first Space the gesture could never fire after priming.
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
        if typed_at_ms is not None and self._preceded_by_space:
            self._last_space_timestamp_ms = typed_at_ms

    def handle_key_event(
        self,
        event: KeyEvent,
        suppress_delimiter_on_replace: bool = True,
    ) -> SessionEventOutcome:
        """
        Process a single physical key event and return the required action and replacement plan.
        """
        # Smart quotes: decide opening/closing from the state *before* the key is
        # processed, run the ordinary path (which keeps the buffer in ASCII), then
        # swap the straight mark on screen if nothing else touched the text.
        smart = self._smart_quote_for(event) if self._features.smart_quotes else None
        outcome = self._handle_key_event_inner(event, suppress_delimiter_on_replace)
        if (
            smart is not None
            and outcome.action == KeyAction.PASS_THROUGH
            and outcome.replacement_plan is None
        ):
            plan = ReplacementPlan(
                backspaces_to_send=0 if suppress_delimiter_on_replace else 1,
                text_to_inject=smart,
                common_prefix_len=0,
                original_full=event.char,
                target_full=smart,
            )
            if self._injector is not None:
                self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
            return SessionEventOutcome(
                action=KeyAction.SUPPRESS_AND_INJECT
                if suppress_delimiter_on_replace
                else KeyAction.PASS_THROUGH,
                replacement_plan=plan,
                reason_tag="SMART_QUOTE",
            )
        return outcome

    def _smart_quote_for(self, event: KeyEvent) -> str | None:
        """Typographic replacement for a straight quote key, or None when it must stay as typed."""
        ch = event.char
        if ch not in ("'", '"'):
            return None
        if (
            event.is_injected
            or self._priming
            or self._paused
            or self._focus_context.is_terminal_or_code
            or self._focus_context.is_password_or_secure
            or self._focus_context.is_excluded_app
            or event.ctrl_pressed
            or event.alt_pressed
            or event.meta_pressed
        ):
            return None
        word = self._word_buffer.current_word
        if word and word[-1].isalnum():
            # Inside or right after a word: apostrophe ("don't") or closing quote ('word"').
            return "\u2019" if ch == "'" else "\u201d"
        opening = self._preceded_by_space or (not word and not self._last_completed_word)
        if word and word[-1] in "([{\u201c\u2018":
            opening = True
        if ch == "'":
            return "\u2018" if opening else "\u2019"
        return "\u201c" if opening else "\u201d"

    def _handle_key_event_inner(
        self,
        event: KeyEvent,
        suppress_delimiter_on_replace: bool,
    ) -> SessionEventOutcome:
        # 1. Always ignore synthetic keystrokes injected by our own engine
        if event.is_injected:
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 2. Entitlement gate seam (always allowed in Typen)
        if self._entitlement_gate is not None and not self._entitlement_gate.is_typing_assistance_enabled():
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 3. Check pause state, password/secure fields, and excluded applications
        if self._paused or self._focus_context.is_password_or_secure or self._focus_context.is_excluded_app:
            self._word_buffer.clear_clean()
            self._auto_space_pending = False
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 4. Any Ctrl, Alt, or Meta/Win/Cmd shortcut invalidates the active buffer
        if event.ctrl_pressed or event.alt_pressed or event.meta_pressed:
            self.on_mouse_click_or_caret_move()
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 5. Cursor navigation keys invalidate the active buffer. Tab almost
        # always moves to another field, whose first word starts a sentence.
        if event.key_name in NAVIGATION_KEYS:
            self.on_mouse_click_or_caret_move()
            if event.key_name == "Tab":
                self._capitaliser.reset_to_sentence_start()
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # 5b. A space the session inserted after a sentence terminator is pending.
        if self._auto_space_pending:
            handled = self._handle_key_after_auto_space(event, suppress_delimiter_on_replace)
            if handled is not None:
                return handled

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
            if self._features.undo_enabled and self._tx_ledger.register_backspace(event.timestamp_ms):
                reversal = self._tx_ledger.consume_for_reversal(backspace_was_suppressed=False)
                if reversal is not None:
                    tx, plan = reversal
                    self._remember_undo(tx.original_token, tx.corrected_token)
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
            if self._features.cap_after_newline:
                self._capitaliser.reset_to_sentence_start()
            else:
                self._capitaliser.mark_mid_sentence()
            self._preceded_by_space = False
            return outcome

        # 8. Spacebar handling
        if event.key_name == "Space" or event.char == " ":
            # 8a. Check double-space-to-period shortcut when buffer is empty after a space
            if (
                not self._word_buffer.current_word
                and self._preceded_by_space
                and self._double_space_eligible
                and self._features.double_space_period
                and not self._priming
            ):
                inter_ms = event.timestamp_ms - self._last_space_timestamp_ms
                adj = evaluate_double_space_period(
                    prev_token=self._last_completed_word,
                    inter_key_ms=inter_ms,
                    is_code_context=self._focus_context.is_terminal_or_code,
                    max_interval_ms=float(self._features.double_space_interval_ms),
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
                        reason_tag=adj.reason_tag,
                    )

            # 8b. Check space-before-punctuation transposition ('word , ' -> 'word, ')
            curr = self._word_buffer.current_word
            if (
                len(curr) == 1
                and curr in (",", ".", "!", "?")
                and self._preceded_by_space
                and self._features.space_before_punct
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
                        reason_tag=adj.reason_tag,
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
            # 10a. A word started straight after a misplaced 'space + closing mark'
            # ('milk ,and' -> 'milk, and'). The mark was parked in the buffer by
            # step 9 waiting for a Space; a letter instead means the visitor ran
            # the next word into it, so fix the spacing now rather than letting
            # ',and' be evaluated as one misspelt token (which would lose the comma).
            curr = self._word_buffer.current_word
            if (
                len(curr) == 1
                and curr in (",", ".", "!", "?")
                and self._preceded_by_space
                and event.char.isalnum()
                and self._features.space_before_punct
                and not self._priming
            ):
                adj = evaluate_space_before_punctuation(
                    prev_token=self._last_completed_word,
                    punct_char=curr,
                    trailing_space=" ",
                    is_code_context=self._focus_context.is_terminal_or_code,
                )
                if adj.should_modify:
                    # Field holds 'milk ,' (the letter is suppressed) or 'milk ,a'
                    # (the letter already landed): remove back to 'milk' and inject ', a'.
                    plan = ReplacementPlan(
                        backspaces_to_send=2 if suppress_delimiter_on_replace else 3,
                        text_to_inject=f"{curr} {event.char}",
                        common_prefix_len=0,
                        original_full=f" {curr}{event.char}",
                        target_full=f"{curr} {event.char}",
                    )
                    self._word_buffer.clear_clean()
                    self._word_buffer.append_char(event.char, event.timestamp_ms)
                    self._double_space_eligible = False
                    self._just_deleted_trailing_space = False
                    if adj.triggers_sentence_start:
                        self._capitaliser.reset_to_sentence_start()
                        self._current_sentence_tokens.clear()
                    if self._injector is not None:
                        self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
                    return SessionEventOutcome(
                        action=(
                            KeyAction.SUPPRESS_AND_INJECT
                            if suppress_delimiter_on_replace
                            else KeyAction.PASS_THROUGH
                        ),
                        replacement_plan=plan,
                        reason_tag=adj.reason_tag,
                    )
            self._just_deleted_trailing_space = False
            self._tx_ledger.on_subsequent_char_typed()
            if not self._word_buffer.current_word and event.char in PREFIX_SYMBOLS:
                self._word_buffer.append_prefix_symbol(event.char, event.timestamp_ms)
            else:
                self._word_buffer.append_char(event.char, event.timestamp_ms)
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

    def _remember_undo(self, original: str, corrected: str) -> None:
        """
        What an undo means for the future, per `undo_remembers`:
        never   - nothing is kept (the one-shot suppression still applies);
        session - the word is quietly listed as an 'Add to Dictionary' suggestion;
        always  - the pair is also rejected for good.
        """
        mode = self._features.undo_remembers
        if mode == "never":
            return
        prefs = self._engine.preferences
        if prefs is None:
            return
        if hasattr(prefs, "note_reverted_word"):
            prefs.note_reverted_word(original, corrected)
        if mode == "always" and " " not in original and hasattr(prefs, "add_rejected_correction"):
            prefs.add_rejected_correction(original, corrected)

    # ------------------------------------------------------------ auto-space

    def _should_auto_space(self, word: str, delimiter: str, leading_prefix: str) -> bool:
        """
        Insert a space after `word<delimiter>`? Only for a real sentence end: a
        word of at least two letters, closed by '.', '!' or '?', in prose (not
        code/terminal), not an abbreviation/initial/number/URL part and not a
        token with a symbol prefix ('--flag.' '/path.').
        """
        if not self._features.auto_space or self._priming:
            return False
        if delimiter not in (".", "!", "?"):
            return False
        if self._focus_context.is_terminal_or_code:
            return False
        # Opening quotes/brackets are prose ('"no."'); anything else ('--flag.',
        # '/path.', '@handle.', '#tag.') is a token we must not reflow.
        if leading_prefix.strip("\"'(\u2018\u201c["):
            return False
        if len(word) < 2 or not word[-1].isalpha():
            return False
        if not any(ch.isalpha() for ch in word[:-1]):
            return False
        if any(ch in word for ch in "./\\@:_") or word[0].isdigit():
            return False
        if delimiter == "." and self._capitaliser.is_abbreviation(word):
            return False
        return True

    def _arm_auto_space(self, timestamp_ms: float) -> None:
        """The field now ends with '<terminator> ' that we inserted."""
        self._auto_space_pending = True
        self._preceded_by_space = True
        self._double_space_eligible = False
        self._just_deleted_trailing_space = False
        self._last_space_timestamp_ms = timestamp_ms
        # The terminator left the capitaliser AWAITING_SPACE; the space we added fulfils it.
        self._capitaliser.on_word_completed("", " ")

    def _handle_key_after_auto_space(self, event: KeyEvent, suppress: bool) -> SessionEventOutcome | None:
        """
        Resolve the key typed right after an auto-inserted space. Returns None
        when the key should go through normal processing (the pending flag is
        then cleared and the auto space simply stays).
        """
        ch = event.char
        self._auto_space_pending = False

        # The user typed the space themselves: swallow it (passive mode: it has
        # already landed, so delete the duplicate).
        if event.key_name == "Space" or ch == " ":
            plan = ReplacementPlan(
                backspaces_to_send=0 if suppress else 1,
                text_to_inject="",
                common_prefix_len=0,
                original_full="  ",
                target_full=" ",
            )
            self._preceded_by_space = True
            self._double_space_eligible = False
            if self._injector is not None and not plan.is_noop:
                self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
            return SessionEventOutcome(
                action=KeyAction.SUPPRESS_AND_INJECT if suppress else KeyAction.PASS_THROUGH,
                replacement_plan=plan,
                reason_tag="AUTO_SPACE_SWALLOWED",
            )

        # Backspace: the user is removing our space; let it go and remember the
        # caret is back right after the terminator.
        if event.key_name == "Backspace":
            self._preceded_by_space = False
            self._just_deleted_trailing_space = False
            self._capitaliser.mark_after_terminal()
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # Another closing mark ('...', '?!', '."', '.)'): pull it back against the terminator.
        if ch and ch in ".!?)\"'\u2019\u201d]":
            plan = ReplacementPlan(
                backspaces_to_send=1 if suppress else 2,
                text_to_inject=ch,
                common_prefix_len=0,
                original_full=f" {ch}",
                target_full=ch,
            )
            self._preceded_by_space = False
            if ch == ".":
                self._capitaliser.mark_mid_sentence()  # an ellipsis never forces a capital
            else:
                self._capitaliser.mark_after_terminal()
            if self._injector is not None:
                self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
            return SessionEventOutcome(
                action=KeyAction.SUPPRESS_AND_INJECT if suppress else KeyAction.PASS_THROUGH,
                replacement_plan=plan,
                reason_tag="AUTO_SPACE_REATTACH",
            )

        # A lowercase letter or digit straight after the terminator: the user is
        # typing a URL, file name or version ('example.com', 'report.docx',
        # 'v1.beta'); take the space back and never touch that token.
        if ch and (ch.islower() or ch.isdigit()):
            plan = ReplacementPlan(
                backspaces_to_send=1 if suppress else 2,
                text_to_inject=ch,
                common_prefix_len=0,
                original_full=f" {ch}",
                target_full=ch,
            )
            self._preceded_by_space = False
            self._word_buffer.mark_tainted()
            self._capitaliser.suppress()
            if self._injector is not None:
                self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
            return SessionEventOutcome(
                action=KeyAction.SUPPRESS_AND_INJECT if suppress else KeyAction.PASS_THROUGH,
                replacement_plan=plan,
                reason_tag="AUTO_SPACE_UNDONE",
            )

        # Anything else (capital letter, Return, symbol): the space stays.
        return None

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
            if delimiter in CLAUSE_BOUNDARY_DELIMITERS:
                self._context_ring.clear()
            self._capitaliser.on_word_completed(token, delimiter)
            self._last_completed_word = token
            self._current_sentence_tokens.append(token + delimiter if delimiter in (",", ";", ":") else token)
            if delimiter in (".", "!", "?", "\n"):
                self._current_sentence_tokens.clear()
            return SessionEventOutcome(action=KeyAction.PASS_THROUGH)

        # In passive mode (OS hooks that cannot block a key) a Return has already
        # been delivered before we run: in chat apps the message is gone. Any
        # injection now would land in the empty composer and send garbage, so a
        # Return boundary only advances state and is never corrected after the fact.
        passive_newline = delimiter == "\n" and not suppress_delimiter

        # Check Pro Snippet Expansion first (e.g. ';sig', '@@email')
        pro_active = self._entitlement_gate is None or self._entitlement_gate.is_pro_enabled()
        if pro_active and self._snippet_matcher is not None and not passive_newline:
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
                    reason_tag=CorrectionReason.SNIPPET_EXPANSION.value,
                )

        # Build evaluation context from the 5-token ID ring buffer
        p1 = self._context_ring.prev1()
        p2 = self._context_ring.prev2()
        eval_ctx = EvaluationContext.with_features(
            self._features,
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
        if (
            not passive_newline
            and self._features.enable_retroactive
            and not self._focus_context.is_terminal_or_code
            and self._last_completed_word
            and p1 is not None
        ):
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
        if delimiter in CLAUSE_BOUNDARY_DELIMITERS:
            # Grammar / confusion context never crosses a clause boundary:
            # 'Hi everyone, dont worry' must not see 'everyone' as the subject of 'dont'.
            self._context_ring.clear()
        self._capitaliser.on_word_completed(final_word, delimiter)
        self._last_completed_word = final_word
        # Keep the clause mark on the token so grammar can see the boundary.
        self._current_sentence_tokens.append(
            final_word + delimiter if delimiter in (",", ";", ":") else final_word
        )

        sentence_completed: str | None = None
        if delimiter in (".", "!", "?", "\n") and self._current_sentence_tokens:
            sentence_completed = " ".join(self._current_sentence_tokens) + (
                delimiter if delimiter != "\n" else ""
            )
            if self._capitaliser.is_sentence_start or delimiter in (".", "!", "?", "\n"):
                self._current_sentence_tokens.clear()

        if passive_newline:
            # State is up to date (context ring, sentence start, last word); the
            # text itself is left exactly as the user sent it.
            self._tx_ledger.clear_active()
            return SessionEventOutcome(
                action=KeyAction.PASS_THROUGH,
                decision=decision,
                sentence_completed_text=sentence_completed,
            )

        # Sentence end: the field should read '<word><terminator> ' so the user
        # can keep typing (a Space they type anyway is swallowed next).
        auto_space = self._should_auto_space(final_word, delimiter, leading_prefix)
        suffix = " " if auto_space else ""

        if retro_plan is not None and not retro_plan.is_noop:
            if auto_space:
                retro_plan = SuffixDiffPlanner.plan(
                    original_full=retro_plan.original_full,
                    target_full=retro_plan.target_full + suffix,
                    delimiter_was_suppressed=suppress_delimiter,
                )
                self._arm_auto_space(timestamp_ms)
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
                target_full=decision.full_replacement + suffix,
                delimiter_was_suppressed=suppress_delimiter,
            )
            self._tx_ledger.record_correction(
                original_token=decision.original_token,
                corrected_token=decision.replacement_token,
                delimiter=decision.replacement_delimiter,
                reason=decision.reason,
                timestamp_ms=timestamp_ms,
            )
            if auto_space:
                self._arm_auto_space(timestamp_ms)
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

        if auto_space:
            original_full = f"{token}{delimiter}"
            plan = SuffixDiffPlanner.plan(
                original_full=original_full,
                target_full=original_full + suffix,
                delimiter_was_suppressed=suppress_delimiter,
            )
            self._arm_auto_space(timestamp_ms)
            if self._injector is not None and not plan.is_noop:
                self._injector.execute_replacement(plan.backspaces_to_send, plan.text_to_inject)
            return SessionEventOutcome(
                action=(KeyAction.SUPPRESS_AND_INJECT if suppress_delimiter else KeyAction.PASS_THROUGH),
                replacement_plan=plan,
                decision=decision,
                sentence_completed_text=sentence_completed,
                reason_tag="AUTO_SPACE",
            )

        return SessionEventOutcome(
            action=KeyAction.PASS_THROUGH,
            decision=decision,
            sentence_completed_text=sentence_completed,
        )
