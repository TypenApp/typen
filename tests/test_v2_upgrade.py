"""
Typen V2 Upgrade Verification Suite:
1. Inline placeholder predictive typing on Tab (in-word suffix completion + next-word prediction)
   and smart Tab interception in `AutoCorrectDaemon._dispatch_os_key`.
2. AdaptivePersonalLM learning (unigrams, bigrams, trigrams, prefix trie, SQLite persistence,
   and candidate ranking boosts).
3. Personal dictionary priority before lexical guards (PascalCase/camelCase/acronyms), exact
   casing transfer, and in-memory SymSpell fuzzy matching (`Typn` -> `Typen`, `githbu` -> `GitHub`).
4. Dynamic noisy-channel missing-space compound splitter (`thecat` -> `the cat`,
   `dontknow` -> `don't know`, `helloworld` -> `hello world`).
5. Capitalisation consistency after Backspace (unwinding boundary history stack), Tab pass-through,
   and window focus switch when caret probe is unavailable.
6. Hybrid Layer 2 `LocalModelManager` (real RAM detection, phonetic-safe `a/an` & duplicate word
   checks, contextual confusion polish, and candidate rescoring).
7. V2 Lexicon (>450,000 words, SCOWL 100 + full JSON dictionary, suggestible slang, and
   expanded Domain Vocabulary packs with SymSpell fuzzy matching).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.test_core_standard import _press_backspace, _type_string

from autocorrect.ai.local_model_manager import LocalModelManager
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.core.models import EvaluationContext
from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.adaptive_lm import AdaptivePersonalLM
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager
from autocorrect.preferences.sqlite_store import SQLitePreferenceStore
from autocorrect.version import APP_VERSION, BINARY_SCHEMA_VERSION


@pytest.fixture(scope="module")
def resource_manager() -> ResourceManager:
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    rm.load_best_available()
    yield rm
    rm.close()


def test_v2_version_and_full_lexicon_scale(resource_manager: ResourceManager) -> None:
    """Verify Typen V2 version numbers and >400,000 word lexicon scale."""
    assert APP_VERSION == "2.0.0"
    assert BINARY_SCHEMA_VERSION == 2
    bundle = resource_manager.active_bundle
    assert bundle.version == "2.0.0"
    assert bundle.schema_version == 2
    assert bundle.lexicon.word_count > 400_000

    # Modern slang and brands exist in core lexicon
    for word in ("ghosting", "gaslighting", "doomscrolling", "openai", "supabase", "typen"):
        assert bundle.lexicon.lookup(word) is not None, word


def test_personal_dictionary_priority_casing_and_fuzzy_symspell(
    tmp_path: Path, resource_manager: ResourceManager
) -> None:
    """
    Words added to the personal dictionary must:
    - Not be skipped by camelCase/PascalCase or acronym guards.
    - Restore their saved canonical casing when typed all-lowercase.
    - Be corrected TOWARDS when mistyped within edit distance <= 2.
    """
    store = SQLitePreferenceStore(tmp_path / "prefs.sqlite3")
    store.add_custom_word("EnwonTech")
    store.add_custom_word("Zorblax")
    store.add_custom_word("XQZ")
    engine = AutocorrectEngine(resource_manager, preferences=store.overlay)

    # 1. Exact lowercase input restores saved custom casing ('enwontech' -> 'EnwonTech')
    dec_brand = engine.evaluate_token("enwontech", EvaluationContext(is_sentence_start=False))
    assert dec_brand.should_replace
    assert dec_brand.replacement_token == "EnwonTech"

    # 2. Short custom acronym ('xqz' -> 'XQZ') is formatted rather than ignored by acronym guard
    dec_acr = engine.evaluate_token("xqz", EvaluationContext(is_sentence_start=False))
    assert dec_acr.should_replace
    assert dec_acr.replacement_token == "XQZ"

    # 3. Near-miss typo of custom word fuzzy-matches via custom SymSpell index
    dec_fuzzy = engine.evaluate_token("zorblx", EvaluationContext(is_sentence_start=False))
    assert dec_fuzzy.should_replace
    assert dec_fuzzy.replacement_token == "Zorblax"

    dec_fuzzy_title = engine.evaluate_token("Zorblx", EvaluationContext(is_sentence_start=False))
    assert dec_fuzzy_title.should_replace
    assert dec_fuzzy_title.replacement_token == "Zorblax"


def test_domain_vocabulary_packs_symspell_and_brands(tmp_path: Path) -> None:
    """Verify expanded V2 Domain Vocabulary packs and SymSpell fuzzy matching."""
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    rm.set_enabled_domain_packs({"programming", "business"})
    engine = AutocorrectEngine(rm)
    try:
        assert engine.evaluate_token("suapbase").replacement_token == "Supabase"
        assert engine.evaluate_token("anthrpic").replacement_token == "Anthropic"
        assert engine.evaluate_token("shpoify").replacement_token == "Shopify"
        assert engine.evaluate_token("supabase").replacement_token == "Supabase"
        assert engine.evaluate_token("openai").replacement_token == "OpenAI"
    finally:
        rm.close()


@pytest.mark.parametrize(
    ("joined", "expected"),
    [
        ("thecat", "the cat"),
        ("helloworld", "hello world"),
        ("dontknow", "don't know"),
        ("imgoing", "I'm going"),
        ("cantwait", "can't wait"),
        ("goingto", "going to"),
        ("myhouse", "my house"),
        ("thisis", "this is"),
    ],
)
def test_dynamic_missing_space_compound_splitter(
    resource_manager: ResourceManager, joined: str, expected: str
) -> None:
    engine = AutocorrectEngine(resource_manager)
    dec = engine.evaluate_token(joined, EvaluationContext(is_sentence_start=False))
    assert dec.should_replace, joined
    assert dec.replacement_token == expected


def test_capitalisation_after_backspace_and_focus_switch(
    resource_manager: ResourceManager,
) -> None:
    """
    Verify:
    1. Backspacing a period and space ('Hello. ' -> 'Hello') rewinds the sentence
       capitaliser to mid-sentence so the next word is NOT capitalised.
    2. Switching window focus when the OS caret probe is attempted but returns None
       suppresses sentence-start capitalisation instead of capitalising mid-sentence.
    3. Pressing Tab without an active prediction does not force sentence-start capitalisation.
    """
    engine = AutocorrectEngine(resource_manager)
    session = InputSessionManager(engine=engine)
    session.configure_features(enable_auto_space_after_sentence=False)

    # 1. Type "hello there. ", then Backspace twice to delete ' ' and '.', then type " friend "
    field = list(_type_string(session, "hello there. ", base_ts=100.0))
    assert "".join(field) == "Hello there. "
    assert session.capitaliser.is_sentence_start

    _press_backspace(session, field, 500.0)  # deletes ' '
    _press_backspace(session, field, 550.0)  # deletes '.' and restores 'there' into buffer
    assert "".join(field) == "Hello there"
    assert not session.capitaliser.is_sentence_start

    # Complete 'there' with Space, then type 'friend ' -> must stay lowercase 'friend'
    field.extend(_type_string(session, " friend ", base_ts=700.0))
    assert "".join(field) == "Hello there friend "

    # 2. Focus switch where caret probe was attempted on a live window but returned None
    session.on_focus_changed(
        FocusContext(process_name="notepad.exe"),
        caret_text_before=None,
        caret_probe_attempted=True,
    )
    assert not session.capitaliser.is_sentence_start
    assert _type_string(session, "continuing mid sentence ") == "continuing mid sentence "

    # 3. Tab key pass-through does not force sentence start
    session.reset_all_state()
    _type_string(session, "Hello ")
    session.handle_key_event(KeyEvent(key_name="Tab", char="\t", timestamp_ms=1000.0))
    assert not session.capitaliser.is_sentence_start


def test_inline_predictive_tab_suffix_and_next_word_and_adaptive_learning(
    tmp_path: Path, resource_manager: ResourceManager
) -> None:
    """
    Verify:
    1. Typing a word prefix ('univers') produces an inline suffix prediction ('ity'),
       and pressing Tab accepts it ('university ').
    2. Typing 'Thank ' produces a next-word prediction ('you'), and pressing Tab
       injects 'you '.
    3. AdaptivePersonalLM learns a user's custom bigram ('project' -> 'falcon') after
       2 uses and predicts 'falcon' the next time 'project ' is typed.
    """
    store = SQLitePreferenceStore(tmp_path / "prefs.sqlite3")
    adaptive = AdaptivePersonalLM()
    store.overlay.set_personal_lm_scorer(adaptive.score_boost)
    engine = AutocorrectEngine(resource_manager, preferences=store.overlay)
    session = InputSessionManager(engine=engine, adaptive_lm=adaptive)

    # 1. In-word suffix completion on Tab
    for idx, ch in enumerate("univers"):
        session.handle_key_event(KeyEvent(key_name=ch, char=ch, timestamp_ms=float(idx * 40)))
    assert session.has_active_prediction
    pred = session.active_prediction
    assert pred is not None
    assert pred.mode == "SUFFIX"
    assert pred.full_word.lower().startswith("univers")

    tab_out = session.handle_key_event(
        KeyEvent(key_name="Tab", char="\t", timestamp_ms=500.0),
        suppress_delimiter_on_replace=True,
    )
    assert tab_out.action == KeyAction.SUPPRESS_AND_INJECT
    assert tab_out.reason_tag == "PREDICTIVE_TAB"
    assert tab_out.replacement_plan is not None
    assert tab_out.replacement_plan.text_to_inject == f"{pred.display_text} "

    # 2. Next-word prediction after 'Thank '
    session.reset_all_state()
    _type_string(session, "Thank ")
    assert session.has_active_prediction
    next_pred = session.active_prediction
    assert next_pred is not None
    assert next_pred.mode == "NEXT_WORD"
    assert next_pred.display_text == "you"

    tab_next = session.handle_key_event(
        KeyEvent(key_name="Tab", char="\t", timestamp_ms=1000.0),
        suppress_delimiter_on_replace=True,
    )
    assert tab_next.action == KeyAction.SUPPRESS_AND_INJECT
    assert tab_next.replacement_plan is not None
    assert tab_next.replacement_plan.text_to_inject == "you "

    # 3. Eagerly learn personal phrase 'project zephyr'
    session.reset_all_state()
    _type_string(session, "project zephyr. ")
    _type_string(session, "project zephyr. ")
    _type_string(session, "We love project ")
    learned_pred = session.active_prediction
    assert learned_pred is not None
    assert learned_pred.mode == "NEXT_WORD"
    assert learned_pred.display_text.lower() == "zephyr"

    # Flush adaptive LM to SQLite and reload into a fresh instance
    u_dirty, n_dirty = adaptive.drain_dirty()
    store.flush_adaptive_lm(u_dirty, n_dirty)
    adaptive2 = AdaptivePersonalLM()
    u_loaded, n_loaded = store.load_adaptive_lm()
    adaptive2.load_persisted(u_loaded, n_loaded)
    assert adaptive2.score_boost("zephyr", prev1_lower="project") > 0.5


def test_daemon_smart_tab_hook_interception(tmp_path: Path) -> None:
    """Verify AutoCorrectDaemon._dispatch_os_key suppresses Tab only when a prediction is active."""
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=False, attach_hooks=False)
    try:
        # When no prediction is active, Tab passes through
        tab_ev = KeyEvent(key_name="Tab", char="\t", timestamp_ms=100.0)
        assert d._dispatch_os_key(tab_ev) == KeyAction.PASS_THROUGH

        # Ensure the worker queue has drained the passive Tab before typing on the worker directly
        d.dispatcher.run_sync(lambda: None)

        # Type 'Thank ' on worker so next-word prediction ('you') becomes active
        for i, ch in enumerate("Thank "):
            name = "Space" if ch == " " else ch
            d._handle_key_on_worker(KeyEvent(key_name=name, char=ch, timestamp_ms=float(200 + i * 30)))
        assert d.session.active_prediction is not None, (
            f"adaptive={d.session._adaptive_lm}, focus={d.session._focus_context}, "
            f"last_word={d.session._last_completed_word!r}, prec_space={d.session._preceded_by_space}, "
            f"buf={d.session.word_buffer.current_word!r}, state={d.session.word_buffer.state}"
        )
        assert d.session.has_active_prediction

        # Now _dispatch_os_key intercepts plain Tab with SUPPRESS_AND_INJECT
        assert d._dispatch_os_key(tab_ev) == KeyAction.SUPPRESS_AND_INJECT
    finally:
        d.stop()


def test_layer2_local_model_manager_phonetic_safety_and_confusion_polish() -> None:
    """Verify Layer 2 LocalModelManager never turns 'a user' into 'an user' or deletes 'had had'."""
    ai = LocalModelManager(is_pro_entitled=True)
    hw = ai.detect_hardware_profile()
    assert hw.total_ram_mb >= 1024

    # 'a user' and 'had had' are valid English and must NOT be corrupted
    assert ai.evaluate_sentence("She is a user who had had enough.", triggered_by_hotkey=True) is None

    # Phonetic vowel sound ('a hour' -> 'an hour') and confusion ('your welcome' -> "you're welcome")
    sugg = ai.evaluate_sentence(
        "Your welcome to wait for a hour.",
        triggered_by_hotkey=True,
    )
    assert sugg is not None
    assert sugg.suggested_sentence == "You're welcome to wait for an hour."
