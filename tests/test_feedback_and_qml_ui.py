"""
Tests for:
- `autocorrect.feedback` (validation, payload, submit via a fake transport)
- the QML page catalogue (every screen has a page file and the Typen module is complete)
- the PySide6 `SettingsBridge` (skipped when PySide6 is not installed)
- `window_list` / tray settings argv (Windows-only pieces are platform-guarded)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from autocorrect import feedback
from autocorrect.daemon.tray import build_settings_command
from autocorrect.ui import SCREEN_NAMES
from autocorrect.ui.qml_bridge import CALLABLE_METHODS, QML_DIR, QML_FILE_PATH
from autocorrect.ui.settings_main import SettingsController

# ---------------------------------------------------------------- feedback.py


def test_feedback_validation_messages() -> None:
    assert feedback.validate("praise", "a", "", "x" * 20) is not None
    assert "alias" in str(feedback.validate("bug", "  ", "", "x" * 20))
    assert "email" in str(feedback.validate("bug", "me", "not-an-email", "x" * 20))
    assert "little more" in str(feedback.validate("bug", "me", "", "short"))
    assert feedback.validate("bug", "me", "", "x" * (feedback.MAX_NOTE_CHARS + 1)) is not None
    assert feedback.validate("suggestion", "me", "me@example.com", "A decent idea here.") is None


def test_feedback_payload_and_diagnostics_never_carry_text() -> None:
    overview = {
        "app_version": "9.9.9",
        "hook_status": {"state": "active", "backend": "WH_KEYBOARD_LL", "detail": ""},
        "is_paused": False,
        "active_region": "EN_GB",
        "session": {"corrections": 3, "last_correction": {"original": "teh", "replacement": "the"}},
    }
    diag = feedback.Diagnostics.from_overview(overview)
    d = diag.as_dict()
    assert d["app_version"] == "9.9.9"
    assert d["hook_state"] == "active"
    assert d["session_corrections"] == 3
    assert "hook_detail" not in d  # empty values are dropped
    assert "teh" not in json.dumps(d)  # never the corrected text

    payload = feedback.build_payload("bug", " me ", "", "It broke.\n", diag, steps=" 1. type ")
    assert payload["kind"] == "bug"
    assert payload["alias"] == "me"
    assert payload["note"] == "It broke."
    assert payload["steps"] == "1. type"
    assert payload["source"] == "desktop"
    assert payload["diagnostics"]["active_region"] == "EN_GB"
    assert "steps" not in feedback.build_payload("suggestion", "me", "", "idea", None)


def _fake_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_feedback_submit_success_failure_and_network_error() -> None:
    seen: dict[str, object] = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            200, json={"ok": True, "url": "https://github.com/TypenApp/typen/discussions/1"}
        )

    res = feedback.submit("suggestion", "me", "", "Please add dark mode.", client=_fake_client(ok))
    assert res.ok and res.url.endswith("/discussions/1")
    assert seen["json"]["kind"] == "suggestion"  # type: ignore[index]

    def declined(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"ok": False, "error": "Too many reports"})

    res = feedback.submit("bug", "me", "", "Something broke badly.", client=_fake_client(declined))
    assert not res.ok and "Too many reports" in res.message

    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    res = feedback.submit("bug", "me", "", "Something broke badly.", client=_fake_client(boom))
    assert not res.ok and "Could not reach" in res.message

    # Validation short-circuits before any request.
    res = feedback.submit("bug", "", "", "x", client=_fake_client(boom))
    assert not res.ok and "alias" in res.message


# ---------------------------------------------------------------- QML catalogue


def test_qml_pages_exist_for_every_screen_and_module_is_complete() -> None:
    main = QML_FILE_PATH.read_text(encoding="utf-8")
    pages_dir = QML_DIR / "pages"
    for title in SCREEN_NAMES:
        assert f'title: "{title}"' in main
    files = {m.split('file: "')[1].split('"')[0] for m in main.splitlines() if 'file: "' in m}
    assert len(files) == len(SCREEN_NAMES)
    for f in files:
        assert (pages_dir / f).exists(), f
        text = (pages_dir / f).read_text(encoding="utf-8")
        assert "import Typen" in text
        for forbidden in ("import QtCharts", "import QtGraphs", "import QtQuick3D"):
            assert forbidden not in text

    qmldir = (QML_DIR / "Typen" / "qmldir").read_text(encoding="utf-8").splitlines()
    declared = [line.split()[-1] for line in qmldir if line and not line.startswith("module")]
    for rel in declared:
        assert (QML_DIR / "Typen" / rel).exists(), rel

    # Every bridge.call("<method>") in QML must be whitelisted on the bridge.
    import re

    called = set()
    for qml in list(pages_dir.glob("*.qml")) + [QML_FILE_PATH]:
        called |= set(re.findall(r'bridge\.call\("([a-z_]+)"', qml.read_text(encoding="utf-8")))
    assert called, "pages should call the bridge"
    assert called <= CALLABLE_METHODS, called - CALLABLE_METHODS


def test_tray_settings_argv_passes_screen(tmp_path: Path) -> None:
    argv = build_settings_command(tmp_path, screen="feedback")
    assert "--screen" in argv and argv[argv.index("--screen") + 1] == "feedback"
    assert "--data-dir" in argv


# ---------------------------------------------------------------- bridge (needs PySide6)

pyside = pytest.importorskip("PySide6", reason="PySide6-Essentials not installed")


@pytest.fixture
def bridge(tmp_path: Path):
    from PySide6.QtCore import QCoreApplication

    from autocorrect.ui.qml_bridge import bridge_class

    app = QCoreApplication.instance() or QCoreApplication([])
    ctrl = SettingsController(data_dir=tmp_path, use_memory_keyring=True)
    b = bridge_class()(ctrl, "Syne", "feedback")
    yield b
    del app


def test_bridge_exposes_state_and_settings(bridge) -> None:
    assert bridge.initialScreen == "feedback"
    assert bridge.fontFamily == "Syne"
    assert bridge.ipcConnected is False
    assert bridge.settings["enable_spelling"] is True
    assert bridge.overview["app_version"]
    assert bridge.general["panic_hold_seconds"] == 10.0
    assert bridge.languages["region_setting"] == "AUTO"
    assert isinstance(bridge.schema, list) and bridge.schema


def test_bridge_set_setting_and_call_roundtrip(bridge) -> None:
    bridge.setSetting("enable_spelling", False)
    bridge.setSetting("excluded_processes", ["KeePass.exe"])
    assert bridge.settings["enable_spelling"] is False
    assert bridge.settings["excluded_processes"] == ["keepass.exe"]

    res = json.loads(bridge.call("add_custom_word", json.dumps({"word": "Enwon"})))
    assert res["ok"] and "Enwon" in res["result"]
    assert "Enwon" in bridge.dictionary["words"]

    denied = json.loads(bridge.call("privacy_wipe_everything", "{}"))
    assert "not allowed" in denied["error"]

    assert bridge.tryText("i recieved it. ").startswith("I ")
    path = bridge.exportDiagnostics()
    assert Path(path).exists()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert "diagnostics" in data and "settings" in data


@pytest.mark.skipif(sys.platform != "win32", reason="Windows window enumeration")
def test_window_list_returns_processes() -> None:
    from autocorrect.adapters.windows.window_list import list_visible_windows

    rows = list_visible_windows(limit=10)
    assert isinstance(rows, list)
    for row in rows:
        assert set(row) == {"process", "title"}
        assert row["process"] == row["process"].lower()
