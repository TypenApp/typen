"""
Linux X11 Adapter (`python-xlib` XRecord + XTest + EWMH).

- `X11TextInjector`      : XTest-driven Backspace + Unicode injection. Characters
                           that are not on the current keymap are typed by
                           temporarily remapping a spare keycode (the xdotool
                           technique) and restoring it afterwards.
- `X11FocusInspector`    : reads `_NET_ACTIVE_WINDOW`, `WM_CLASS` and
                           `_NET_WM_NAME` to classify password managers,
                           terminals and polkit/keyring prompts.
- `X11SyntheticTracker`  : shared ledger so the XRecord hook can recognise and
                           ignore the key events the injector itself generated
                           (X11 has no equivalent of Win32 `dwExtraInfo`).

Everything X-specific is imported lazily so this module is importable (and
unit-testable) on Windows/macOS and in headless CI.
"""

from __future__ import annotations

import sys
import threading
from collections import deque
from typing import Any, Final

from autocorrect.input.ports import FocusContext

LINUX_EXCLUDED_WM_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "1password",
        "bitwarden",
        "keepassxc",
        "gcr-prompter",
        "polkit-gnome-authentication-agent-1",
        "polkit-kde-authentication-agent-1",
        "lxpolkit",
        "pinentry",
        "pinentry-gnome3",
        "pinentry-qt",
        "pinentry-gtk-2",
        "gnome-keyring-prompt",
        "ksshaskpass",
    }
)

LINUX_TERMINAL_WM_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "gnome-terminal",
        "gnome-terminal-server",
        "konsole",
        "xterm",
        "urxvt",
        "alacritty",
        "kitty",
        "wezterm",
        "wezterm-gui",
        "terminator",
        "tilix",
        "xfce4-terminal",
        "mate-terminal",
        "lxterminal",
        "foot",
        "code",
        "code-oss",
        "codium",
        "jetbrains-idea",
        "jetbrains-pycharm",
        "jetbrains-clion",
        "sublime_text",
        "neovide",
        "emacs",
    }
)

# X11 keysyms used for control keys.
XK_BACKSPACE: Final[int] = 0xFF08
XK_TAB: Final[int] = 0xFF09
XK_RETURN: Final[int] = 0xFF0D
XK_ESCAPE: Final[int] = 0xFF1B
XK_HOME: Final[int] = 0xFF50
XK_LEFT: Final[int] = 0xFF51
XK_UP: Final[int] = 0xFF52
XK_RIGHT: Final[int] = 0xFF53
XK_DOWN: Final[int] = 0xFF54
XK_PAGE_UP: Final[int] = 0xFF55
XK_PAGE_DOWN: Final[int] = 0xFF56
XK_END: Final[int] = 0xFF57
XK_KP_ENTER: Final[int] = 0xFF8D
XK_DELETE: Final[int] = 0xFFFF
XK_SHIFT_L: Final[int] = 0xFFE1
XK_SHIFT_R: Final[int] = 0xFFE2
XK_CONTROL_L: Final[int] = 0xFFE3
XK_CONTROL_R: Final[int] = 0xFFE4
XK_CAPS_LOCK: Final[int] = 0xFFE5
XK_META_L: Final[int] = 0xFFE7
XK_META_R: Final[int] = 0xFFE8
XK_ALT_L: Final[int] = 0xFFE9
XK_ALT_R: Final[int] = 0xFFEA
XK_SUPER_L: Final[int] = 0xFFEB
XK_SUPER_R: Final[int] = 0xFFEC
XK_ISO_LEVEL3_SHIFT: Final[int] = 0xFE03

MODIFIER_KEYSYMS: Final[frozenset[int]] = frozenset(
    {
        XK_SHIFT_L,
        XK_SHIFT_R,
        XK_CONTROL_L,
        XK_CONTROL_R,
        XK_CAPS_LOCK,
        XK_META_L,
        XK_META_R,
        XK_ALT_L,
        XK_ALT_R,
        XK_SUPER_L,
        XK_SUPER_R,
        XK_ISO_LEVEL3_SHIFT,
    }
)

KEYSYM_TO_KEY_NAME: Final[dict[int, str]] = {
    XK_BACKSPACE: "Backspace",
    XK_TAB: "Tab",
    XK_RETURN: "Return",
    XK_KP_ENTER: "Enter",
    XK_ESCAPE: "Escape",
    XK_HOME: "Home",
    XK_LEFT: "Left",
    XK_UP: "Up",
    XK_RIGHT: "Right",
    XK_DOWN: "Down",
    XK_PAGE_UP: "PageUp",
    XK_PAGE_DOWN: "PageDown",
    XK_END: "End",
    XK_DELETE: "Delete",
}

# X11 modifier state bits.
SHIFT_MASK: Final[int] = 1 << 0
LOCK_MASK: Final[int] = 1 << 1
CONTROL_MASK: Final[int] = 1 << 2
MOD1_MASK: Final[int] = 1 << 3  # Alt
MOD4_MASK: Final[int] = 1 << 6  # Super / Meta
MOD5_MASK: Final[int] = 1 << 7  # AltGr (ISO_Level3_Shift) on most layouts

