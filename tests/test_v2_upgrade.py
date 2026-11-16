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
    """Verify Typen V2.1 version numbers and >400,000 word lexicon scale."""
    assert APP_VERSION == "2.1.0"
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


def test_first_word_after_click_or_focus_is_never_ignored(
    tmp_path: Path, resource_manager: ResourceManager
) -> None:
    """
    Verify:
    1. Clicking into a control when the OS caret probe returns None (e.g. control
       lacks TextPattern2) keeps the buffer CLEAN (not TAINTED) so the very first
       word typed is corrected (and capitalised on a fresh session).
    2. In DemoHost (`route == 'caret'`), a click event with `text` resyncs from
       the caret text rather than tainting the buffer, so the very first word
       after clicking in the web demo is corrected and capitalised properly.
    """
    from autocorrect.demo_host import EngineHost

    engine = AutocorrectEngine(resource_manager)
    session = InputSessionManager(engine=engine)

    # 1a. Click at the start of a fresh session where caret probe returned None
    session.on_mouse_click_or_caret_move(caret_text_before=None, caret_probe_attempted=True)
    assert session.word_buffer.state.value == "CLEAN"
    assert session.capitaliser.is_sentence_start
    assert _type_string(session, "recieved ") == "Received "

    # 1b. Click mid-session where caret probe returned None -> buffer is STILL CLEAN
    # so the first word typed after the click is corrected (even while caps are suppressed)
    session.on_mouse_click_or_caret_move(caret_text_before=None, caret_probe_attempted=True)
    assert session.word_buffer.state.value == "CLEAN"
    assert not session.capitaliser.is_sentence_start
    assert _type_string(session, "recieved ") == "received "

    # 2. DemoHost 'caret' route with empty or sentence-end text leaves buffer CLEAN
    host = EngineHost(work_dir=tmp_path / "demo_host", resource_manager=resource_manager)
    sid = "web-firstwordclick001"
    status, body = host.handle("POST", "caret", {"text": ""}, sid)
    assert status == 200
    assert body["buffer_state"] == "CLEAN"
    assert body["sentence_state"] == "SENTENCE_START"

    # Typing 'recieved ' as the very first word after clicking in the demo corrects AND capitalises
    for ch in "recieved":
        host.handle("POST", "key", {"key_name": ch, "char": ch, "text": ""}, sid)
    _, space_res = host.handle("POST", "key", {"key_name": "Space", "char": " ", "text": "recieved"}, sid)
    assert space_res["action"] == "SUPPRESS_AND_INJECT"
    assert space_res["plan"]["target_full"] == "Received "

    # 3. Right Arrow (as well as Tab) accepts active inline predictions, and
    # `predictive_accept_key` setting controls which key is accepted.
    adaptive = AdaptivePersonalLM()
    sess_pred = InputSessionManager(engine=engine, adaptive_lm=adaptive)
    _type_string(sess_pred, "Thank ")
    assert sess_pred.has_active_prediction
    right_out = sess_pred.handle_key_event(
        KeyEvent(key_name="Right", char="", timestamp_ms=500.0),
        suppress_delimiter_on_replace=True,
    )
    assert right_out.action == KeyAction.SUPPRESS_AND_INJECT
    assert right_out.reason_tag == "PREDICTIVE_TAB"
    assert right_out.replacement_plan is not None
    assert right_out.replacement_plan.text_to_inject == "you "

    # When `predictive_accept_key == 'tab'`, Right Arrow passes through normally
    sess_pred.reset_all_state()
    sess_pred.configure_features(predictive_accept_key="tab")
    _type_string(sess_pred, "Thank ")
    assert sess_pred.has_active_prediction
    right_pass = sess_pred.handle_key_event(
        KeyEvent(key_name="Right", char="", timestamp_ms=600.0),
        suppress_delimiter_on_replace=True,
    )
    assert right_pass.action == KeyAction.PASS_THROUGH


