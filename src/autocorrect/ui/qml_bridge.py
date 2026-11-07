"""
PySide6-Essentials QObject ViewModel Bridge (`SettingsBridge`) for the Qt Quick
settings window. Strictly imports only LGPLv3 modules (`QtCore`, `QtGui`,
`QtQml`, `QtQuickControls2`).

The bridge is deliberately thin: every screen reads a JSON-like state map
(`overview`, `settings`, `corrections`, ...) and writes through two generic
slots: `setSetting(key, value)` for anything in `settings_schema` and
`call(method, paramsJson)` for the controller's other methods (dictionary,
profiles, snippets, AI, feedback). State maps are cached per refresh so a
screen full of bound controls costs one IPC round-trip, not one per control.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from autocorrect.ui.lgpl_compliance import assert_no_gpl_qt_modules_loaded

if TYPE_CHECKING:
    from autocorrect.ui.settings_main import SettingsController

log = logging.getLogger(__name__)

QML_DIR = Path(__file__).resolve().parent / "qml"
QML_FILE_PATH = QML_DIR / "Main.qml"

# Controller methods QML may invoke through `call()`. Anything else is refused,
# so a typo in QML can never reach, say, `privacy_wipe` by accident.
CALLABLE_METHODS: frozenset[str] = frozenset(
    {
        "set_paused",
        "set_insights_enabled",
        "reset_insights",
        "get_insights_daily",
        "privacy_wipe",
        "add_custom_word",
        "delete_custom_word",
        "accept_suggested_word",
        "dismiss_suggested_word",
        "export_dictionary_csv",
        "import_dictionary_csv",
        "export_dictionary_json",
        "import_dictionary_json",
        "set_region",
        "set_enabled_domain_packs",
        "add_rejected_correction",
        "remove_rejected_correction",
        "set_preferred_variant",
        "remove_preferred_variant",
        "set_byok_api_key",
        "update_ai_settings",
        "upsert_app_profile",
        "delete_app_profile",
        "upsert_snippet",
        "delete_snippet",
        "rollback_language_resources",
        "check_for_updates",
        "apply_app_update",
        "try_text",
        "open_sponsors_page",
        "open_source_repository",
    }
)

STATE_GETTERS: dict[str, str] = {
    "overview": "get_overview",
    "general": "get_general_settings",
    "languages": "get_languages_state",
    "corrections": "get_corrections_state",
    "dictionary": "get_dictionary_state",
    "apps": "get_apps_state",
    "snippets": "get_snippets_state",
    "ai": "get_ai_state",
    "updates": "get_updates_state",
    "about": "get_about_state",
}


def _jsonable(value: Any) -> Any:
    """Make controller output safe for QVariant conversion (sets, tuples, Decimals...)."""
    return json.loads(json.dumps(value, default=str))


def load_brand_font() -> str:
    """Register Syne with Qt and return its family name ('' when unavailable)."""
    try:
        from PySide6.QtGui import QFontDatabase

        from autocorrect.branding import find_font_file

        path = find_font_file()
        if path is None:
            return ""
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            return ""
        families = QFontDatabase.applicationFontFamilies(font_id)
        return str(families[0]) if families else ""
    except Exception:
        log.debug("brand font not loaded", exc_info=True)
        return ""


_BRIDGE_CLASS: type | None = None


def bridge_class() -> type:
    """Build (once) and return the `SettingsBridge` QObject class. Requires PySide6."""
    global _BRIDGE_CLASS
    if _BRIDGE_CLASS is not None:
        return _BRIDGE_CLASS

    from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

    class SettingsBridge(QObject):  # type: ignore[misc]
        stateChanged = Signal()
        overviewChanged = Signal()
        toast = Signal(str, bool)  # message, is_error

        def __init__(self, ctrl: SettingsController, font_family: str, initial_screen: str = "") -> None:
            super().__init__()
            self._ctrl = ctrl
            self._font_family = font_family
            self._initial_screen = initial_screen or ""
            self._cache: dict[str, dict[str, Any]] = {}
            self._settings: dict[str, Any] | None = None
            self._schema: list[dict[str, Any]] | None = None

        # ------------------------------------------------------------ cache
        def _state(self, name: str) -> dict[str, Any]:
            if name not in self._cache:
                getter = getattr(self._ctrl, STATE_GETTERS[name])
                try:
                    self._cache[name] = _jsonable(getter())
                except Exception as exc:
                    log.exception("state %s failed", name)
                    self._cache[name] = {"error": str(exc)}
            return self._cache[name]

        def _invalidate(self) -> None:
            self._cache.clear()
            self._settings = None
            self.stateChanged.emit()
            self.overviewChanged.emit()

        # ------------------------------------------------------- properties
        @Property(str, constant=True)  # type: ignore[misc,arg-type]
        def fontFamily(self) -> str:
            return self._font_family

        @Property(str, constant=True)  # type: ignore[misc,arg-type]
        def initialScreen(self) -> str:
            return self._initial_screen

        @Property("QVariantMap", notify=overviewChanged)  # type: ignore[misc,arg-type]
        def overview(self) -> dict[str, Any]:
            return self._state("overview")

        def _settings_map(self) -> dict[str, Any]:
            if self._settings is None:
                self._settings = dict(_jsonable(self._ctrl.get_all_settings()))
            return self._settings

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def settings(self) -> dict[str, Any]:
            return self._settings_map()

        @Property("QVariantList", constant=True)  # type: ignore[misc,arg-type]
        def schema(self) -> list[dict[str, Any]]:
            if self._schema is None:
                self._schema = _jsonable(self._ctrl.get_settings_schema())
            return self._schema

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def general(self) -> dict[str, Any]:
            return self._state("general")

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def languages(self) -> dict[str, Any]:
            return self._state("languages")

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def corrections(self) -> dict[str, Any]:
            return self._state("corrections")

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def dictionary(self) -> dict[str, Any]:
            return self._state("dictionary")

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def apps(self) -> dict[str, Any]:
            return self._state("apps")

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def snippets(self) -> dict[str, Any]:
            return self._state("snippets")

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def ai(self) -> dict[str, Any]:
            return self._state("ai")

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def updates(self) -> dict[str, Any]:
            return self._state("updates")

        @Property("QVariantMap", notify=stateChanged)  # type: ignore[misc,arg-type]
        def about(self) -> dict[str, Any]:
            return self._state("about")

        @Property(str, notify=overviewChanged)  # type: ignore[misc,arg-type]
        def appVersion(self) -> str:
            return str(self._state("overview").get("app_version", ""))

        @Property(bool, notify=overviewChanged)  # type: ignore[misc,arg-type]
        def isPaused(self) -> bool:
            return bool(self._state("overview").get("is_paused", False))

        @Property(bool, notify=overviewChanged)  # type: ignore[misc,arg-type]
        def ipcConnected(self) -> bool:
            return bool(self._ctrl.is_daemon_ipc_connected())

        @Property(str, notify=overviewChanged)  # type: ignore[misc,arg-type]
        def statusMessage(self) -> str:
            ov = self._state("overview")
            hook = ov.get("hook_status") or {}
            if not self.ipcConnected:
                return "Typen is not running"
            if ov.get("is_paused"):
                return "Paused"
            if isinstance(hook, dict) and hook.get("state") in ("failed", "unsupported", "disabled"):
                return "Not correcting"
            return "Active"

        @Property(str, notify=overviewChanged)  # type: ignore[misc,arg-type]
        def statusDetail(self) -> str:
            ov = self._state("overview")
            hook = ov.get("hook_status") or {}
            if not self.ipcConnected:
                return "Start Typen from the Start menu; it normally launches at login."
            if ov.get("is_paused"):
                hold = ov.get("hold_esc_seconds", 10)
                return f"Resume here, from the tray, or hold Esc for {hold:.0f} s."
            if isinstance(hook, dict) and hook.get("state") in ("failed", "unsupported", "disabled"):
                return str(hook.get("remediation") or hook.get("detail") or "Input hook unavailable.")
            listening = ov.get("listening") or {}
            proc = listening.get("process_name") if isinstance(listening, dict) else ""
            return f"Listening in {proc}" if proc else "Listening for typing in every app."

        @Property(bool, notify=stateChanged)  # type: ignore[misc,arg-type]
        def themeIsDark(self) -> bool:
            choice = str(self._settings_map().get("ui_theme", "system"))
            if choice == "dark":
                return True
            if choice == "light":
                return False
            try:
                from PySide6.QtCore import Qt
                from PySide6.QtGui import QGuiApplication

                return bool(QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark)
            except Exception:
                return False

        # ------------------------------------------------------------ slots
        @Slot()  # type: ignore[misc,arg-type]
        def refresh(self) -> None:
            self._invalidate()

        @Slot()  # type: ignore[misc,arg-type]
        def refreshOverview(self) -> None:
            self._cache.pop("overview", None)
            self.overviewChanged.emit()

        @Slot(str, "QVariant")  # type: ignore[misc,arg-type]
        def setSetting(self, key: str, value: Any) -> None:
            try:
                self._ctrl.set_settings({key: value})
            except Exception as exc:
                log.exception("setSetting %s", key)
                self.toast.emit(f"Could not save {key}: {exc}", True)
            self._invalidate()

        @Slot(str)  # type: ignore[misc,arg-type]
        def setSettings(self, values_json: str) -> None:
            try:
                self._ctrl.set_settings(json.loads(values_json or "{}"))
            except Exception as exc:
                log.exception("setSettings")
                self.toast.emit(f"Could not save settings: {exc}", True)
            self._invalidate()

        @Slot(str, str, result=str)  # type: ignore[misc,arg-type]
        def call(self, method: str, params_json: str) -> str:
            """Invoke a whitelisted controller method with JSON kwargs; returns JSON."""
            if method not in CALLABLE_METHODS:
                return json.dumps({"error": f"method not allowed: {method}"})
            try:
                params = json.loads(params_json or "{}")
                fn = getattr(self._ctrl, method)
                if isinstance(params, list):
                    result = fn(*params)
                else:
                    result = fn(**params)
                out = json.dumps({"ok": True, "result": _jsonable(result)})
            except PermissionError as exc:
                out = json.dumps({"error": str(exc)})
                self.toast.emit(str(exc), True)
            except Exception as exc:
                log.exception("call %s", method)
                out = json.dumps({"error": str(exc)})
                self.toast.emit(f"{method.replace('_', ' ')} failed: {exc}", True)
            self._invalidate()
            return out

        @Slot(str, result=str)  # type: ignore[misc,arg-type]
        def tryText(self, text: str) -> str:
            try:
                return str(self._ctrl.try_text(text))
            except Exception:
                log.exception("try_text")
                return text

        @Slot()  # type: ignore[misc,arg-type]
        def togglePause(self) -> None:
            self._ctrl.set_paused(not self.isPaused)
            self._invalidate()

        @Slot(str)  # type: ignore[misc,arg-type]
        def openUrl(self, url: str) -> None:
            if url.startswith(("https://", "http://", "mailto:")):
                webbrowser.open(url)

        @Slot()  # type: ignore[misc,arg-type]
        def openDataFolder(self) -> None:
            path = str(self._ctrl.data_dir)
            try:
                if sys.platform == "win32":
                    os.startfile(path)  # noqa: S606 - opening the user's own data folder
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])  # noqa: S603,S607
                else:
                    subprocess.Popen(["xdg-open", path])  # noqa: S603,S607
            except Exception:
                log.exception("open data folder")

        @Slot(str, result=str)  # type: ignore[misc,arg-type]
        def readTextFile(self, url_or_path: str) -> str:
            path = QUrl(url_or_path).toLocalFile() if url_or_path.startswith("file:") else url_or_path
            try:
                return Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                self.toast.emit(f"Could not read file: {exc}", True)
                return ""

        @Slot(str, str, result=bool)  # type: ignore[misc,arg-type]
        def writeTextFile(self, url_or_path: str, text: str) -> bool:
            path = QUrl(url_or_path).toLocalFile() if url_or_path.startswith("file:") else url_or_path
            try:
                Path(path).write_text(text, encoding="utf-8")
                self.toast.emit(f"Saved {Path(path).name}", False)
                return True
            except OSError as exc:
                self.toast.emit(f"Could not write file: {exc}", True)
                return False

        @Slot(str, str, str, str, str, bool, result=str)  # type: ignore[misc,arg-type]
        def sendFeedback(
            self, kind: str, alias: str, email: str, note: str, steps: str, include_diagnostics: bool
        ) -> str:
            from autocorrect import feedback

            diag = (
                feedback.Diagnostics.from_overview(self._state("overview")) if include_diagnostics else None
            )
            result = feedback.submit(kind, alias, email, note, diag, steps=steps)  # type: ignore[arg-type]
            self.toast.emit(result.message, not result.ok)
            return json.dumps({"ok": result.ok, "message": result.message, "url": result.url})

        @Slot(result=str)  # type: ignore[misc,arg-type]
        def exportDiagnostics(self) -> str:
            """Write a diagnostics bundle (health + settings, no text content) and return its path."""
            from autocorrect import feedback

            bundle = {
                "diagnostics": feedback.Diagnostics.from_overview(self._state("overview")).as_dict(),
                "overview": self._state("overview"),
                "settings": self._settings_map(),
            }
            out = self._ctrl.data_dir / "typen-diagnostics.json"
            try:
                out.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
                self.toast.emit(f"Diagnostics written to {out}", False)
            except OSError as exc:
                self.toast.emit(f"Could not write diagnostics: {exc}", True)
                return ""
            return str(out)

    _BRIDGE_CLASS = SettingsBridge
    return SettingsBridge


def launch_pyside6_qml_ui(controller: SettingsController, initial_screen: str | None = None) -> int:
    """Launch the Qt Quick settings window under LGPLv3 compliance."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    assert_no_gpl_qt_modules_loaded()
    SettingsBridge = bridge_class()  # noqa: N806

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.setApplicationName("Typen")
    app.setOrganizationName("Typen")
    try:
        from autocorrect.branding import draw_mark

        icon_file = controller.data_dir / "typen-window-icon-v2.png"
        draw_mark(256).save(icon_file)
        app.setWindowIcon(QIcon(str(icon_file)))  # type: ignore[attr-defined]
    except Exception:
        log.debug("window icon unavailable", exc_info=True)

    font_family = load_brand_font()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    bridge = SettingsBridge(controller, font_family, initial_screen or "")
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.rootContext().setContextProperty("initialScreen", initial_screen or "")
    engine.load(QUrl.fromLocalFile(str(QML_FILE_PATH)))
    if not engine.rootObjects():
        return 1
    return int(app.exec())
