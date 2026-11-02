"""
Acceptance Tests for Core Standard Edition:
- Spelling accuracy & candidate ranking
- Punctuation assistance (contractions, space-before-punctuation, double-space period, operator preservation)
- Automatic sentence capitalisation & abbreviation/URL/code guards
- Contextual homophones & retroactive 2-word disambiguation
- Deliberate double-Backspace undo & one-shot (same-instance) revert suppression
- Case & formatting preservation
- False-positive rate (< 0.1%)
"""

from __future__ import annotations

from pathlib import Path

from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import CorrectionReason, EvaluationContext
from autocorrect.input.ports import KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.intelligence.schema import RegionFlag
from pipeline.regression_runner import run_golden_corpus_regression


def _type_string(session: InputSessionManager, text: str, base_ts: float = 1000.0) -> str:
    """
    Simulate typing `text` character-by-character into a virtual text field
    governed by `session` and return the resulting field contents.
    """
    field_chars: list[str] = []
    ts = base_ts
    for ch in text:
        ts += 60.0
        key_name = "Space" if ch == " " else ("Return" if ch == "\n" else ch)
        evt = KeyEvent(key_name=key_name, char=ch, timestamp_ms=ts)
        outcome = session.handle_key_event(evt, suppress_delimiter_on_replace=True)
        if outcome.action == KeyAction.PASS_THROUGH:
            field_chars.append(ch)
        elif (
            outcome.action == KeyAction.SUPPRESS_AND_INJECT
            and outcome.replacement_plan is not None
        ):
            plan = outcome.replacement_plan
            for _ in range(plan.backspaces_to_send):
                if field_chars:
                    field_chars.pop()
            for inj_ch in plan.text_to_inject:
                field_chars.append(inj_ch)
    return "".join(field_chars)


def test_real_time_sentence_autocorrection() -> None:
    """Verify the canonical example from Section 5.1: 'I recieved your mesage.' -> 'I received your message.'"""
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    session = InputSessionManager(engine=engine)
    try:
        result = _type_string(session, "I recieved your mesage.")
        assert result == "I received your message."
    finally:
        rm.close()


def test_capitalisation_and_brand_preservation() -> None:
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    try:
        assert engine.evaluate_token("recieved").replacement_token == "received"
        assert (
            engine.evaluate_token(
                "Recieved", EvaluationContext(is_sentence_start=True)
            ).replacement_token
            == "Received"
        )
        assert engine.evaluate_token("RECIEVED").replacement_token == "RECEIVED"
        assert engine.evaluate_token("THe").replacement_token == "The"
        assert engine.evaluate_token("iphone").replacement_token == "iPhone"
        assert engine.evaluate_token("javascript").replacement_token == "JavaScript"
        assert engine.evaluate_token("i").replacement_token == "I"
    finally:
        rm.close()


def test_contextual_homophones_and_two_word_retroactive() -> None:
    """
    Verify Section 6 contextual intelligence:
    - 'I went too the market.' -> 'I went to the market.'
    - 'better then' -> 'better than'
    - 'over their.' -> 'over there.'
    - 'your welcome ' -> "you're welcome "
    - 'its a ' -> "it's a "
    - 'there house ' -> 'their house '
    """
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    session = InputSessionManager(engine=engine)
    try:
        assert _type_string(session, "I went too the market.") == "I went to the market."
        session.reset_all_state()
        assert _type_string(session, "This is better then that.") == "This is better than that."
        session.reset_all_state()
        assert _type_string(session, "Look over their.") == "Look over there."
        session.reset_all_state()
        assert _type_string(session, "your welcome ") == "You're welcome "
        session.reset_all_state()
        assert _type_string(session, "its a great day.") == "It's a great day."
        session.reset_all_state()
        assert _type_string(session, "We visited there house ") == "We visited their house "
    finally:
        rm.close()


def test_punctuation_assistance() -> None:
    """
    Verify Standard punctuation assistance:
    - Contraction apostrophe restoration ('dont' -> "don't", 'cant' -> "can't", 'im' -> "I'm")
    - Space-before-punctuation transposition ('Hello , world .' -> 'Hello, world.')
    - Double-space to period ('Hello  world' -> 'Hello. World ')
    """
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    session = InputSessionManager(engine=engine)
    try:
        assert _type_string(session, "I dont think cant works.") == "I don't think can't works."
        session.reset_all_state()
        assert _type_string(session, "Hello , world ") == "Hello, world "
        session.reset_all_state()
        assert _type_string(session, "Hello  world ") == "Hello. World "
    finally:
        rm.close()