UNICODE_KEYSYM_BASE: Final[int] = 0x01000000


def keysym_to_char(keysym: int) -> str:
    """
    Translate an X11 keysym to the printable character it produces, or ''.
    Latin-1 keysyms are their own code points; everything else printable is
    encoded as 0x01000000 | code point (XFree86 / xkbcommon convention).
    """
    if 0x20 <= keysym <= 0x7E or 0xA0 <= keysym <= 0xFF:
        return chr(keysym)
    if keysym & UNICODE_KEYSYM_BASE and keysym > UNICODE_KEYSYM_BASE:
        cp = keysym & 0x00FFFFFF
        if cp >= 0x20:
            try:
                return chr(cp)
            except ValueError:
                return ""
    return ""


def char_to_keysym(ch: str) -> int:
    """Inverse of `keysym_to_char` for a single character (plus '\\n' and '\\t')."""
    if ch == "\n":
        return XK_RETURN
    if ch == "\t":
        return XK_TAB
    cp = ord(ch)
    if 0x20 <= cp <= 0x7E or 0xA0 <= cp <= 0xFF:
        return cp
    return UNICODE_KEYSYM_BASE | cp


def translate_x11_key(keysym: int, state: int) -> tuple[str, str, bool, bool, bool, bool]:
    """
    Pure helper (unit-tested on every OS): map a keysym + modifier state to
    `(key_name, char, ctrl, alt, meta, shift)` in the `KeyEvent` vocabulary.
    Chord keys (Ctrl/Alt/Super held) yield no character, matching the Win32 hook.
    """
    ctrl = bool(state & CONTROL_MASK)
    alt = bool(state & MOD1_MASK)
    meta = bool(state & MOD4_MASK)
    shift = bool(state & SHIFT_MASK)
    key_name = KEYSYM_TO_KEY_NAME.get(keysym, "")
    if keysym == XK_RETURN or keysym == XK_KP_ENTER:
        char = "\n"
    elif keysym == 0x20:
        char = " "
        key_name = "Space"
    else:
        char = "" if (ctrl or alt or meta) else keysym_to_char(keysym)
    if not key_name and char:
        key_name = char
    return key_name, char, ctrl, alt, meta, shift


class X11SyntheticTracker:
    """
    Records the keycodes the injector is about to fake so the XRecord hook can
    drop exactly those press/release events instead of feeding them back into
    the session (which would otherwise re-evaluate our own corrections).
    """

    def __init__(self) -> None:
        self._pending: deque[tuple[int, bool]] = deque()
        self._lock = threading.Lock()

    def expect(self, keycode: int, is_press: bool) -> None:
        with self._lock:
            self._pending.append((keycode, is_press))

    def consume_if_expected(self, keycode: int, is_press: bool) -> bool:
        with self._lock:
            if self._pending and self._pending[0] == (keycode, is_press):
                self._pending.popleft()
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)


_shared_tracker = X11SyntheticTracker()


def shared_synthetic_tracker() -> X11SyntheticTracker:
    return _shared_tracker


