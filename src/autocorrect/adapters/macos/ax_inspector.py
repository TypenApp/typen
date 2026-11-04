"""
macOS Accessibility (AXUIElement) Focus, Secure Input, and Permission Inspector.
Checks `IsSecureEventInputEnabled()`, `AXSecureTextField`, and bundle ID blocklists,
and provides user onboarding helpers for macOS Accessibility permissions.
"""

from __future__ import annotations

import sys
from typing import Final

from autocorrect.input.ports import FocusContext

MACOS_EXCLUDED_BUNDLES: Final[frozenset[str]] = frozenset(
    {
        "com.1password.1password",
        "com.agilebits.onepassword7",
        "com.bitwarden.desktop",
        "org.keepassxc.keepassxc",
        "com.dashlane.dashlanephonefinal",
        "com.apple.keychainaccess",
    }
)

MACOS_TERMINAL_BUNDLES: Final[frozenset[str]] = frozenset(
    {
        "com.apple.terminal",
        "com.googlecode.iterm2",
        "io.alacritty",
        "com.github.wez.wezterm",
        "dev.warp.warp-stable",
    }
)


class MacAXFocusInspector:
    """
    Inspects macOS secure input mode, focused AXUIElement role/subrole,
    and active application bundle identifier.
    """

    def __init__(self, extra_excluded_bundles: set[str] | None = None) -> None:
        self._user_excluded: set[str] = {b.lower() for b in (extra_excluded_bundles or set())}

    @staticmethod
    def is_accessibility_trusted(prompt_user: bool = False) -> bool:
        """
        Check whether macOS Accessibility permissions are granted to this process.
        If `prompt_user=True`, displays the native macOS System Settings permission dialog.
        """
        if sys.platform != "darwin":
            return True
        try:
            import ApplicationServices  # type: ignore[import-not-found]

            options = {ApplicationServices.kAXTrustedCheckOptionPrompt: bool(prompt_user)}
            return bool(ApplicationServices.AXIsProcessTrustedWithOptions(options))
        except Exception:
            return False

    @staticmethod
    def get_permission_onboarding_instructions() -> str:
        """Return clear user-facing instructions for granting macOS Accessibility access."""
        return (
            "To enable system-wide autocorrect on macOS:\n"
            "1. Open System Settings -> Privacy & Security -> Accessibility.\n"
            "2. Toggle ON 'Typen'.\n"
            "3. Ensure 'Input Monitoring' is also enabled if prompted."
        )

    def classify_macos_metadata(
        self,
        bundle_id: str,
        app_name: str,
        ax_role: str = "",
        ax_subrole: str = "",
        secure_event_input_enabled: bool = False,
    ) -> FocusContext:
        """Pure classification logic testable across all operating systems."""
        b_low = bundle_id.lower()
        is_password = (
            secure_event_input_enabled or ax_subrole == "AXSecureTextField" or ax_role == "AXSecureTextField"
        )
        is_excluded = b_low in MACOS_EXCLUDED_BUNDLES or b_low in self._user_excluded
        is_terminal = b_low in MACOS_TERMINAL_BUNDLES

        return FocusContext(
            process_name=app_name.lower(),
            window_title=app_name,
            bundle_or_app_id=b_low,
            is_password_or_secure=is_password,
            is_terminal_or_code=is_terminal,
            is_excluded_app=is_excluded,
        )

    @staticmethod
    def is_secure_event_input_enabled() -> bool:
        """
        `IsSecureEventInputEnabled()` lives in Carbon/HIToolbox (not exposed by
        pyobjc's Quartz bindings), so call it through ctypes. True whenever any
        app — password fields in Safari/Chrome, Terminal with secure entry,
        login windows — has asked macOS to block keyboard snooping.
        """
        if sys.platform != "darwin":
            return False
        try:
            import ctypes

            carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
            carbon.IsSecureEventInputEnabled.restype = ctypes.c_ubyte
            return bool(carbon.IsSecureEventInputEnabled())
        except Exception:
            return False

    def get_current_focus(self) -> FocusContext:
        if sys.platform != "darwin":
            return FocusContext()
        try:
            import ApplicationServices  # type: ignore[import-not-found]
            from AppKit import NSWorkspace  # type: ignore[import-not-found]

            secure_input = self.is_secure_event_input_enabled()

            front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            bundle_id = str(front_app.bundleIdentifier() or "") if front_app else ""
            app_name = str(front_app.localizedName() or "") if front_app else ""

            sys_wide = ApplicationServices.AXUIElementCreateSystemWide()
            err, focused_elem = ApplicationServices.AXUIElementCopyAttributeValue(
                sys_wide, "AXFocusedUIElement", None
            )
            role = ""
            subrole = ""
            if err == 0 and focused_elem is not None:
                _, r_val = ApplicationServices.AXUIElementCopyAttributeValue(focused_elem, "AXRole", None)
                _, sr_val = ApplicationServices.AXUIElementCopyAttributeValue(focused_elem, "AXSubrole", None)
                role = str(r_val or "")
                subrole = str(sr_val or "")

            return self.classify_macos_metadata(
                bundle_id=bundle_id,
                app_name=app_name,
                ax_role=role,
                ax_subrole=subrole,
                secure_event_input_enabled=secure_input,
            )
        except Exception:
            return FocusContext()