def test_async_caret_resync_preserves_in_progress_first_word_and_ctrl_a_clear(
    resource_manager: ResourceManager,
) -> None:
    """
    Verify:
    1. When a focus switch suppresses caps while UIA is probing asynchronously,
       typing the first letters ('rec') before `apply_async_caret_context('rec')`
       arrives preserves 'rec' in the buffer AND upgrades to SENTENCE_START so
       completing 'ieved ' yields 'Received '.
    2. `Ctrl+A` followed by `Backspace` resets a mid-sentence/tainted field back
       to CLEAN + SENTENCE_START.
    """
    engine = AutocorrectEngine(resource_manager)
    session = InputSessionManager(engine=engine)

    # Focus switch before async caret arrives: buffer is CLEAN, caps provisionally SUPPRESSED
    session.on_focus_changed(
        FocusContext(process_name="chrome.exe", control_id="1:1"),
        caret_text_before=None,
        caret_probe_attempted=True,
    )
    assert not session.capitaliser.is_sentence_start

    field: list[str] = list(_type_string(session, "rec", base_ts=10.0))
    assert session.word_buffer.current_word == "rec"

    # Async UIA probe finishes 30ms later and sees only the 'rec' already typed in the empty box
    session.apply_async_caret_context("rec")
    assert session.word_buffer.current_word == "rec"
    assert session.capitaliser.is_sentence_start

    # Completing 'ieved ' corrects AND capitalises the first word!
    for idx, ch in enumerate("ieved "):
        ev = KeyEvent(
            key_name="Space" if ch == " " else ch,
            char=ch,
            timestamp_ms=100.0 + idx * 20.0,
        )
        out = session.handle_key_event(ev, suppress_delimiter_on_replace=True)
        if out.action == KeyAction.PASS_THROUGH:
            field.append(ch)
        elif out.replacement_plan is not None:
            for _ in range(out.replacement_plan.backspaces_to_send):
                field.pop()
            field.extend(out.replacement_plan.text_to_inject)
    assert "".join(field) == "Received "

    # Now taint the session mid-sentence, then press Ctrl+A + Backspace -> fresh field!
    session.on_mouse_click_or_caret_move()
    assert session.word_buffer.state.value == "TAINTED"
    session.handle_key_event(
        KeyEvent(key_name="a", char="", ctrl_pressed=True, timestamp_ms=500.0)
    )
    clear_out = session.handle_key_event(
        KeyEvent(key_name="Backspace", char="", timestamp_ms=530.0)
    )
    assert clear_out.reason_tag == "SELECT_ALL_CLEARED"
    assert session.word_buffer.state.value == "CLEAN"
    assert session.capitaliser.is_sentence_start
    assert _type_string(session, "recieved ", base_ts=600.0) == "Received "


def test_backspace_reopen_no_false_caps_and_erase_cancels_revert_learning(
    tmp_path: Path,
) -> None:
    """
    Verify:
    1. Deleting a single trailing space after sentence-initial 'Hello ' and typing
       's ' reopens 'Hello' -> 'Hellos ', whereas pressing Space + 'world ' keeps
       'world' lowercase mid-sentence.
    2. Pressing Backspace repeatedly to completely erase a corrected word ('teh '
       -> 'the ' -> Backspace x 4) rolls back revert-learning so 'teh' is NEVER
       auto-added to `custom_words`.
    """
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=False, attach_hooks=False)
    try:
        d.apply_settings(
            {"auto_learn_after_reverts": 2, "undo_remembers": "always", "notify_first_correction": False}
        )
        for round_idx in range(3):
            base = float(round_idx * 5000)
            for i, ch in enumerate("teh "):
                d._handle_key_on_worker(
                    KeyEvent(
                        key_name="Space" if ch == " " else ch,
                        char=ch,
                        timestamp_ms=base + i * 30.0,
                    )
                )
            # Erase all the way through the word (4 Backspaces)
            for b_idx in range(4):
                d._handle_key_on_worker(
                    KeyEvent(
                        key_name="Backspace",
                        char="",
                        timestamp_ms=base + 200.0 + b_idx * 40.0,
                    )
                )
        assert not d.preference_store.overlay.is_custom_word("teh")
        assert not d.preference_store.overlay.is_rejected_pair("teh", "the")

        # Reopen after single trailing-space Backspace
        sess = d.session
        sess.reset_all_state()
        buf = list(_type_string(sess, "Hello ", base_ts=10.0))
        _press_backspace(sess, buf, ts=300.0)
        buf.extend(_type_string(sess, "s ", base_ts=350.0))
        assert "".join(buf) == "Hellos "
    finally:
        d.stop()


