"""
Cross-platform plumbing that must be correct on every OS even though the
real hooks can only run on their own platform: session detection, X11 key
translation, synthetic-event ledger, macOS key translation, data-dir
resolution/migration, startup registration artefacts and hook-status surfacing.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from autocorrect.adapters.linux.session_type import LinuxSessionType, detect_linux_session
from autocorrect.adapters.linux.x11_adapter import (
    CONTROL_MASK,
    MOD4_MASK,
    SHIFT_MASK,
    XK_BACKSPACE,
    XK_LEFT,
    XK_RETURN,
    X11FocusInspector,
    X11SyntheticTracker,
    char_to_keysym,
    keysym_to_char,
    translate_x11_key,
)
from autocorrect.adapters.macos.quartz_tap import QuartzTapError, build_key_event
from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.daemon.hook_status import HookState, HookStatus
from autocorrect.daemon.startup import StartupManager
from autocorrect.platform_paths import default_data_dir, legacy_data_dir, resolve_data_dir

# ------------------------------------------------------------ Linux session


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}, LinuxSessionType.WAYLAND),
        ({"XDG_SESSION_TYPE": "x11"}, LinuxSessionType.X11),
        ({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":1"}, LinuxSessionType.WAYLAND),
        ({"DISPLAY": ":0"}, LinuxSessionType.X11),
        ({}, LinuxSessionType.HEADLESS),
        ({"XDG_SESSION_TYPE": "tty"}, LinuxSessionType.HEADLESS),
    ],
)
def test_detect_linux_session(env: dict[str, str], expected: LinuxSessionType) -> None:
    assert detect_linux_session(env) == expected


# ------------------------------------------------------------ X11 translate


def test_x11_keysym_round_trip_and_unicode() -> None:
    for ch in "aZ9 é£ßñ€—😀\n\t":
        assert keysym_to_char(char_to_keysym(ch)) == (ch if ch not in "\n\t" else "")
    assert keysym_to_char(XK_BACKSPACE) == ""
    assert char_to_keysym("\n") == XK_RETURN


def test_x11_translate_key_names_and_chords() -> None:
    assert translate_x11_key(ord("a"), 0)[:2] == ("a", "a")
    assert translate_x11_key(ord("A"), SHIFT_MASK)[:2] == ("A", "A")
    assert translate_x11_key(0x20, 0)[:2] == ("Space", " ")
    assert translate_x11_key(XK_RETURN, 0)[:2] == ("Return", "\n")
    assert translate_x11_key(XK_LEFT, 0)[:2] == ("Left", "")
    name, char, ctrl, alt, meta, shift = translate_x11_key(ord("c"), CONTROL_MASK)
    assert (char, ctrl) == ("", True)  # Ctrl+C is a chord, not a character
    assert translate_x11_key(ord("l"), MOD4_MASK)[4] is True  # Super held


def test_x11_synthetic_tracker_matches_in_order_only() -> None:
    t = X11SyntheticTracker()
    t.expect(22, True)
    t.expect(22, False)
    assert not t.consume_if_expected(22, False)  # out of order: a real key, keep it
    assert t.consume_if_expected(22, True)
    assert t.consume_if_expected(22, False)
    assert t.pending_count == 0
    assert not t.consume_if_expected(22, True)


def test_x11_focus_classification() -> None:
    insp = X11FocusInspector(extra_excluded={"MyBank"})
    ctx = insp.classify_x11_window("KeePassXC", "Unlock Database")
    assert ctx.is_excluded_app
    assert insp.classify_x11_window("gcr-prompter", "Enter password to unlock keyring").is_password_or_secure
    ctx = insp.classify_x11_window("Alacritty", "~ — zsh")
    assert ctx.is_terminal_or_code and not ctx.is_excluded_app
    assert insp.classify_x11_window("mybank", "Online banking").is_excluded_app
    ctx = insp.classify_x11_window("firefox", "Mozilla Firefox")
    assert not (ctx.is_excluded_app or ctx.is_terminal_or_code or ctx.is_password_or_secure)
    assert ctx.process_name == "firefox"


# ----------------------------------------------------------- macOS translate

_CMD, _CTRL, _ALT, _SHIFT = 1 << 20, 1 << 18, 1 << 19, 1 << 17


def _mac(keycode: int, flags: int, text: str):
    return build_key_event(
        keycode,
        flags,
        text,
        0.0,
        mask_command=_CMD,
        mask_control=_CTRL,
        mask_alternate=_ALT,
        mask_shift=_SHIFT,
    )


def test_macos_key_event_uses_layout_translated_text() -> None:
    assert _mac(0, 0, "a").char == "a"
    assert _mac(0, _SHIFT, "A").char == "A"
    assert _mac(0, _ALT, "é").char == "é"  # Option-e dead key produces a real glyph
    assert _mac(0, _ALT, "é").alt_pressed is False  # ...so it is not a chord
    assert _mac(49, 0, " ").key_name == "Space"
    assert _mac(36, 0, "\r").char == "\n" and _mac(36, 0, "\r").key_name == "Return"
    ev = _mac(8, _CMD, "c")
    assert ev.char == "" and ev.meta_pressed  # Cmd+C
    assert _mac(123, 0, "\x1c").key_name == "Left" and _mac(123, 0, "\x1c").char == ""
    assert _mac(51, 0, "\x7f").key_name == "Backspace"


def test_quartz_tap_error_carries_remediation() -> None:
    err = QuartzTapError("denied")
    assert "Input Monitoring" in err.remediation


# -------------------------------------------------------------- data dirs


def test_default_data_dir_per_platform(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert default_data_dir("win32", home, env={}) == home / ".autocorrect_desktop"
    assert (
        default_data_dir("darwin", home, env={}) == home / "Library" / "Application Support" / "AutoCorrect"
    )
    assert default_data_dir("linux", home, env={}) == home / ".local" / "share" / "autocorrect"
    assert (
        default_data_dir("linux", home, env={"XDG_DATA_HOME": str(tmp_path / "xdg")})
        == tmp_path / "xdg" / "autocorrect"
    )
    assert (
        default_data_dir("linux", home, env={"AUTOCORRECT_DATA_DIR": str(tmp_path / "custom")})
        == tmp_path / "custom"
    )


def test_resolve_data_dir_migrates_legacy_dir_once(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = legacy_data_dir(home)
    (legacy / "licence").mkdir(parents=True)
    (legacy / "licence" / "entitlement.lic").write_text("{}")
    target = resolve_data_dir(platform="linux", home=home, env={})
    assert target == home / ".local" / "share" / "autocorrect"
    assert (target / "licence" / "entitlement.lic").exists()
    assert not legacy.exists()
    # Second resolution is a no-op; an explicit path is always honoured.
    assert resolve_data_dir(platform="linux", home=home, env={}) == target
    explicit = tmp_path / "explicit"
    assert resolve_data_dir(explicit, platform="linux", home=home, env={}) == explicit and explicit.is_dir()


def test_windows_keeps_legacy_dir(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy = legacy_data_dir(home)
    legacy.mkdir(parents=True)
    assert resolve_data_dir(platform="win32", home=home, env={}) == legacy


# ------------------------------------------------------------- startup files


def test_macos_launch_agent_plist_and_linux_desktop_entry() -> None:
    plist = plistlib.loads(
        StartupManager.build_macos_launch_agent_plist(
            ["/Applications/AutoCorrect.app/Contents/MacOS/AutoCorrect"]
        )
    )
    assert plist["Label"] == "io.autocorrect.desktop" and plist["RunAtLoad"] is True
    assert plist["LimitLoadToSessionType"] == "Aqua"
    entry = StartupManager.build_linux_desktop_entry(["/opt/auto correct/AutoCorrectDesktop", "--no-tray"])
    assert entry.startswith("[Desktop Entry]\n")
    assert "Exec='/opt/auto correct/AutoCorrectDesktop' --no-tray" in entry
    assert "X-GNOME-Autostart-enabled=true" in entry
    assert StartupManager.linux_autostart_path(Path("/h"), env={}) == Path(
        "/h/.config/autostart/autocorrect-desktop.desktop"
    )
    assert StartupManager.linux_autostart_path(Path("/h"), env={"XDG_CONFIG_HOME": "/cfg"}) == Path(
        "/cfg/autostart/autocorrect-desktop.desktop"
    )


# ------------------------------------------------------------- hook status


def test_hook_status_is_surfaced_over_ipc_and_in_dry_run(tmp_path: Path) -> None:
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=True)
    try:
        assert d.hook_status.state == HookState.DRY_RUN and d.hook_status.is_active
        from autocorrect.ipc import LocalIPCClient

        ov = LocalIPCClient(data_dir=tmp_path, max_retries=1).call("system.get_overview")
        assert ov["hook_status"]["state"] == "dry_run"
    finally:
        d.stop()
    assert d.hook_status.state == HookState.INACTIVE


def test_failed_hook_status_keeps_daemon_but_marks_hooks_inactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=False)
    monkeypatch.setattr(
        d,
        "_install_platform_hook",
        lambda: HookStatus(HookState.FAILED, backend="test", detail="boom", remediation="grant permission"),
    )
    d.start(start_ipc=False)
    try:
        assert d.hook_status.state == HookState.FAILED
        assert not d.hooks_active
        assert not d.focus_monitor.is_running
        assert d.entitlement_manager.evaluate().typing_assistance_enabled  # licence state unaffected
    finally:
        d.stop()
