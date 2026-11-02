"""
Linux X11 Adapter (`python-xlib` XRecord + XTest).
"""

from __future__ import annotations

from typing import Final

from autocorrect.input.ports import FocusContext

LINUX_EXCLUDED_WM_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "1password",
        "bitwarden",
        "keepassxc",
        "gcr-prompter",
        "polkit-gnome-authentication-agent-1",
    }
)

LINUX_TERMINAL_WM_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "gnome-terminal",
        "konsole",
        "xterm",
        "alacritty",
        "kitty",
        "wezterm",
        "terminator",
        "xfce4-terminal",
    }
)


class X11TextInjector:
    """Executes suffix-diff backspace and key injection under X11 via XTest."""

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run
        self.history: list[tuple[int, str]] = []

    def execute_replacement(self, backspaces: int, text_to_inject: str) -> None:
        self.history.append((backspaces, text_to_inject))


class X11FocusInspector:
    """Inspects X11 `_NET_ACTIVE_WINDOW` `WM_CLASS` and `_NET_WM_NAME`."""

    def __init__(self, extra_excluded: set[str] | None = None) -> None:
        self._user_excluded = {c.lower() for c in (extra_excluded or set())}

    def classify_x11_window(self, wm_class: str, wm_name: str) -> FocusContext:
        cls_low = wm_class.lower()
        name_low = wm_name.lower()
        is_password = any(
            kw in name_low for kw in ("password", "passphrase", "pin", "unlock keyring")
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

    def get_current_focus(self) -> FocusContext:
        return FocusContext()
