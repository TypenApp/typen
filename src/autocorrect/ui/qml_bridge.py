"""
PySide6-Essentials QObject ViewModel Bridge (`SettingsBridge`) for the
10-Screen Qt Quick / QML Desktop Customisation Interface.
Strictly imports only LGPLv3 modules (`QtCore`, `QtGui`, `QtQml`, `QtQuickControls2`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from autocorrect.ui.lgpl_compliance import assert_no_gpl_qt_modules_loaded

if TYPE_CHECKING:
    from autocorrect.ui.settings_main import SettingsController

QML_FILE_PATH = Path(__file__).resolve().parent / "qml" / "Main.qml"


def launch_pyside6_qml_ui(controller: SettingsController) -> int:
    """
    Launch the hardware-accelerated Qt Quick / QML 10-Screen Settings UI
    using `PySide6-Essentials` under LGPLv3 compliance.
    """
    from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    # Enforce strict LGPLv3 module policy before creating any window
    assert_no_gpl_qt_modules_loaded()

    class SettingsBridge(QObject):  # type: ignore[misc]
        stateChanged = Signal()

        def __init__(self, ctrl: SettingsController) -> None:
            super().__init__()
            self._ctrl = ctrl

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def appVersion(self) -> str:
            return str(self._ctrl.get_overview().get("app_version", "1.2.0"))

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def editionBadge(self) -> str:
            ov = self._ctrl.get_overview()
            ent = ov.get("entitlement", {})
            return str(ent.get("mode", "OPEN_SOURCE")) if isinstance(ent, dict) else "OPEN_SOURCE"

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def statusMessage(self) -> str:
            ov = self._ctrl.get_overview()
            ent = ov.get("entitlement", {})
            hook = ov.get("hook_status", {})
            if isinstance(hook, dict) and hook.get("state") in ("failed", "unsupported"):
                # Typing assistance is not actually running: say why and what to do.
                return f"Not correcting — {hook.get('remediation') or hook.get('detail') or 'input hook unavailable'}"
            return str(ent.get("status_message", "Active")) if isinstance(ent, dict) else "Active"

        @Property(bool, notify=stateChanged)  # type: ignore[misc]
        def isPaused(self) -> bool:
            return bool(self._ctrl.get_overview().get("is_paused", False))

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def activeRegion(self) -> str:
            return str(self._ctrl.get_overview().get("active_region", "EN_GB"))

        @Property(int, notify=stateChanged)  # type: ignore[misc]
        def lexiconWordCount(self) -> int:
            return int(self._ctrl.get_overview().get("lexicon_word_count", 0))

        @Property(int, notify=stateChanged)  # type: ignore[misc]
        def customWordCount(self) -> int:
            return len(self._ctrl.list_custom_words())

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def ipcTransportLabel(self) -> str:
            return "Connected via Local IPC" if self._ctrl.is_daemon_ipc_connected() else "Local Direct Mode"

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def insightsSummaryText(self) -> str:
            ins = self._ctrl.get_overview().get("insights", {})
            if not isinstance(ins, dict):
                return ""
            return (
                f"Words Evaluated: {ins.get('words_evaluated', 0)}  |  "
                f"Spelling Fixes: {ins.get('spelling_corrections', 0)}  |  "
                f"Contextual Fixes: {ins.get('contextual_corrections', 0)}  |  "
                f"Punctuation/Caps: {ins.get('punctuation_and_caps_fixes', 0)}  |  "
                f"Snippets Expanded: {ins.get('snippets_expanded', 0)}  |  "
                f"Keystrokes Saved: {ins.get('keystrokes_saved', 0)}"
            )

        @Property(bool, notify=stateChanged)  # type: ignore[misc]
        def launchAtLogin(self) -> bool:
            return bool(self._ctrl.get_general_settings().get("launch_at_login", False))

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def rewriteHotkey(self) -> str:
            return str(self._ctrl.get_general_settings().get("rewrite_hotkey", "Ctrl+Shift+R"))

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def pauseHotkey(self) -> str:
            return str(self._ctrl.get_general_settings().get("pause_hotkey", "Ctrl+Alt+P"))

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def customWordsPreview(self) -> str:
            words = self._ctrl.list_custom_words()
            return ", ".join(words) if words else "(No custom words added yet)"

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def suggestedWordsPreview(self) -> str:
            sug = self._ctrl.list_suggested_words()
            if not sug:
                return "(None)"
            return ", ".join(f"{item['word']} (-> {item['corrected_to']})" for item in sug)

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def enabledDomainPacksText(self) -> str:
            state = self._ctrl.get_languages_state()
            packs = state.get("domain_packs", [])
            if not isinstance(packs, list):
                return "None"
            enabled = [str(p["name"]) for p in packs if isinstance(p, dict) and p.get("enabled")]
            return ", ".join(enabled) if enabled else "None"

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def correctionsSummaryText(self) -> str:
            c = self._ctrl.get_corrections_state()
            return (
                f"Aggressiveness: {c.get('aggressiveness', 1.0)}  |  "
                f"Punctuation Assist: {c.get('enable_punctuation_assist')}  |  "
                f"Double-Space Period: {c.get('enable_double_space_period')}  |  "
                f"Auto-Capitalise: {c.get('enable_auto_capitalise')}  |  "
                f"Rejected Pairs: {len(c.get('rejected_corrections', []))}  |  "
                f"Preferred Variants: {len(c.get('preferred_variants', []))}"
            )

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def aiSummaryText(self) -> str:
            ai = self._ctrl.get_ai_state()
            loc = ai.get("local_ai", {})
            byok = ai.get("byok", {})
            if not isinstance(loc, dict) or not isinstance(byok, dict):
                return ""
            return (
                f"Layer 2 Local AI: {loc.get('recommended_model_id')} ({loc.get('accelerator')}) • "
                f"400ms Pause Pill: {loc.get('pause_pill_enabled')}\n"
                f"Layer 3 BYOK Cloud AI: Provider={byok.get('active_provider')} ({byok.get('active_model')}) • "
                f"Local-Only Lockdown={byok.get('local_only_mode')} • "
                f"Caps=${byok.get('daily_limit_usd')}/day, ${byok.get('monthly_limit_usd')}/month"
            )

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def profilesSummaryText(self) -> str:
            profs = self._ctrl.list_app_profiles()
            return "\n".join(
                f"• {p['display_name']} ({p['app_identifier']}): aggressiveness={p['aggressiveness']}, packs={','.join(p['active_domain_packs'])}"
                for p in profs
            )

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def snippetsSummaryText(self) -> str:
            snips = self._ctrl.list_snippets()
            if not snips:
                return "No custom text expansion snippets configured."
            return "\n".join(f"• {s['trigger']}  ->  {s['expansion']}" for s in snips)

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def updatesSummaryText(self) -> str:
            u = self._ctrl.get_updates_state()
            app = u.get("app", {})
            res = u.get("language_resources", {})
            if not isinstance(app, dict) or not isinstance(res, dict):
                return ""
            return (
                f"App Binary: v{app.get('current_version')}  |  "
                f"Language Intelligence Library: v{res.get('active_version')} "
                f"(Schema v{res.get('schema_version')}, {res.get('word_count')} words)"
            )

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def aboutSummaryText(self) -> str:
            about = self._ctrl.get_about_state()
            return (
                f"Typen v{about.get('app_version')} — {about.get('status_message')}\n"
                f"Licence: {about.get('licence')}. Source: {about.get('source_url')}\n"
                f"Sponsored via GitHub Sponsors: {about.get('donate_url')}\n"
                f"Uses Qt 6 / PySide6-Essentials, dynamically linked under GNU LGPLv3."
            )

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def donateUrl(self) -> str:
            return str(self._ctrl.get_about_state().get("donate_url", ""))

        @Property(str, notify=stateChanged)  # type: ignore[misc]
        def sourceUrl(self) -> str:
            return str(self._ctrl.get_about_state().get("source_url", ""))

        @Slot()  # type: ignore[misc]
        def togglePause(self) -> None:
            self._ctrl.set_paused(not self.isPaused)
            self.stateChanged.emit()

        @Slot()  # type: ignore[misc]
        def resetInsights(self) -> None:
            self._ctrl.reset_insights()
            self.stateChanged.emit()

        @Slot(bool)  # type: ignore[misc]
        def setLaunchAtLogin(self, enabled: bool) -> None:
            self._ctrl.update_general_settings(launch_at_login=enabled)
            self.stateChanged.emit()

        @Slot()  # type: ignore[misc]
        def privacyWipe(self) -> None:
            self._ctrl.privacy_wipe()
            self.stateChanged.emit()

        @Slot(str)  # type: ignore[misc]
        def addCustomWord(self, word: str) -> None:
            self._ctrl.add_custom_word(word)
            self.stateChanged.emit()

        @Slot(str)  # type: ignore[misc]
        def setRegion(self, region: str) -> None:
            self._ctrl.set_region(region)
            self.stateChanged.emit()

        @Slot()  # type: ignore[misc]
        def rollbackResources(self) -> None:
            self._ctrl.rollback_language_resources()
            self.stateChanged.emit()

        @Slot()  # type: ignore[misc]
        def openDonatePage(self) -> None:
            self._ctrl.open_sponsors_page()

        @Slot()  # type: ignore[misc]
        def openSourcePage(self) -> None:
            self._ctrl.open_source_repository()

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    bridge = SettingsBridge(controller)
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(QML_FILE_PATH)))
    if not engine.rootObjects():
        return 1
    return int(app.exec())
