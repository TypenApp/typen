"""
Integration & Unit Tests for:
- Authenticated Local IPC Server & Client (`src/autocorrect/ipc/`)
- 10-Screen Desktop Customisation Controller (`src/autocorrect/ui/settings_main.py`)
- PySide6 / Qt 6 LGPLv3 Commercial Compliance Guard (`src/autocorrect/ui/lgpl_compliance.py`)
- Declarative QML 10-Screen Structure (`src/autocorrect/ui/qml/Main.qml`)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.ipc import (
    IPCRequest,
    LocalIPCClient,
)
from autocorrect.ui import (
    GPL_FORBIDDEN_QT_MODULES,
    LGPL_ALLOWED_QT_MODULES,
    SCREEN_NAMES,
    SettingsController,
    assert_no_gpl_qt_modules_loaded,
    scan_distribution_dir_for_gpl_binaries,
)
from autocorrect.ui.qml_bridge import QML_FILE_PATH


def test_ipc_authentication_and_protocol_guards(tmp_path: Path) -> None:
    """
    Verify that `LocalIPCServer`:
    - Rejects unauthenticated or forged-token requests with `IPCAuthenticationError`.
    - Rejects mismatched `protocol_version`.
    - Allows authenticated `LocalIPCClient` calls and survives daemon restart/reconnection.
    """
    daemon = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    daemon.start(start_ipc=True)
    try:
        assert daemon.ipc_server.is_running

        # 1. Forged token is rejected
        forged_req = IPCRequest(
            method="system.get_overview",
            params={},
            auth_token="00" * 32,
        )
        forged_resp = daemon.ipc_server.handle_raw_request(forged_req.to_json_bytes())
        assert not forged_resp.ok
        assert "Unauthorized" in (forged_resp.error or "")

        # 2. Unsupported protocol_version is rejected
        bad_ver_req = IPCRequest(
            method="system.get_overview",
            params={},
            auth_token="00" * 32,
            protocol_version="99.0",
        )
        bad_ver_resp = daemon.ipc_server.handle_raw_request(bad_ver_req.to_json_bytes())
        assert not bad_ver_resp.ok
        assert "Unsupported IPC protocol_version" in (bad_ver_resp.error or "")

        # 3. Authenticated LocalIPCClient succeeds over local pipe/socket
        client = LocalIPCClient(data_dir=tmp_path)
        assert client.is_daemon_online()
        overview = client.call("system.get_overview")
        assert overview["app_version"] == "1.2.0"
        assert overview["lexicon_word_count"] > 100_000
    finally:
        daemon.stop()

    # 4. Restart daemon and confirm client automatically reconnects with the rotated token
    daemon2 = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    daemon2.start(start_ipc=True)
    try:
        client2 = LocalIPCClient(data_dir=tmp_path)
        assert client2.is_daemon_online()
    finally:
        daemon2.stop()


def test_all_10_desktop_ui_screens_end_to_end_over_live_ipc(tmp_path: Path) -> None:
    """
    End-to-end verification that `SettingsController` drives all 10 screens
    over authenticated Local IPC against a running `AutoCorrectDaemon`, mutating
    the live daemon's engine overlay, domain packs, snippets, profiles, AI controls,
    and licence state without duplicating the engine in the UI process.
    """
    assert len(SCREEN_NAMES) == 10
    daemon = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    daemon.start(start_ipc=True)
    controller = SettingsController(data_dir=tmp_path, use_memory_keyring=True)

    try:
        assert controller.is_daemon_ipc_connected()

        # --- Screen 1: Overview ---
        ov = controller.get_overview()
        assert ov["is_paused"] is False
        assert ov["active_region"] == "EN_GB"
        controller.set_paused(True)
        assert daemon.session.is_paused is True
        controller.set_paused(False)
        assert daemon.session.is_paused is False

        daemon.insights.record_spelling_correction(chars_saved=3)
        assert controller.get_overview()["insights"]["spelling_corrections"] == 1
        controller.reset_insights()
        assert controller.get_overview()["insights"]["spelling_corrections"] == 0

        # --- Screen 2: General ---
        gen = controller.update_general_settings(
            launch_at_login=True,
            rewrite_hotkey="Ctrl+Shift+G",
        )
        assert gen["launch_at_login"] is True
        assert gen["rewrite_hotkey"] == "Ctrl+Shift+G"

        # --- Screen 3: Dictionary (Custom words, Reverted Suggestions, CSV/JSON) ---
        controller.add_custom_word("PySideSix")
        assert "PySideSix" in controller.list_custom_words()
        # Verify the live daemon's engine immediately knows 'PySideSix' via IPC
        assert daemon.preference_store.overlay.is_custom_word("pysidesix")

        # Simulate a reverted word in the daemon and accept it from the UI
        daemon.preference_store.note_reverted_word("NuitkaBuild", "Nuitka")
        suggested = controller.list_suggested_words()
        assert any(s["word"] == "NuitkaBuild" for s in suggested)
        controller.accept_suggested_word("NuitkaBuild")
        assert "NuitkaBuild" in controller.list_custom_words()
        assert controller.list_suggested_words() == []

        csv_data = controller.export_dictionary_csv()
        assert "PySideSix" in csv_data
        imported_cnt = controller.import_dictionary_csv("word\nBachsSDK\n")
        assert imported_cnt == 1
        assert "BachsSDK" in controller.list_custom_words()

        # --- Screen 4: Languages & 6 Pro Domain Vocabulary Packs ---
        lang = controller.set_region("EN_US")
        assert lang["active_region"] == "EN_US"
        assert daemon.session._active_region.name == "EN_US"

        lang2 = controller.set_enabled_domain_packs(["programming", "medicine", "law"])
        enabled_ids = [p["id"] for p in lang2["domain_packs"] if p["enabled"]]
        assert set(enabled_ids) == {"programming", "medicine", "law"}
        assert daemon.engine.evaluate_token("kubernets").replacement_token == "Kubernetes"

        # --- Screen 5: Corrections, Sensitivity, Rejected & Preferred Variants ---
        corr = controller.update_correction_features(
            enable_punctuation_assist=False,
            enable_double_space_period=False,
            aggressiveness=0.85,
        )
        assert corr["enable_punctuation_assist"] is False
        assert corr["aggressiveness"] == pytest.approx(0.85)

        controller.add_rejected_correction("teh", "the")
        assert daemon.preference_store.overlay.is_rejected_pair("teh", "the")
        controller.remove_rejected_correction("teh", "the")
        assert not daemon.preference_store.overlay.is_rejected_pair("teh", "the")

        controller.set_preferred_variant("color", "colour")
        assert daemon.preference_store.overlay.get_preferred_variant("color") == "colour"
        controller.remove_preferred_variant("color")
        assert daemon.preference_store.overlay.get_preferred_variant("color") is None

        # --- Screen 6: Pro Intelligence (Local AI & BYOK Cloud AI) ---
        ai_state = controller.set_byok_api_key("openai", "sk-proj-validtestkey1234567890")
        assert ai_state["byok"]["providers"]["openai"]["has_key"] is True

        ai_state2 = controller.update_ai_settings(
            local_only_mode=True,
            daily_limit_usd="3.50",
            monthly_limit_usd="25.00",
            load_local_model=True,
        )
        assert ai_state2["byok"]["local_only_mode"] is True
        assert ai_state2["byok"]["daily_limit_usd"] == "3.50"
        assert ai_state2["local_ai"]["model_loaded"] is True
        assert daemon.spending_controller.local_only_mode is True

        # --- Screen 7: Application-Specific Profiles ---
        profs = controller.upsert_app_profile(
            "obsidian.exe",
            "Obsidian Notes",
            aggressiveness=1.1,
            active_domain_packs=["academic", "programming"],
        )
        assert any(p["app_identifier"] == "obsidian.exe" for p in profs)
        controller.delete_app_profile("obsidian.exe")
        assert not any(p["app_identifier"] == "obsidian.exe" for p in controller.list_app_profiles())

        # --- Screen 8: Text Expansion Snippets ---
        snips = controller.upsert_snippet(";addr", "100 Bishopsgate, London", "Office address")
        assert any(s["trigger"] == ";addr" for s in snips)
        assert daemon.snippet_engine.match_snippet(";addr") == "100 Bishopsgate, London"
        controller.delete_snippet(";addr")
        assert daemon.snippet_engine.match_snippet(";addr") is None

        # --- Screen 9: Independent Updates ---
        upd = controller.get_updates_state()
        assert upd["app"]["current_version"] == "1.2.0"
        assert upd["language_resources"]["schema_version"] == 1
        controller.rollback_language_resources()

        # --- Screen 10: Licence & Commercial Entitlement ---
        lic = controller.get_licence_state()
        assert lic["mode"] == "TRIAL_PRO"
        assert lic["pricing"]["standard_quote_usd"] == "14.99"
        assert lic["pricing"]["pro_quote_usd"] == "34.99"
        assert "NGN" in lic["pricing"]["regional_standard"]

        # One-Click Privacy Wipe clears custom vocabulary and preferences cleanly
        controller.privacy_wipe()
        assert controller.list_custom_words() == []
    finally:
        daemon.stop()


def test_lgplv3_compliance_and_qml_10_screen_declaration(tmp_path: Path) -> None:
    """
    Verify:
    - No GPLv3-only Qt modules are imported (`assert_no_gpl_qt_modules_loaded`).
    - Distribution directory scanner catches any accidental GPLv3 Qt binary (`Qt6Charts.dll`).
    - `Main.qml` exists and declares all 10 required customisation screens without importing
      any GPLv3 QML modules (`QtCharts`, `QtGraphs`, `QtQuick3D`, `QtVirtualKeyboard`).
    """
    assert "QtQuick" in LGPL_ALLOWED_QT_MODULES
    assert "QtQuickControls2" in LGPL_ALLOWED_QT_MODULES
    assert "QtCharts" in GPL_FORBIDDEN_QT_MODULES
    assert "QtQuick3D" in GPL_FORBIDDEN_QT_MODULES
    assert assert_no_gpl_qt_modules_loaded() == []

    # Simulate a distribution folder with an accidental GPLv3 binary
    fake_dist = tmp_path / "autocorrect.dist"
    fake_dist.mkdir()
    (fake_dist / "Qt6Core.dll").write_bytes(b"ok")
    (fake_dist / "Qt6Quick.dll").write_bytes(b"ok")
    (fake_dist / "Qt6Charts.dll").write_bytes(b"gpl_violation")
    detected = scan_distribution_dir_for_gpl_binaries(fake_dist)
    assert detected == ["Qt6Charts.dll"]

    # Verify QML file structure and absence of GPLv3 imports
    assert QML_FILE_PATH.exists()
    qml_text = QML_FILE_PATH.read_text(encoding="utf-8")
    for screen_title in SCREEN_NAMES:
        assert f'title: "{screen_title}"' in qml_text
    for forbidden_qml in ("import QtCharts", "import QtGraphs", "import QtQuick3D"):
        assert forbidden_qml not in qml_text