class X11TextInjector:
    """Executes suffix-diff backspace and key injection under X11 via XTest."""

    def __init__(self, dry_run: bool = False, tracker: X11SyntheticTracker | None = None) -> None:
        self._dry_run = dry_run
        self._tracker = tracker or shared_synthetic_tracker()
        self.history: list[tuple[int, str]] = []
        self._display: Any = None
        self._spare_keycode: int | None = None
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- setup

    def _ensure_display(self) -> Any:
        if self._display is None:
            from Xlib import display as xdisplay  # type: ignore[import-not-found]

            self._display = xdisplay.Display()
        return self._display

    def _find_spare_keycode(self, disp: Any) -> int | None:
        """First keycode with no keysyms bound: safe to remap for off-keymap characters."""
        if self._spare_keycode is not None:
            return self._spare_keycode
        min_kc, max_kc = disp.display.info.min_keycode, disp.display.info.max_keycode
        mapping = disp.get_keyboard_mapping(min_kc, max_kc - min_kc + 1)
        for offset, syms in enumerate(mapping):
            if all(s == 0 for s in syms):
                self._spare_keycode = min_kc + offset
                return self._spare_keycode
        return None

    # ----------------------------------------------------------- primitives

    def _press_release(self, disp: Any, keycode: int, with_shift: bool) -> None:
        from Xlib import X  # type: ignore[import-not-found]
        from Xlib.ext import xtest  # type: ignore[import-not-found]

        shift_kc = disp.keysym_to_keycode(XK_SHIFT_L) if with_shift else 0
        if shift_kc:
            self._tracker.expect(shift_kc, True)
            xtest.fake_input(disp, X.KeyPress, shift_kc)
        self._tracker.expect(keycode, True)
        xtest.fake_input(disp, X.KeyPress, keycode)
        self._tracker.expect(keycode, False)
        xtest.fake_input(disp, X.KeyRelease, keycode)
        if shift_kc:
            self._tracker.expect(shift_kc, False)
            xtest.fake_input(disp, X.KeyRelease, shift_kc)

    def _type_char(self, disp: Any, ch: str) -> None:
        keysym = char_to_keysym(ch)
        keycode = disp.keysym_to_keycode(keysym)
        if keycode:
            # Is the keysym on the shifted level of that key?
            with_shift = disp.keycode_to_keysym(keycode, 0) != keysym and (
                disp.keycode_to_keysym(keycode, 1) == keysym
            )
            self._press_release(disp, keycode, with_shift)
            return
        spare = self._find_spare_keycode(disp)
        if spare is None:
            return  # Nothing we can do for this glyph on this keymap.
        disp.change_keyboard_mapping(spare, [[keysym] * 2])
        disp.sync()
        try:
            self._press_release(disp, spare, False)
            disp.sync()
        finally:
            disp.change_keyboard_mapping(spare, [[0] * 2])
            disp.sync()

    # ---------------------------------------------------------------- public

    def execute_replacement(self, backspaces: int, text_to_inject: str) -> None:
        self.history.append((backspaces, text_to_inject))
        if self._dry_run or not sys.platform.startswith("linux"):
            return
        with self._lock:
            try:
                disp = self._ensure_display()
                bs_kc = disp.keysym_to_keycode(XK_BACKSPACE)
                for _ in range(max(0, backspaces)):
                    self._press_release(disp, bs_kc, False)
                for ch in text_to_inject:
                    self._type_char(disp, ch)
                disp.sync()
            except Exception:
                # Lost the X connection or XTest unavailable: drop the pending
                # ledger so the hook does not swallow the user's next real keys.
                self._tracker.clear()
                self._display = None


class X11FocusInspector:
    """Inspects X11 `_NET_ACTIVE_WINDOW` `WM_CLASS` and `_NET_WM_NAME`."""

    def __init__(self, extra_excluded: set[str] | None = None) -> None:
        self._user_excluded = {c.lower() for c in (extra_excluded or set())}
        self._display: Any = None
        self._atoms: dict[str, int] = {}
        self._last = FocusContext()

    def classify_x11_window(self, wm_class: str, wm_name: str) -> FocusContext:
        cls_low = wm_class.lower()
        name_low = wm_name.lower()
        is_password = any(
            kw in name_low
            for kw in ("password", "passphrase", "pin", "unlock keyring", "authentication required")
        )
        is_excluded = cls_low in LINUX_EXCLUDED_WM_CLASSES or cls_low in self._user_excluded
        is_terminal = cls_low in LINUX_TERMINAL_WM_CLASSES
        return FocusContext(
            process_name=cls_low,
            window_title=wm_name,
            bundle_or_app_id=cls_low,
            is_password_or_secure=is_password,
            is_terminal_or_code=is_terminal,
            is_excluded_app=is_excluded,
        )

    def _atom(self, disp: Any, name: str) -> int:
        if name not in self._atoms:
            self._atoms[name] = disp.intern_atom(name)
        return self._atoms[name]

    def _read_active_window(self, disp: Any) -> tuple[str, str]:
        root = disp.screen().root
        prop = root.get_full_property(self._atom(disp, "_NET_ACTIVE_WINDOW"), 0)
        if prop is None or not prop.value:
            return "", ""
        win_id = int(prop.value[0])
        if not win_id:
            return "", ""
        win = disp.create_resource_object("window", win_id)
        wm_class = ""
        try:
            cls = win.get_wm_class()
            if cls:
                # (instance, class); the class is the stable application identity.
                wm_class = str(cls[1] or cls[0] or "")
        except Exception:
            pass
        wm_name = ""
        try:
            name_prop = win.get_full_property(
                self._atom(disp, "_NET_WM_NAME"), self._atom(disp, "UTF8_STRING")
            )
            if name_prop is not None and name_prop.value:
                raw = name_prop.value
                wm_name = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            else:
                legacy = win.get_wm_name()
                if legacy:
                    wm_name = (
                        legacy.decode("latin-1", "replace") if isinstance(legacy, bytes) else str(legacy)
                    )
        except Exception:
            pass
        return wm_class, wm_name

    def get_current_focus(self) -> FocusContext:
        if not sys.platform.startswith("linux"):
            return FocusContext()
        try:
            if self._display is None:
                from Xlib import display as xdisplay  # type: ignore[import-not-found]

                self._display = xdisplay.Display()
            wm_class, wm_name = self._read_active_window(self._display)
            self._last = self.classify_x11_window(wm_class, wm_name)
        except Exception:
            # Treat a broken X connection as "unknown app": keep the last
            # classification rather than silently re-enabling corrections in a
            # window we previously identified as sensitive.
            self._display = None
        return self._last