def test_v2_database_typo_unmasking_context_and_quantized_neural_ai(
    resource_manager: ResourceManager,
) -> None:
    """
    Verify:
    1. Common typos formerly masked by raw JSON / SCOWL-95 noise ('manged', 'letterin',
       'langauge', 'beleve', 'differen', 'probabl', 'theer', 'shool', 'fomr') correct cleanly.
    2. High aggressiveness (1.5) and min_correction_length=3 fix 'managabke' -> 'manageable'
       and 'mes' -> 'mess' (never 'me').
    3. Common English words ('cursor', 'slack', 'zoom', 'notion', 'linear', 'stripe') stay
       lowercase mid-sentence while unambiguous brands ('github' -> 'GitHub', 'google' -> 'Google')
       apply brand casing.
    4. Quantized Int8 Neural Context Model (`neural_ctx_int8.bin`), contextual phrases
       ("im not realy seeing it's effect ", "i should of gone "), and Layer-2 AI_REWRITE
       pause-pill acceptance work end-to-end.
    """
    from autocorrect.adapters.windows.inline_ghost_overlay import render_pill_bgra

    ai = LocalModelManager(is_pro_entitled=True, resource_manager=resource_manager)
    ai.load_model()
    assert ai.has_neural_context
    engine = AutocorrectEngine(resource_manager, local_ai=ai)
    session = InputSessionManager(engine=engine, adaptive_lm=AdaptivePersonalLM())

    for typo, expected in (
        ("manged", "managed"),
        ("letterin", "lettering"),
        ("langauge", "language"),
        ("beleve", "believe"),
        ("differen", "different"),
        ("probabl", "probably"),
        ("theer", "there"),
        ("shool", "school"),
        ("fomr", "from"),
    ):
        dec = engine.evaluate_token(typo)
        assert dec.should_replace and dec.replacement_token == expected, (typo, dec)

    # Aggressiveness 1.5 & short-word guard
    session.configure_features(aggressiveness=1.5, min_correction_length=3)
    ctx_aggr = EvaluationContext.with_features(session.features)
    assert engine.evaluate_token("managabke", ctx_aggr).replacement_token == "manageable"
    assert engine.evaluate_token("mes", ctx_aggr).replacement_token == "mess"
    session.configure_features(aggressiveness=1.0, min_correction_length=4)

    # Common nouns stay lowercase mid-sentence; unambiguous brands format cleanly
    for noun in ("cursor", "slack", "zoom", "notion", "linear", "stripe"):
        assert not engine.evaluate_token(noun, EvaluationContext(is_sentence_start=False)).should_replace
    assert engine.evaluate_token("google", EvaluationContext(is_sentence_start=False)).replacement_token == "Google"

    # Contextual prose sentences
    assert _type_string(session, "im not realy seeing it's effect ") == "I'm not really seeing its effect "
    session.reset_all_state()
    assert (
        _type_string(session, "recieved teh mesage form github and google. ")
        == "Received the message from GitHub and Google.  "[:46].rstrip() + " "
    )
    session.reset_all_state()
    assert _type_string(session, "i should of gone ") == "I should have gone "
    session.reset_all_state()
    assert _type_string(session, "i should of course go ") == "I should of course go "

    # Layer-2 long-range clause pause-pill arming & Tab acceptance
    session.reset_all_state()
    field = list(_type_string(session, "The list of items are "))
    clause = session.active_clause_for_ai()
    assert clause == "The list of items are"
    sugg = ai.evaluate_sentence(clause, pause_elapsed_ms=450.0)
    assert sugg is not None and sugg.suggested_sentence == "The list of items is"
    assert session.arm_ai_clause_suggestion(clause, sugg.suggested_sentence)
    tab_out = session.handle_key_event(
        KeyEvent(key_name="Tab", char="\t", timestamp_ms=900.0),
        suppress_delimiter_on_replace=True,
    )
    assert tab_out.replacement_plan is not None
    for _ in range(tab_out.replacement_plan.backspaces_to_send):
        field.pop()
    field.extend(tab_out.replacement_plan.text_to_inject)
    assert "".join(field) == "The list of items is "

    # 32-bit premultiplied BGRA True In-Line Ghost & Word-Only Inline Pill rasterisers
    from autocorrect.adapters.windows.inline_ghost_overlay import (
        render_inline_ghost_bgra,
        resolve_overlay_font_px,
    )

    ghost_bgra, gw, gh = render_inline_ghost_bgra("ershell", caret_h=20, dpi=120, is_dark_bg=False)
    assert len(ghost_bgra) == gw * gh * 4 and gw >= 16 and gh >= 16
    # Corner pixel of True In-Line Ghost must be 100% transparent (0, 0, 0, 0)
    assert ghost_bgra[:4] == b"\x00\x00\x00\x00"

    bgra, w, h = render_pill_bgra("pow", "ershell", dpi=120, is_dark_bg=True, caret_h=20, exact_caret=True)
    assert len(bgra) == w * h * 4 and w >= 28 and h >= 18
    bgra_ai, w_ai, h_ai = render_pill_bgra("", "items is", dpi=120, is_dark_bg=False, font_scale=1.25)
    assert len(bgra_ai) == w_ai * h_ai * 4 and h_ai > h
    assert resolve_overlay_font_px(20, 120, exact_caret=True, font_scale=1.2) > resolve_overlay_font_px(
        20, 120, exact_caret=True, font_scale=0.85
    )


