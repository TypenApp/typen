"""
Tests for System-Wide Input State Machine, Caret Invalidation,
Suffix-Diff Replacement Planner, and Cross-Platform OS Adapters
(Windows Win32, macOS Quartz/AX, Linux X11/Wayland IBus).
"""

from __future__ import annotations

from autocorrect.adapters.linux.ibus_engine import (
    IBUS_INPUT_PURPOSE_FREE_FORM,
    IBUS_INPUT_PURPOSE_PASSWORD,
    WaylandIBusEngineAdapter,
)
from autocorrect.adapters.linux.x11_adapter import X11FocusInspector
from autocorrect.adapters.macos.ax_inspector import MacAXFocusInspector
from autocorrect.adapters.windows.uia_inspector import ES_PASSWORD, Win32FocusInspector
from autocorrect.adapters.windows.win32_hook import Win32KeyboardMouseHook
from autocorrect.adapters.windows.win32_injector import (
    AUTOCORRECT_EXTRA_INFO_TAG,
    KEYEVENTF_UNICODE,
    Win32UnicodeInjector,
)
from autocorrect.core.engine import AutocorrectEngine
from autocorrect.input.diff_planner import SuffixDiffPlanner
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager
from autocorrect.input.word_buffer import BufferState
from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR, ResourceManager


def test_suffix_diff_replacement_planner() -> None:
    """
    Verify that replacing 'recieved ' with 'received ' (when Space is suppressed)
    keeps the common prefix 'rec' (3 chars) and only backspaces 5 chars ('ieved').
    """
    plan = SuffixDiffPlanner.plan(
        original_full="recieved ",
        target_full="received ",
        delimiter_was_suppressed=True,
    )
    assert plan.common_prefix_len == 3
    assert plan.backspaces_to_send == 5
    assert plan.text_to_inject == "eived "


def test_caret_invalidation_on_mouse_click_and_arrows() -> None:
    """
    Verify Section 2.1: If a user types 'rec', clicks the mouse or presses an arrow key,
    and types 'ieved ', the tainted buffer must NOT backspace and corrupt surrounding text.
    """
    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    session = InputSessionManager(engine=engine)
    try:
        for ch in "rec":
            session.handle_key_event(KeyEvent(key_name=ch, char=ch, timestamp_ms=100.0))
        assert session.word_buffer.state == BufferState.CLEAN

        # User clicks mouse mid-word
        session.on_mouse_click_or_caret_move()
        assert session.word_buffer.state == BufferState.TAINTED

        for ch in "ieved":
            session.handle_key_event(KeyEvent(key_name=ch, char=ch, timestamp_ms=200.0))

        # Pressing Space resets the tainted buffer to CLEAN without modifying text
        outcome = session.handle_key_event(
            KeyEvent(key_name="Space", char=" ", timestamp_ms=300.0)
        )
        assert outcome.action == KeyAction.PASS_THROUGH
        assert session.word_buffer.state == BufferState.CLEAN
    finally:
        rm.close()


def test_win32_unicode_injector_and_self_injection_guard() -> None:
    injector = Win32UnicodeInjector(dry_run=True)
    structs = injector.build_input_structs(backspaces=2, text_to_inject="hi")
    # 2 backspaces * 2 (down/up) + 2 UTF-16 chars * 2 (down/up) = 8 INPUT structs
    assert len(structs) == 8
    for s in structs:
        assert s.union.ki.dwExtraInfo == AUTOCORRECT_EXTRA_INFO_TAG
        assert Win32KeyboardMouseHook.is_self_injected(0, s.union.ki.dwExtraInfo)

    # Last 4 events are KEYEVENTF_UNICODE
    assert bool(structs[4].union.ki.dwFlags & KEYEVENTF_UNICODE)


def test_windows_macos_linux_password_and_app_exclusions() -> None:
    # 1. Windows Focus Inspector
    win_insp = Win32FocusInspector()
    ctx_pw_style = win_insp.classify_window_metadata("chrome.exe", "Login", ES_PASSWORD)
    assert ctx_pw_style.is_password_or_secure

    ctx_1p = win_insp.classify_window_metadata("1password.exe", "Vault", 0)
    assert ctx_1p.is_excluded_app

    ctx_term = win_insp.classify_window_metadata("windowsterminal.exe", "PowerShell", 0)
    assert ctx_term.is_terminal_or_code

    # 2. macOS AX Focus Inspector
    mac_insp = MacAXFocusInspector()
    mac_pw = mac_insp.classify_macos_metadata(
        "com.apple.Safari", "Safari", ax_subrole="AXSecureTextField"
    )
    assert mac_pw.is_password_or_secure
    mac_sec = mac_insp.classify_macos_metadata(
        "com.apple.Safari", "Safari", secure_event_input_enabled=True
    )
    assert mac_sec.is_password_or_secure

    # 3. Linux X11 & Wayland IBus Adapter
    x11_insp = X11FocusInspector()
    assert x11_insp.classify_x11_window("keepassxc", "KeePassXC").is_excluded_app

    rm = ResourceManager(bundled_dir=DEFAULT_BUNDLED_DIR)
    engine = AutocorrectEngine(rm)
    session = InputSessionManager(engine=engine)
    ibus = WaylandIBusEngineAdapter(session)
    try:
        # When Wayland client signals password purpose, typing 'teh ' must pass through untouched
        ibus.on_content_type_changed(IBUS_INPUT_PURPOSE_PASSWORD)
        for ch in "teh ":
            consumed = ibus.process_ibus_key_event(
                KeyEvent(
                    key_name="Space" if ch == " " else ch,
                    char=ch,
                    timestamp_ms=100.0,
                )
            )
            assert not consumed

        # When switched back to free-form text, 'teh ' is corrected
        ibus.on_content_type_changed(IBUS_INPUT_PURPOSE_FREE_FORM)
        for ch in "teh":
            ibus.process_ibus_key_event(KeyEvent(key_name=ch, char=ch, timestamp_ms=200.0))
        consumed_space = ibus.process_ibus_key_event(
            KeyEvent(key_name="Space", char=" ", timestamp_ms=250.0)
        )
        assert consumed_space
        assert ibus.committed_operations[-1] == (3, "The ")
    finally:
        rm.close()
