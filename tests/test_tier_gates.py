"""
Tact is free software: there are no editions, trials or licence files. These
tests pin that down end to end (daemon, IPC, offline Settings fallback, input
session) so a regression that reintroduces a gate is caught immediately.
Also covers the focus monitor that makes password/terminal/excluded-app
protection and per-application profiles live.
"""

from __future__ import annotations

from pathlib import Path

from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.daemon.focus_monitor import FocusMonitor
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.ipc import LocalIPCClient
from autocorrect.licensing import DONATE_URL, EntitlementManager, EntitlementSnapshot
from autocorrect.productivity.app_profiles import ApplicationProfile
from autocorrect.ui import SettingsController


def _daemon(tmp_path: Path, *, start_ipc: bool = False) -> AutoCorrectDaemon:
    d = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d.start(start_ipc=start_ipc)
    return d


def _type(daemon: AutoCorrectDaemon, text: str) -> list[tuple[str, str]]:
    replacements: list[tuple[str, str]] = []
    for ch in text:
        key = "Space" if ch == " " else ch
        out = daemon.session.handle_key_event(KeyEvent(key_name=key, char=ch, timestamp_ms=0.0))
        if out.action == KeyAction.SUPPRESS_AND_INJECT and out.replacement_plan is not None:
            plan = out.replacement_plan
            # Normalise away the trailing delimiter and sentence-start capitalisation.
            replacements.append((plan.original_full.strip().lower(), plan.target_full.strip().lower()))
    return replacements


# --------------------------------------------------------------- entitlement


def test_entitlement_is_constant_and_fully_unlocked() -> None:
    mgr = EntitlementManager()
    snap = mgr.evaluate()
    assert snap == EntitlementSnapshot()
    assert snap.mode == "OPEN_SOURCE"
    assert snap.typing_assistance_enabled and snap.pro_features_enabled and snap.can_download_new_updates
    assert snap.updates_expire_at is None
    assert mgr.is_typing_assistance_enabled() and mgr.is_pro_enabled()
    assert DONATE_URL.startswith("https://")


# --------------------------------------------------------------------- daemon


def test_everything_is_unlocked_in_the_daemon(tmp_path: Path) -> None:
    d = _daemon(tmp_path)
    try:
        assert d.entitlement_manager.evaluate().mode == "OPEN_SOURCE"
        assert d.hooks_active
        # Layer 1 spelling...
        assert ("recieved", "received") in _type(d, "recieved ")
        # ...snippets expand...
        d.snippet_engine.add_snippet(";sig", "Best regards")
        assert (";sig", "best regards") in _type(d, ";sig ")
        # ...Local AI loads...
        d.local_ai.load_model()
        assert d.local_ai.is_model_loaded
        # ...and domain packs follow the user's preference.
        d.set_user_domain_packs({"programming"})
        assert "programming" in d.resource_manager.active_bundle.domain_packs
    finally:
        d.stop()


def test_daemon_restores_persisted_domain_packs_on_start(tmp_path: Path) -> None:
    d1 = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    d1.start(start_ipc=False)
    d1.preference_store.set_setting("enabled_domain_packs", "law,finance")
    d1.stop()
    d2 = AutoCorrectDaemon(data_dir=tmp_path, dry_run_hooks=True)
    try:
        d2.start(start_ipc=False)
        assert set(d2.resource_manager.active_bundle.domain_packs) == {"law", "finance"}
    finally:
        d2.stop()


# ------------------------------------------------------------------------ IPC


def test_ipc_accepts_every_setter_and_reports_about_state(tmp_path: Path) -> None:
    d = _daemon(tmp_path, start_ipc=True)
    try:
        client = LocalIPCClient(data_dir=tmp_path, max_retries=1)
        assert client.call("languages.get_state")["pro_enabled"] is True
        client.call("languages.set_domain_packs", {"pack_ids": ["programming"]})
        client.call("profiles.upsert", {"app_identifier": "code.exe", "display_name": "VS Code"})
        client.call("snippets.upsert", {"trigger": ";x", "expansion": "y"})
        client.call("insights.set_enabled", {"enabled": True})
        assert d.preference_store.get_setting("enabled_domain_packs", "") == "programming"

        about = client.call("about.get_state")
        assert about["mode"] == "OPEN_SOURCE" and about["licence"] == "MIT"
        assert about["donate_url"] == DONATE_URL
        assert "pricing" not in about and "device_id_hash" not in about

        ctl = SettingsController(data_dir=tmp_path, use_memory_keyring=True)
        assert ctl.is_daemon_ipc_connected()
        assert ctl.get_about_state() == about
    finally:
        d.stop()


