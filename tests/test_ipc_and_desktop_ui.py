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
from autocorrect.version import APP_VERSION


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
        assert overview["app_version"] == APP_VERSION
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
    and about state without duplicating the engine in the UI process.
    """
    assert len(SCREEN_NAMES) == 11
    daemon = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    daemon.start(start_ipc=True)
    controller = SettingsController(data_dir=tmp_path, use_memory_keyring=True)

    try:
        assert controller.is_daemon_ipc_connected()

        # --- Screen 1: Overview ---
        ov = controller.get_overview()
        assert ov["is_paused"] is False
        # Default language is "follow system", resolved to a concrete variant.
        assert ov["active_region"] in {"EN_GB", "EN_US", "EN_CA", "EN_AU"}
        assert ov["hold_esc_seconds"] == pytest.approx(10.0)
        assert controller.try_text("i recieved it.") == "I received it. "
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
            panic_hold_seconds=12,
            notify_pause_resume=False,
            log_level="verbose",
        )
        assert gen["launch_at_login"] is True
        assert gen["rewrite_hotkey"] == "Ctrl+Shift+G"
        assert gen["panic_hold_seconds"] == pytest.approx(12.0)
        assert daemon.kill_switch.hold_seconds == pytest.approx(12.0)
        assert gen["notify_pause_resume"] is False
        assert gen["log_level"] == "verbose"
        assert {s["key"] for s in gen["schema"]} >= {"start_paused", "ui_theme", "update_channel"}
        # The generic surface sees the same values and validates/clamps them.
        assert controller.get_all_settings("general")["panic_hold_seconds"] == pytest.approx(12.0)
        assert controller.set_settings({"panic_hold_seconds": 2})["panic_hold_seconds"] == pytest.approx(5.0)

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

        # --- Screen 4: Languages & 6 Domain Vocabulary Packs ---
        lang = controller.set_region("EN_US")
        assert lang["active_region"] == "EN_US" and lang["region_setting"] == "EN_US"
        assert daemon.session._active_region.name == "EN_US"
        assert daemon.preference_store.overlay.active_region.name == "EN_US"
        lang_auto = controller.set_region("AUTO")
        assert lang_auto["region_setting"] == "AUTO"
        assert lang_auto["active_region"] == lang_auto["system_region"]
        lang_strict = controller.update_language_settings(variant_enforcement="strict")
        assert lang_strict["variant_enforcement"] == "strict"
        assert daemon.session.features.variant_enforcement == "strict"
        controller.set_region("EN_US")

        lang2 = controller.set_enabled_domain_packs(["programming", "medicine", "law"])
        enabled_ids = [p["id"] for p in lang2["domain_packs"] if p["enabled"]]
        assert set(enabled_ids) == {"programming", "medicine", "law"}
        assert daemon.engine.evaluate_token("kubernets").replacement_token == "Kubernetes"

        # --- Screen 5: Corrections, Sensitivity, Rejected & Preferred Variants ---
        corr = controller.update_correction_features(
            enable_punctuation_assist=False,
            enable_double_space_period=False,
            aggressiveness=0.85,
            smart_quotes=True,
            min_correction_length=3,
            undo_remembers="always",
        )
        assert corr["enable_punctuation_assist"] is False
        assert corr["aggressiveness"] == pytest.approx(0.85)
        assert corr["smart_quotes"] is True and corr["min_correction_length"] == 3
        # ...and the live session picked every one of them up.
        live = daemon.session.features
        assert live.enable_punctuation_assist is False and live.smart_quotes is True
        assert live.min_correction_length == 3 and live.undo_remembers == "always"
        assert corr["effective"]["aggressiveness"] == pytest.approx(0.85)

        controller.add_rejected_correction("teh", "the")
        assert daemon.preference_store.overlay.is_rejected_pair("teh", "the")
        controller.remove_rejected_correction("teh", "the")
        assert not daemon.preference_store.overlay.is_rejected_pair("teh", "the")

        controller.set_preferred_variant("color", "colour")
        assert daemon.preference_store.overlay.get_preferred_variant("color") == "colour"
        controller.remove_preferred_variant("color")
        assert daemon.preference_store.overlay.get_preferred_variant("color") is None

        # --- Screen 6: Intelligence (Local AI & BYOK Cloud AI) ---
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
            overrides={"enable_grammar": False},
            region="EN_GB",
        )
        obsidian = next(p for p in profs if p["app_identifier"] == "obsidian.exe")
        assert obsidian["overrides"] == {"enable_grammar": False} and obsidian["region"] == "EN_GB"
        # Persisted: a fresh store sees it too.
        assert any(r["app_identifier"] == "obsidian.exe" for r in daemon.preference_store.list_app_profiles())
        apps = controller.update_apps_settings(excluded_processes=["game.exe"], code_processes=["nvim.exe"])
        assert apps["excluded_processes"] == ["game.exe"] and apps["code_processes"] == ["nvim.exe"]
        assert "overridable_keys" in apps and "enable_grammar" in apps["overridable_keys"]
        controller.delete_app_profile("obsidian.exe")
        assert not any(p["app_identifier"] == "obsidian.exe" for p in controller.list_app_profiles())

        # --- Screen 8: Text Expansion Snippets ---
        snips = controller.upsert_snippet(";addr", "100 Bishopsgate, London", "Office address")
        assert any(s["trigger"] == ";addr" for s in snips)
        assert daemon.snippet_engine.match_snippet(";addr") == "100 Bishopsgate, London"
        assert daemon.preference_store.list_snippets() == [(";addr", "100 Bishopsgate, London")]
        controller.delete_snippet(";addr")
        assert daemon.snippet_engine.match_snippet(";addr") is None
        snip_state = controller.update_snippet_settings(snippet_case_matching=False)
        assert snip_state["snippet_case_matching"] is False and daemon.snippet_engine.case_matching is False

        # --- Screen 9: Independent Updates ---
        upd = controller.get_updates_state()
        assert upd["app"]["current_version"] == APP_VERSION
        assert upd["language_resources"]["schema_version"] == 1
        assert controller.update_updates_settings(update_channel="beta")["app"]["channel"] == "beta"
        controller.rollback_language_resources()

        # --- Screen 10: About & Support ---
        about = controller.get_about_state()
        assert about["mode"] == "OPEN_SOURCE"
        assert about["licence"] == "MIT"
        assert about["donate_url"].startswith("https://")

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
