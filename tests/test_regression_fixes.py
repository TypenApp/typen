"""
Regression tests for the reported real-world failures:
- Corrections must fully replace the original token (no 'old + new' merged text).
- Sentence-start capitalisation, including standalone 'i' -> 'I'.
- Double-Backspace (not single) correction reversal.
- Double-space period must produce 'word. ' and never 'word .' / 'word.. '.
- A revert does not pardon later fresh instances of the same misspelling.
- Custom dictionary: view / manually add / delete controls correction behaviour.
- Reported misses: 'montly' -> 'monthly' (not 'mostly'), 'becos' -> 'because',
  'ofa' -> 'of a', 'mispelled', 'seperatly'; valid words must be left alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import EvaluationContext
from autocorrect.input.ports import KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore
from autocorrect.sandbox import SANDBOX_HTML
from autocorrect.ui.settings_main import SettingsController
from tests.test_core_standard import _press_backspace, _type_string


@pytest.fixture(scope="module")
def engine() -> AutocorrectEngine:
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    yield AutocorrectEngine(rm)
    rm.close()


@pytest.fixture()
def session(engine: AutocorrectEngine) -> InputSessionManager:
    return InputSessionManager(engine=engine)


def test_user_reported_sentence_end_to_end(session: InputSessionManager) -> None:
    """The exact reported sentence must come out clean, with no merged tokens."""
    result = _type_string(
        session, "i receive montly subs becos i am a beast ofa man. "
    )
    assert result == "I receive monthly subs because I am a beast of a man. "
    # No conjoined-twin residue anywhere.
    for residue in ("iI", "rReceive", "toTo", "becos", "montly", "ofa man", " ."):
        assert residue not in result


def test_replacement_fully_replaces_original(session: InputSessionManager) -> None:
    """Every correction swaps the whole token; nothing of the typo survives."""
    result = _type_string(session, "i recieved teh mesage becos montly ")
    assert result == "I received the message because monthly "


def test_sentence_start_capitalisation(session: InputSessionManager) -> None:
    assert _type_string(session, "hello world ") == "Hello world "
    session.reset_all_state()
    assert _type_string(session, "i am here. i went home ") == "I am here. I went home "
    session.reset_all_state()
    # Start-of-text misspelling is corrected AND capitalised as one replacement.
    assert _type_string(session, "recieved it ") == "Received it "


def test_double_space_period(session: InputSessionManager) -> None:
    result = _type_string(session, "this is a test  next ")
    assert result == "This is a test. Next "
    assert " ." not in result


def test_double_space_after_period_never_doubles_period(
    session: InputSessionManager,
) -> None:
    result = _type_string(session, "Hello.  Next sentence ")
    assert result == "Hello.  Next sentence "
    assert ".." not in result


def test_space_before_period_is_normalised(session: InputSessionManager) -> None:
    result = _type_string(session, "a beast of a man . ")
    assert result == "A beast of a man. "


def test_first_backspace_never_reverts(session: InputSessionManager) -> None:
    field = list(_type_string(session, "I dont "))
    assert "".join(field) == "I don't "
    first = _press_backspace(session, field, 9000.0)
    assert first.action == KeyAction.PASS_THROUGH
    assert "".join(field) == "I don't"  # only the space was deleted
    second = _press_backspace(session, field, 9100.0)
    assert second.action == KeyAction.SUPPRESS_AND_INJECT
    assert "".join(field) == "I dont"


def test_backspace_type_backspace_does_not_revert(
    session: InputSessionManager,
) -> None:
    """An intervening keystroke disarms the gesture: later Backspaces edit."""
    field = list(_type_string(session, "I recieved "))
    assert "".join(field) == "I received "
    _press_backspace(session, field, 9000.0)  # deletes the space
    assert "".join(field) == "I received"
    typed = session.handle_key_event(
        KeyEvent(key_name="x", char="x", timestamp_ms=9100.0),
        suppress_delimiter_on_replace=True,
    )
    assert typed.action == KeyAction.PASS_THROUGH
    field.append("x")
    back1 = _press_backspace(session, field, 9200.0)
    back2 = _press_backspace(session, field, 9300.0)
    assert back1.reverted_word is None and back2.reverted_word is None
    assert "".join(field) == "I receive"


@pytest.mark.parametrize(
    ("typo", "expected"),
    [
        ("montly", "monthly"),
        ("becos", "because"),
        ("becuse", "because"),
        ("mispelled", "misspelled"),
        ("seperatly", "separately"),
        ("seperately", "separately"),
        ("grammer", "grammar"),
        ("subcription", "subscription"),
        ("recieved", "received"),
        ("mesage", "message"),
        ("teh", "the"),
        ("adress", "address"),
        ("langage", "language"),
        ("writting", "writing"),
    ],
)
def test_common_typos_correct(
    engine: AutocorrectEngine, typo: str, expected: str
) -> None:
    decision = engine.evaluate_token(typo)
    assert decision.should_replace, typo
    assert decision.replacement_token == expected, typo


@pytest.mark.parametrize(
    ("fused", "expected"),
    [("ofa", "of a"), ("alot", "a lot"), ("aswell", "as well"), ("thankyou", "thank you")],
)
def test_missing_space_corrections(
    engine: AutocorrectEngine, fused: str, expected: str
) -> None:
    decision = engine.evaluate_token(fused)
    assert decision.should_replace
    assert decision.replacement_token == expected


@pytest.mark.parametrize(
    "valid",
    [
        "monthly", "subscriptions", "subscription", "subs", "beast", "because",
        "separately", "misspelled", "receive", "received", "man", "the",
        "hello", "world", "colour", "organise", "computer", "python",
        "code", "coding", "json", "browser", "settings",
        "useState", "getElementById", "config.json", "hello_world",
        # Comprehensive external lexicon (ESDB/SCOWL) coverage: real English
        # words that a hand-typed list would inevitably miss.
        "aardvark", "photosynthesis", "serendipity", "unprecedented",
        "entrepreneur", "questionnaire", "chrysanthemum", "rhythm",
        "conscience", "miscellaneous", "fluorescent", "kaleidoscope",
        "floccinaucinihilipilification", "pneumonia", "silhouette",
    ],
)
def test_valid_words_are_never_rewritten(engine: AutocorrectEngine, valid: str) -> None:
    ctx = EvaluationContext(is_sentence_start=False)
    decision = engine.evaluate_token(valid, ctx)
    assert not decision.should_replace, valid


def test_montly_is_monthly_not_mostly(engine: AutocorrectEngine) -> None:
    decision = engine.evaluate_token("montly")
    assert decision.replacement_token == "monthly"
    assert decision.replacement_token != "mostly"


def test_custom_dictionary_add_view_delete(tmp_path: Path) -> None:
    """Settings controller: user can see, manually add, and delete words."""
    controller = SettingsController(tmp_path, use_memory_keyring=True)
    assert controller.list_custom_words() == []
    controller.add_custom_word("montly")
    controller.add_custom_word("becos")
    assert controller.list_custom_words() == ["becos", "montly"]
    controller.delete_custom_word("montly")
    assert controller.list_custom_words() == ["becos"]


def test_custom_dictionary_controls_correction(tmp_path: Path) -> None:
    """Only an explicit dictionary entry pardons a word; deleting re-enables it."""
    store = SQLitePreferenceStore(tmp_path / "prefs.sqlite3")
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm, preferences=store.overlay)
    try:
        assert engine.evaluate_token("montly").replacement_token == "monthly"
        store.add_custom_word("montly")
        assert not engine.evaluate_token("montly").should_replace
        store.remove_custom_word("montly")
        assert engine.evaluate_token("montly").replacement_token == "monthly"
    finally:
        rm.close()


def test_comprehensive_data_driven_lexicon() -> None:
    """The shipped dictionary must be a real spell-checker database (ESDB),
    not the hand-typed core list: >100k attested words, with corpus-attested
    misspellings never validated."""
    import json

    manifest = json.loads(
        (DEFAULT_BUNDLED_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["word_count"] > 100_000

    from pipeline.external_sources import load_external_lexicon

    external = load_external_lexicon()
    if not external:
        pytest.skip("External lexicon unavailable (offline build mode)")
    assert len(external) > 100_000
    assert "monthly" in external and "aardvark" in external
    # Misspellings must never be validated by corpus attestation.
    for typo in ("recieved", "teh", "montly", "becos", "seperatly"):
        assert typo not in external


def test_sandbox_prevents_default_synchronously_before_awaiting_engine() -> None:
    """Guard the browser bug: preventDefault must precede the async round-trip,
    keys must be serialised, and pass-through text is inserted by our code."""
    keydown = SANDBOX_HTML.index("editor.addEventListener('keydown'")
    prevent = SANDBOX_HTML.index("e.preventDefault();", keydown)
    process = SANDBOX_HTML.index("enqueueKey(() => processKey(keyName, charStr));", keydown)
    assert prevent < process  # synchronous suppression happens first
    assert "let keyQueue = Promise.resolve();" in SANDBOX_HTML
    assert "applyPassThrough(keyName, charStr)" in SANDBOX_HTML
    # Dictionary management UI is present in the sandbox.
    assert 'id="dict-input"' in SANDBOX_HTML
    assert "/api/dictionary/add" in SANDBOX_HTML
    assert "/api/dictionary/delete" in SANDBOX_HTML
    assert "/api/dictionary/dismiss" in SANDBOX_HTML
    assert 'id="dict-suggested-list"' in SANDBOX_HTML


@pytest.mark.parametrize(
    ("raw_text", "expected_text"),
    [
        ("You're welcome. Raw eggs is best. ", "You're welcome. Raw eggs are best. "),
        ("your welcome. raw eggs is best. ", "You're welcome. Raw eggs are best. "),
        ("The dogs was barking. ", "The dogs were barking. "),
        ("My friends has arrived. ", "My friends have arrived. "),
        ("They was happy and we is ready. ", "They were happy and we are ready. "),
        ("He dont know what she have done. ", "He doesn't know what she has done. "),
        ("I bought two egg and three book. ", "I bought two eggs and three books. "),
        ("These book are great. ", "These books are great. "),
        ("This books are great. ", "This book is great. "),
        ("I ate a egg and an banana. ", "I ate an egg and a banana. "),
        ("I should of went home. ", "I should have gone home. "),
        ("There is many reasons for this. ", "There are many reasons for this. "),
        ("You and I is ready. ", "You and I are ready. "),
    ],
)
def test_standard_tier_grammar_subject_verb_and_plurals(
    session: InputSessionManager, raw_text: str, expected_text: str
) -> None:
    session.reset_all_state()
    assert _type_string(session, raw_text) == expected_text


@pytest.mark.parametrize(
    "valid_sentence",
    [
        "One of the raw eggs is cracked. ",
        "Eating raw eggs is risky. ",
        "Physics is hard and the news is good. ",
        "If he were here he would know. ",
    ],
)
def test_grammar_false_positive_guards(
    session: InputSessionManager, valid_sentence: str
) -> None:
    session.reset_all_state()
    assert _type_string(session, valid_sentence) == valid_sentence


def test_interrupted_double_backspace_and_space_space_backspace_never_revert(
    session: InputSessionManager,
) -> None:
    """
    Verify:
    1. `space + space + backspace` converts double-space to `. ` and then
       deletes characters normally without ever reverting the corrected word.
    2. `backspace + space + backspace` (interrupted double-Backspace) cancels
       the revert and never produces a botched replacement.
    3. `backspace + space + space` after a word still triggers double-space period.
    """
    # 1. Word correction followed by double-space then Backspaces
    session.reset_all_state()
    field = list(_type_string(session, "I recieved  ", base_ts=1000.0))
    assert "".join(field) == "I received. "
    b1 = _press_backspace(session, field, 2000.0)
    assert b1.reverted_word is None
    assert "".join(field) == "I received."
    b2 = _press_backspace(session, field, 2080.0)
    assert b2.reverted_word is None
    assert "".join(field) == "I received"

    # 2. Interrupted double-Backspace: Backspace #1, then Space, then Backspace
    session.reset_all_state()
    field2 = list(_type_string(session, "I recieved ", base_ts=3000.0))
    assert "".join(field2) == "I received "
    _press_backspace(session, field2, 3800.0)  # deletes trailing space
    assert "".join(field2) == "I received"
    # Interrupt with Space
    sp = session.handle_key_event(
        KeyEvent(key_name="Space", char=" ", timestamp_ms=3900.0),
        suppress_delimiter_on_replace=True,
    )
    assert sp.action == KeyAction.PASS_THROUGH
    field2.append(" ")
    assert "".join(field2) == "I received "
    # Subsequent Backspace (and even a second one) must NOT revert
    after1 = _press_backspace(session, field2, 4000.0)
    after2 = _press_backspace(session, field2, 4080.0)
    assert after1.reverted_word is None and after2.reverted_word is None
    assert "".join(field2) == "I receive"

    # 3. Backspace deleting space, followed by Space + Space -> '. '
    session.reset_all_state()
    field3 = list(_type_string(session, "I recieved ", base_ts=5000.0))
    assert "".join(field3) == "I received "
    _press_backspace(session, field3, 5600.0)
    assert "".join(field3) == "I received"
    field3.extend(_type_string(session, "  ", base_ts=5700.0))
    assert "".join(field3) == "I received. "


def test_revert_notes_suggested_dictionary_word_without_auto_pardoning(
    tmp_path: Path,
) -> None:
    """
    On double-Backspace revert, the word must be quietly added to the
    suggested 'Add to Dictionary' list without a popup and without
    pardoning subsequent instances until the user accepts the suggestion.
    """
    store = SQLitePreferenceStore(tmp_path / "prefs.sqlite3")
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm, preferences=store.overlay)
    session = InputSessionManager(engine=engine)
    try:
        field = list(_type_string(session, "I recieved ", base_ts=1000.0))
        assert "".join(field) == "I received "

        # Double-Backspace to revert 'received' -> 'recieved'
        _press_backspace(session, field, 1800.0)
        rev = _press_backspace(session, field, 1900.0)
        assert rev.reverted_word == "recieved"
        assert "".join(field) == "I recieved"

        # 'recieved' is now in suggested_words, NOT in custom_words
        suggested = store.list_suggested_words()
        assert len(suggested) == 1
        assert suggested[0]["word"] == "recieved"
        assert suggested[0]["corrected_to"] == "received"
        assert suggested[0]["revert_count"] == 1
        assert store.list_custom_words() == []

        # Subsequent fresh instance is STILL corrected because user hasn't accepted it
        session.reset_all_state()
        assert _type_string(session, "I recieved ") == "I received "

        # Accepting the suggestion promotes it to custom_words and clears suggestion
        store.accept_suggested_word("recieved")
        assert store.list_custom_words() == ["recieved"]
        assert store.list_suggested_words() == []

        # Now subsequent instances are preserved as typed
        session.reset_all_state()
        assert _type_string(session, "I recieved ") == "I recieved "
    finally:
        rm.close()