def test_offline_settings_fallback_is_unlocked_too(tmp_path: Path) -> None:
    """With no daemon running, the UI process answers from the same constant entitlement."""
    ctl = SettingsController(data_dir=tmp_path, use_memory_keyring=True)
    assert not ctl.is_daemon_ipc_connected()
    assert ctl.get_languages_state()["pro_enabled"] is True
    ctl.set_enabled_domain_packs(["programming"])
    ctl.upsert_snippet(";x", "y")
    ctl.upsert_app_profile("code.exe", "VS Code")
    about = ctl.get_about_state()
    assert about["mode"] == "OPEN_SOURCE" and about["donate_url"] == DONATE_URL
    assert ctl.get_overview()["entitlement"]["pro_features_enabled"] is True


# ---------------------------------------------------------------------- focus


class _FakeInspector:
    def __init__(self) -> None:
        self.focus = FocusContext(process_name="notepad.exe", bundle_or_app_id="notepad.exe")

    def get_current_focus(self) -> FocusContext:
        return self.focus


def test_focus_monitor_fires_only_on_change() -> None:
    insp = _FakeInspector()
    seen: list[FocusContext] = []
    mon = FocusMonitor(insp, seen.append, poll_interval_s=0.01)
    assert mon.poll_once() is not None
    assert mon.poll_once() is None
    insp.focus = FocusContext(process_name="chrome.exe", is_password_or_secure=True)
    assert mon.poll_once() is not None
    assert [f.process_name for f in seen] == ["notepad.exe", "chrome.exe"]


def test_password_field_focus_stops_corrections(tmp_path: Path) -> None:
    d = _daemon(tmp_path)
    try:
        assert ("recieved", "received") in _type(d, "recieved ")
        d._on_focus_changed(FocusContext(process_name="chrome.exe", is_password_or_secure=True))
        assert _type(d, "recieved ") == []
        d._on_focus_changed(FocusContext(process_name="keepass.exe", is_excluded_app=True))
        assert _type(d, "recieved ") == []
        d._on_focus_changed(FocusContext(process_name="notepad.exe"))
        assert ("recieved", "received") in _type(d, "recieved ")
    finally:
        d.stop()


def test_app_profile_applies_settings_and_packs(tmp_path: Path) -> None:
    d = _daemon(tmp_path)
    try:
        d.app_profiles.set_profile(
            ApplicationProfile(
                app_identifier="code.exe",
                display_name="VS Code",
                enable_auto_capitalise=False,
                aggressiveness=0.8,
                active_domain_packs=frozenset({"programming"}),
            )
        )
        d._on_focus_changed(FocusContext(process_name="code.exe", bundle_or_app_id="code.exe"))
        assert "programming" in d.resource_manager.active_bundle.domain_packs
        assert d.session._enable_auto_capitalise is False
        d._on_focus_changed(FocusContext(process_name="notepad.exe"))
        assert d.session._enable_auto_capitalise is True
        assert "programming" not in d.resource_manager.active_bundle.domain_packs
    finally:
        d.stop()


def test_disabled_profile_excludes_app(tmp_path: Path) -> None:
    d = _daemon(tmp_path)
    try:
        d.app_profiles.set_profile(
            ApplicationProfile(app_identifier="game.exe", display_name="Game", enabled=False)
        )
        d._on_focus_changed(FocusContext(process_name="game.exe", bundle_or_app_id="game.exe"))
        assert _type(d, "recieved ") == []
    finally:
        d.stop()


def test_focus_monitor_thread_lifecycle_drives_daemon() -> None:
    insp = _FakeInspector()
    seen: list[str] = []
    mon = FocusMonitor(insp, lambda f: seen.append(f.process_name), poll_interval_s=0.01)
    mon.start()
    try:
        assert mon.is_running
        insp.focus = FocusContext(process_name="chrome.exe")
        import time

        deadline = time.monotonic() + 2.0
        while "chrome.exe" not in seen and time.monotonic() < deadline:
            time.sleep(0.01)
        assert seen[:2] == ["notepad.exe", "chrome.exe"]
    finally:
        mon.stop()
    assert not mon.is_running