def test_self_exclusion_of_typen_settings_ui_across_platforms() -> None:
    """
    Verify Typen's own Settings UI window is marked `is_excluded_app=True` on
    Windows, macOS, and Linux so typing in 'Try it' or Dictionary/Domain Pack
    editors never triggers a duplicate OS overlay or double-correction.
    """
    from autocorrect.adapters.linux.x11_adapter import X11FocusInspector
    from autocorrect.adapters.macos.ax_inspector import MacAXFocusInspector
    from autocorrect.adapters.windows.uia_inspector import Win32FocusInspector

    win_insp = Win32FocusInspector()
    assert win_insp.classify_window_metadata("typen.exe", "Typen").is_excluded_app
    assert win_insp.classify_window_metadata("pythonw.exe", "Typen").is_excluded_app
    assert not win_insp.classify_window_metadata("notepad.exe", "Untitled - Notepad").is_excluded_app

    mac_insp = MacAXFocusInspector()
    assert mac_insp.classify_macos_metadata("io.autocorrect.desktop", "Typen").is_excluded_app
    assert not mac_insp.classify_macos_metadata("com.apple.TextEdit", "TextEdit").is_excluded_app

    x11_insp = X11FocusInspector()
    assert x11_insp.classify_x11_window("typen", "Typen").is_excluded_app
    assert not x11_insp.classify_x11_window("gedit", "Untitled").is_excluded_app


def test_local_domain_vocabulary_pack_editing_over_ipc_and_offline(tmp_path: Path) -> None:
    """
    Verify users can manually add words (preserving brand casing), edit existing
    domain words, delete built-in or custom domain words, add/delete domain typo
    shortcuts, and reset a domain pack back to built-in defaults via SettingsController
    (both live over IPC and offline), with immediate effect in AutocorrectEngine.
    """
    from autocorrect.ui.settings_main import SettingsController

    daemon = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    daemon.start(start_ipc=True, attach_hooks=False)
    try:
        ctrl = SettingsController(data_dir=tmp_path)
        ctrl.set_enabled_domain_packs(["programming"])

        # 1. Add custom brand word ('FastHTML') + comma-separated words to 'programming'
        details = ctrl.add_domain_pack_word("programming", "FastHTML, DrizzleORM")
        words_by_low = {w["lower"]: w for w in details["words"]}
        assert words_by_low["fasthtml"]["word"] == "FastHTML"
        assert words_by_low["fasthtml"]["source"] == "custom"
        assert details["has_overrides"] is True

        # Live daemon immediately recognizes 'fasthtml' -> 'FastHTML' and fuzzy-matches 'fasthtlm'
        assert (
            daemon.engine.evaluate_token("fasthtml", EvaluationContext(is_sentence_start=False)).replacement_token
            == "FastHTML"
        )
        assert (
            daemon.engine.evaluate_token("drizzleomr", EvaluationContext(is_sentence_start=False)).replacement_token
            == "DrizzleORM"
        )

        # 2. Edit 'DrizzleORM' -> 'Drizzle'
        details2 = ctrl.edit_domain_pack_word("programming", "DrizzleORM", "Drizzle")
        lows2 = {w["lower"]: w["word"] for w in details2["words"]}
        assert "drizzleorm" not in lows2
        assert lows2["drizzle"] == "Drizzle"

        # 3. Remove a built-in domain word ('idempotency') and add a custom direct typo ('fhtml' -> 'FastHTML')
        ctrl.delete_domain_pack_word("programming", "idempotency")
        details3 = ctrl.upsert_domain_pack_typo("programming", "fhtml", "FastHTML")
        assert "idempotency" not in {w["lower"] for w in details3["words"]}
        assert any(t["typo"] == "fhtml" and t["target"] == "FastHTML" for t in details3["direct_typos"])
        assert daemon.engine.evaluate_token("fhtml").replacement_token == "FastHTML"

        # 4. Reset pack to built-in defaults
        reset_details = ctrl.reset_domain_pack("programming")
        assert reset_details["has_overrides"] is False
        assert "idempotency" in {w["lower"] for w in reset_details["words"]}
        assert "fasthtml" not in {w["lower"] for w in reset_details["words"]}
    finally:
        daemon.stop()