def test_automatic_sentence_capitalisation_and_abbreviation_guards() -> None:
    """
    Verify automatic sentence capitalisation after '.', '?', '!' and suppression after
    abbreviations ('Mr.', 'Dr.', 'e.g.'), numbers, and code identifiers.
    """
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    session = InputSessionManager(engine=engine)
    try:
        out = _type_string(session, "hello world. how are you? great! thanks ")
        assert out == "Hello world. How are you? Great! Thanks "

        session.reset_all_state()
        # 'Dr.' is a known abbreviation so 'smith' (if lowercase common word 'tall') must NOT be auto-capitalised as a new sentence
        out_abbr = _type_string(session, "We met Dr. tall yesterday.")
        assert out_abbr == "We met Dr. tall yesterday."

        session.reset_all_state()
        out_eg = _type_string(session, "Use tools e.g. python for scripts.")
        assert out_eg == "Use tools e.g. python for scripts."
    finally:
        rm.close()


def _press_backspace(session: InputSessionManager, field: list[str], ts: float) -> object:
    """Simulate one Backspace keypress against a virtual field (list of chars)."""
    outcome = session.handle_key_event(
        KeyEvent(key_name="Backspace", char="", timestamp_ms=ts),
        suppress_delimiter_on_replace=True,
    )
    if outcome.action == KeyAction.PASS_THROUGH:
        if field:
            field.pop()
    elif outcome.replacement_plan is not None:
        for _ in range(outcome.replacement_plan.backspaces_to_send):
            if field:
                field.pop()
        field.extend(outcome.replacement_plan.text_to_inject)
    return outcome


def test_double_backspace_reversal_and_one_shot_suppression() -> None:
    """
    Verify Correction Reversal (double-Backspace gesture):
    1. User types 'I recieved ' -> becomes 'I received '.
    2. FIRST Backspace is an ordinary edit: deletes the space, keeps 'received'.
    3. SECOND consecutive Backspace restores 'I recieved'.
    4. Pressing Space on that same restored instance stays 'I recieved '
       (one-shot suppression is consumed here, not a session-wide pardon).
    5. Typing the same misspelling again as a fresh instance corrects it again.
    6. Once subsequent characters are typed, Backspace is ordinary editing.
    """
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    session = InputSessionManager(engine=engine)
    try:
        field = list(_type_string(session, "I recieved ", base_ts=1000.0))
        assert "".join(field) == "I received "

        # First Backspace: ordinary deletion of the trailing space only.
        first = _press_backspace(session, field, 2000.0)
        assert first.action == KeyAction.PASS_THROUGH
        assert first.reverted_word is None
        assert "".join(field) == "I received"

        # Second consecutive Backspace: deliberate correction reversal.
        second = _press_backspace(session, field, 2100.0)
        assert second.action == KeyAction.SUPPRESS_AND_INJECT
        assert second.reverted_word == "recieved"
        assert "".join(field) == "I recieved"

        # Pressing Space again must NOT re-correct this same restored instance.
        sp_evt = KeyEvent(key_name="Space", char=" ", timestamp_ms=2200.0)
        sp_outcome = session.handle_key_event(sp_evt, suppress_delimiter_on_replace=True)
        assert sp_outcome.action == KeyAction.PASS_THROUGH
        field.append(" ")
        assert "".join(field) == "I recieved "

        # But a later, fresh instance of 'recieved' IS corrected again: a
        # revert is not an implicit "this spelling is correct" declaration.
        field.extend(_type_string(session, "recieved ", base_ts=5000.0))
        assert "".join(field) == "I recieved received "

        # Once subsequent characters are typed, Backspace is ordinary.
        session.reset_all_state()
        field2 = list(_type_string(session, "I mesage x", base_ts=3000.0))
        assert "".join(field2) == "I message x"
        bs2 = session.handle_key_event(
            KeyEvent(key_name="Backspace", char="", timestamp_ms=4000.0),
            suppress_delimiter_on_replace=True,
        )
        assert bs2.action == KeyAction.PASS_THROUGH
        assert bs2.reverted_word is None
    finally:
        rm.close()


def test_regional_spelling_variants_and_golden_corpus_fpr() -> None:
    """
    Verify British vs American English regional enforcement and Golden Corpus FPR < 0.1%.
    """
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    try:
        # In EN_GB, 'colour' and 'organise' are valid in-vocab and untouched
        gb_ctx = EvaluationContext(active_region=RegionFlag.EN_GB)
        assert not engine.evaluate_token("colour", gb_ctx).should_replace
        assert not engine.evaluate_token("organise", gb_ctx).should_replace

        # In EN_US, 'color' and 'organize' are valid in-vocab and untouched
        us_ctx = EvaluationContext(active_region=RegionFlag.EN_US)
        assert not engine.evaluate_token("color", us_ctx).should_replace
        assert not engine.evaluate_token("organize", us_ctx).should_replace

        # Golden corpus gate check
        metrics = run_golden_corpus_regression(DEFAULT_BUNDLED_DIR)
        assert metrics.passed_gate
        assert metrics.false_positive_rate <= 0.001
    finally:
        rm.close()
