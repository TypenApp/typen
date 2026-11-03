"""
Linux Wayland IBus Input Method Engine Adapter.

Under Wayland, compositors forbid background processes from snooping global
keys or injecting keystrokes. Implementing an IBus engine provides
compositor-sanctioned access to key events, surrounding-text replacement
(`delete_surrounding_text` + `commit_text`), and explicit password-field
detection (`IBUS_INPUT_PURPOSE_PASSWORD` / `IBUS_INPUT_PURPOSE_PIN`).

This module holds the toolkit-independent logic (unit-tested everywhere);
`ibus_main.py` binds it to the real `IBus.Engine` GObject class.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from autocorrect.adapters.linux.x11_adapter import MODIFIER_KEYSYMS, translate_x11_key
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager

# Standard IBus InputPurpose enum values (from IBus-1.0 gir)
IBUS_INPUT_PURPOSE_FREE_FORM: Final[int] = 0
IBUS_INPUT_PURPOSE_ALPHA: Final[int] = 1
IBUS_INPUT_PURPOSE_DIGITS: Final[int] = 2
IBUS_INPUT_PURPOSE_NUMBER: Final[int] = 3
IBUS_INPUT_PURPOSE_PHONE: Final[int] = 4
IBUS_INPUT_PURPOSE_URL: Final[int] = 5
IBUS_INPUT_PURPOSE_EMAIL: Final[int] = 6
IBUS_INPUT_PURPOSE_NAME: Final[int] = 7
IBUS_INPUT_PURPOSE_PASSWORD: Final[int] = 8
IBUS_INPUT_PURPOSE_PIN: Final[int] = 9
IBUS_INPUT_PURPOSE_TERMINAL: Final[int] = 10

# IBus InputHints bits
IBUS_INPUT_HINT_SPELLCHECK: Final[int] = 1 << 0
IBUS_INPUT_HINT_NO_SPELLCHECK: Final[int] = 1 << 1
IBUS_INPUT_HINT_INHIBIT_OSK: Final[int] = 1 << 10  # often set by password/terminal widgets

# IBus ModifierType bits (match X11 for the low bits)
IBUS_RELEASE_MASK: Final[int] = 1 << 30
IBUS_SUPER_MASK: Final[int] = 1 << 26
IBUS_MOD4_MASK: Final[int] = 1 << 6

# IBus Capabilite bits reported by the client
IBUS_CAP_SURROUNDING_TEXT: Final[int] = 1 << 5

# Purposes for which we never correct: anything that is not prose.
NON_PROSE_PURPOSES: Final[frozenset[int]] = frozenset(
    {
        IBUS_INPUT_PURPOSE_DIGITS,
        IBUS_INPUT_PURPOSE_NUMBER,
        IBUS_INPUT_PURPOSE_PHONE,
        IBUS_INPUT_PURPOSE_URL,
        IBUS_INPUT_PURPOSE_EMAIL,
        IBUS_INPUT_PURPOSE_PASSWORD,
        IBUS_INPUT_PURPOSE_PIN,
    }
)


@dataclass(frozen=True)
class IBusReplacement:
    """What the engine must do to the client's text: delete N chars before the caret, commit text."""

    delete_before_caret: int
    commit_text: str


