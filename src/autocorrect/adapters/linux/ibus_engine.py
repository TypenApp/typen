"""
Linux Wayland IBus Input Method Engine Adapter.
Under Wayland, compositors forbid background processes from snooping global keys
or injecting keystrokes via X11. Implementing an IBus Engine provides compositor-sanctioned
access to key events, surrounding text replacement (`delete_surrounding_text` + `commit_text`),
and explicit password field detection (`IBUS_INPUT_PURPOSE_PASSWORD` / `IBUS_INPUT_PURPOSE_PIN`).
"""

from __future__ import annotations

from typing import Final

from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.input.session_state import InputSessionManager

# Standard IBus InputPurpose enum values (from IBus-1.0 gir)
IBUS_INPUT_PURPOSE_FREE_FORM: Final[int] = 0
IBUS_INPUT_PURPOSE_PASSWORD: Final[int] = 7
IBUS_INPUT_PURPOSE_PIN: Final[int] = 8
IBUS_INPUT_PURPOSE_TERMINAL: Final[int] = 9


class WaylandIBusEngineAdapter:
    """
    Bridges IBus `process_key_event` and `set_content_type` signals to `InputSessionManager`.
    Automatically disables autocorrect whenever the Wayland client reports
    `IBUS_INPUT_PURPOSE_PASSWORD` or `IBUS_INPUT_PURPOSE_PIN`.
    """

    def __init__(self, session: InputSessionManager) -> None:
        self._session = session
        self.committed_operations: list[tuple[int, str]] = []

    def on_content_type_changed(self, purpose: int, hints: int = 0) -> FocusContext:
        """Handle Wayland text-input-v3 / IBus content-type notifications."""
        is_secure = purpose in (IBUS_INPUT_PURPOSE_PASSWORD, IBUS_INPUT_PURPOSE_PIN)
        is_terminal = purpose == IBUS_INPUT_PURPOSE_TERMINAL
        ctx = FocusContext(
            process_name="wayland-client",
            window_title="",
            bundle_or_app_id="wayland-ibus",
            is_password_or_secure=is_secure,
            is_terminal_or_code=is_terminal,
            is_excluded_app=False,
        )
        self._session.on_focus_changed(ctx)
        return ctx

    def process_ibus_key_event(self, event: KeyEvent) -> bool:
        """
        Process an IBus key event.
        Returns True if the event was consumed and replaced via surrounding-text mutation,
        or False to let the compositor pass the key event through untouched.
        """
        outcome = self._session.handle_key_event(event, suppress_delimiter_on_replace=True)
        if (
            outcome.action == KeyAction.SUPPRESS_AND_INJECT
            and outcome.replacement_plan is not None
        ):
            plan = outcome.replacement_plan
            self.committed_operations.append((plan.backspaces_to_send, plan.text_to_inject))
            return True
        return False
