"""
Auto-space after sentence punctuation.

A word closed by '.', '!' or '?' gets a space appended so the user can keep
typing; a Space they type anyway is swallowed, a second closing mark is pulled
back against the terminator, a lowercase letter starts the next sentence, and
a digit typed straight after the dot (versions) takes the space back. Host
TLDs and file extensions ('example.com', 'report.docx') are glued back at
word-complete. Both the blocking (IBus / dry-run) and passive (Windows hook)
delivery modes are covered.
"""

from __future__ import annotations

import pytest

from autocorrect.core.engine import AutocorrectEngine
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager


@pytest.fixture(scope="module")
def engine() -> AutocorrectEngine:
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    yield AutocorrectEngine(rm)
    rm.close()


@pytest.fixture()
def session(engine: AutocorrectEngine) -> InputSessionManager:
    return InputSessionManager(engine=engine)


def _type(session: InputSessionManager, text: str, *, passive: bool) -> str:
    """
    Drive `session` with `text` into a virtual field. In passive mode every key
    has already landed before the session sees it (Windows low-level hook); in
    blocking mode a key only lands when the session passes it through.
    '\\b' is Backspace.
    """
    field: list[str] = []
    ts = 1000.0
    suppress = not passive
    for ch in text:
        ts += 60.0
        if ch == "\b":
            if passive and field:
                field.pop()
            out = session.handle_key_event(
                KeyEvent(key_name="Backspace", char="", timestamp_ms=ts),
                suppress_delimiter_on_replace=suppress,
            )
            if not passive and out.action == KeyAction.PASS_THROUGH and field:
                field.pop()
            continue
        key = "Space" if ch == " " else ("Return" if ch == "\n" else ch)
        if passive:
            field.append(ch)
        out = session.handle_key_event(
            KeyEvent(key_name=key, char=ch, timestamp_ms=ts), suppress_delimiter_on_replace=suppress
        )
        if not passive and out.action == KeyAction.PASS_THROUGH:
            field.append(ch)
        plan = out.replacement_plan
        if plan is not None and (passive or out.action == KeyAction.SUPPRESS_AND_INJECT):
            for _ in range(plan.backspaces_to_send):
                if field:
                    field.pop()
            field.extend(plan.text_to_inject)
    return "".join(field)


@pytest.mark.parametrize("passive", [False, True])
@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("hello world.", "Hello world. "),
        ("wait!", "Wait! "),
        ("really?", "Really? "),
        # Typing the space yourself never doubles it, and the next sentence starts capitalised.
        ("hello world. this is a tset. ", "Hello world. This is a test. "),
        # Relying on the inserted space (no extra Space key) still capitalises.
        ("hello world.this is a tset. ", "Hello world. This is a test. "),
        # A correction on the final word merges with the added space.
        ("i recieved teh mesage.", "I received the message. "),
        # Ellipsis / combined marks are pulled back against the terminator.
        ("wait...what ", "Wait...what "),
        ("really?! yes ", "Really?! Yes "),
        ('he said "stop." then ', 'He said "stop." Then '),
        ("done.) next ", "Done.) Next "),
        # Lowercase straight after the dot: URL / file / version, leave it alone.
        ("go to example.com now ", "Go to example.com now "),
        ("open report.docx please ", "Open report.docx please "),
        # Abbreviations, initials and numbers never get a space.
        ("we met dr. smith ", "We met dr. smith "),
        ("use e.g. python ", "Use e.g. python "),
        ("version 1.2 ok ", "Version 1.2 ok "),
        # Backspace removes the added space and the flag with it.
        ("hello world.\bx", "Hello world.x"),
        # Enter after the auto space leaves the space in place.
        ("hello world.\nnext ", "Hello world. \nNext "),
    ],
)
def test_auto_space_rules(session: InputSessionManager, typed: str, expected: str, passive: bool) -> None:
    assert _type(session, typed, passive=passive) == expected


def test_auto_space_reports_reason_tags(session: InputSessionManager) -> None:
    for ch in "Fine":
        session.handle_key_event(KeyEvent(key_name=ch, char=ch, timestamp_ms=1.0))
    out = session.handle_key_event(
        KeyEvent(key_name=".", char=".", timestamp_ms=2.0), suppress_delimiter_on_replace=False
    )
    assert out.reason_tag == "AUTO_SPACE"
    assert out.replacement_plan is not None
    assert out.replacement_plan.text_to_inject == " "
    swallowed = session.handle_key_event(
        KeyEvent(key_name="Space", char=" ", timestamp_ms=3.0), suppress_delimiter_on_replace=False
    )
    assert swallowed.reason_tag == "AUTO_SPACE_SWALLOWED"
    assert swallowed.replacement_plan is not None
    assert swallowed.replacement_plan.backspaces_to_send == 1  # passive: the Space already landed


def test_auto_space_can_be_disabled(session: InputSessionManager) -> None:
    session.configure_features(enable_auto_space=False)
    assert _type(session, "hello world.", passive=False) == "Hello world."
    session.reset_all_state()
    assert _type(session, "hello world. next ", passive=True) == "Hello world. Next "


def test_auto_space_off_in_code_and_terminal_apps(session: InputSessionManager) -> None:
    session.on_focus_changed(FocusContext(process_name="code.exe", is_terminal_or_code=True))
    assert _type(session, "print.", passive=False) == "print."