class WaylandIBusEngineAdapter:
    """
    Bridges IBus `process_key_event`, `set_content_type`, `set_capabilities`,
    `focus_in/out` signals to `InputSessionManager`.

    Automatically disables autocorrect whenever the client reports a password,
    PIN, URL, e-mail or numeric purpose, or the NO_SPELLCHECK hint.
    """

    def __init__(
        self,
        session: InputSessionManager,
        apply_replacement: Callable[[IBusReplacement], None] | None = None,
    ) -> None:
        self._session = session
        self._apply = apply_replacement
        self._client_caps = 0
        self._purpose = IBUS_INPUT_PURPOSE_FREE_FORM
        self._hints = 0
        self._app_id = "wayland-client"
        self.committed_operations: list[tuple[int, str]] = []

    # -------------------------------------------------------------- signals

    def on_capabilities_changed(self, caps: int) -> None:
        self._client_caps = int(caps)

    @property
    def client_supports_surrounding_text(self) -> bool:
        return bool(self._client_caps & IBUS_CAP_SURROUNDING_TEXT)

    def on_focus_in(self, app_id: str = "") -> FocusContext:
        self._app_id = app_id or "wayland-client"
        return self._refresh_focus()

    def on_focus_out(self) -> None:
        self._session.reset_all_state()

    def on_reset(self) -> None:
        """Client cleared/replaced its text (e.g. Ctrl+A, programmatic set) — buffer is stale."""
        self._session.on_mouse_click_or_caret_move()

    def on_content_type_changed(self, purpose: int, hints: int = 0) -> FocusContext:
        """Handle Wayland text-input-v3 / IBus content-type notifications."""
        self._purpose = int(purpose)
        self._hints = int(hints)
        return self._refresh_focus()

    def _refresh_focus(self) -> FocusContext:
        is_secure = self._purpose in (IBUS_INPUT_PURPOSE_PASSWORD, IBUS_INPUT_PURPOSE_PIN)
        is_non_prose = self._purpose in NON_PROSE_PURPOSES or bool(
            self._hints & IBUS_INPUT_HINT_NO_SPELLCHECK
        )
        is_terminal = self._purpose == IBUS_INPUT_PURPOSE_TERMINAL
        ctx = FocusContext(
            process_name=self._app_id,
            window_title="",
            bundle_or_app_id=self._app_id,
            is_password_or_secure=is_secure,
            is_terminal_or_code=is_terminal,
            # Non-prose fields are treated like excluded apps: never touch them.
            is_excluded_app=is_non_prose and not is_secure,
        )
        self._session.on_focus_changed(ctx)
        return ctx

    # ------------------------------------------------------------ key events

    @staticmethod
    def translate_ibus_key(keyval: int, state: int, timestamp_ms: float) -> KeyEvent | None:
        """
        Map an IBus (keyval, state) pair to a `KeyEvent`, or None for events
        the engine must simply pass through (key releases, bare modifiers).
        IBus keyvals *are* X11 keysyms, so the X11 translation table applies.
        """
        if state & IBUS_RELEASE_MASK:
            return None
        if keyval in MODIFIER_KEYSYMS or keyval == 0:
            return None
        # Fold the IBus-specific Super bit onto the X11 Mod4 bit our table understands.
        x_state = state & 0xFF
        if state & IBUS_SUPER_MASK:
            x_state |= IBUS_MOD4_MASK
        key_name, char, ctrl, alt, meta, shift = translate_x11_key(keyval, x_state)
        return KeyEvent(
            key_name=key_name,
            char=char,
            timestamp_ms=timestamp_ms,
            ctrl_pressed=ctrl,
            alt_pressed=alt,
            meta_pressed=meta,
            shift_pressed=shift,
            is_injected=False,
        )

    def process_ibus_key_event(self, event: KeyEvent) -> bool:
        """
        Process an IBus key event.
        Returns True if the event was consumed and replaced via surrounding-text mutation,
        or False to let the compositor pass the key event through untouched.
        """
        outcome = self._session.handle_key_event(event, suppress_delimiter_on_replace=True)
        if outcome.action == KeyAction.SUPPRESS_AND_INJECT and outcome.replacement_plan is not None:
            plan = outcome.replacement_plan
            self.committed_operations.append((plan.backspaces_to_send, plan.text_to_inject))
            if self._apply is not None:
                self._apply(IBusReplacement(plan.backspaces_to_send, plan.text_to_inject))
            return True
        return False

    def process_raw_key(self, keyval: int, keycode: int, state: int, timestamp_ms: float) -> bool:
        """Convenience for the GObject engine: translate then process; False = pass through."""
        evt = self.translate_ibus_key(keyval, state, timestamp_ms)
        if evt is None:
            return False
        return self.process_ibus_key_event(evt)
