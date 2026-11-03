"""
Tier gating, end to end: Standard vs Pro vs trial-expired, enforced in the
daemon, over IPC, in the offline Settings fallback, and in the input session.
Also covers the focus monitor that makes password/terminal/excluded-app
protection and per-application profiles live.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pipeline.issue_licence import issue_certificate

from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.daemon.focus_monitor import FocusMonitor
from autocorrect.input.ports import FocusContext, KeyAction, KeyEvent
from autocorrect.ipc import IPCError, LocalIPCClient
from autocorrect.licensing.signed_licence import Edition, current_platform_sku
from autocorrect.productivity.app_profiles import ApplicationProfile
from autocorrect.ui import SettingsController

DEVICE = "11" * 32


def _daemon_with(tmp_path: Path, edition: Edition | None, *, start_ipc: bool = False) -> AutoCorrectDaemon:
    """Daemon whose licence dir holds a signed cert of `edition` (None = no cert -> trial)."""
    root = Ed25519PrivateKey.generate()
    if edition is not None:
        cert = issue_certificate(root, current_platform_sku(edition), DEVICE, order_id="T")
        (tmp_path / "licence").mkdir(parents=True, exist_ok=True)
        (tmp_path / "licence" / "entitlement.lic").write_text(cert.to_json(), encoding="utf-8")
    d = AutoCorrectDaemon(
        data_dir=tmp_path, dry_run_hooks=True, device_id_hash=DEVICE, public_key=root.public_key()
    )
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


# --------------------------------------------------------------------- daemon


def test_standard_licence_types_but_has_no_pro(tmp_path: Path) -> None:
    d = _daemon_with(tmp_path, Edition.STANDARD)
    try:
        snap = d.entitlement_manager.evaluate()
        assert snap.mode == "LICENSED_STANDARD"
        assert snap.typing_assistance_enabled and not snap.pro_features_enabled
        assert d.hooks_active
        # Layer 1 spelling still works for Standard...
        assert ("recieved", "received") in _type(d, "recieved ")
        # ...but snippets (Pro) never expand even if one is registered.
        d.snippet_engine.add_snippet(";sig", "Best regards")
        assert all(tgt != "best regards" for _, tgt in _type(d, ";sig "))
        # ...and Local AI refuses to load.
        with pytest.raises(PermissionError):
            d.local_ai.load_model()
        # ...and domain packs are forced off even if preferences say otherwise.
        d.preference_store.set_setting("enabled_domain_packs", "programming")
        d.set_user_domain_packs({"programming"})
        assert d.resource_manager.active_bundle.domain_packs == {}
    finally:
        d.stop()


def test_pro_licence_unlocks_snippets_and_packs(tmp_path: Path) -> None:
    d = _daemon_with(tmp_path, Edition.PRO)
    try:
        assert d.entitlement_manager.evaluate().mode == "LICENSED_PRO"
        d.snippet_engine.add_snippet(";sig", "Best regards")
        assert (";sig", "best regards") in _type(d, ";sig ")
        d.set_user_domain_packs({"programming"})
        assert "programming" in d.resource_manager.active_bundle.domain_packs
    finally:
        d.stop()


def test_expired_trial_releases_hooks_and_passes_keys_through(tmp_path: Path) -> None:
    d = _daemon_with(tmp_path, None)
    try:
        assert d.entitlement_manager.evaluate().mode == "TRIAL_PRO"
        assert d.hooks_active
        later = datetime.now(UTC) + timedelta(days=15)
        snap = d.entitlement_manager.evaluate(now_utc=later)
        assert snap.mode == "TRIAL_EXPIRED"
        assert not d.hooks_active  # on_typing_disabled callback fired
        assert _type(d, "recieved ") == []
    finally:
        d.stop()


def test_daemon_restores_persisted_domain_packs_on_start(tmp_path: Path) -> None:
    root = Ed25519PrivateKey.generate()
    cert = issue_certificate(root, current_platform_sku(Edition.PRO), DEVICE, order_id="T")
    (tmp_path / "licence").mkdir(parents=True)
    (tmp_path / "licence" / "entitlement.lic").write_text(cert.to_json(), encoding="utf-8")
    d1 = AutoCorrectDaemon(
        data_dir=tmp_path, dry_run_hooks=True, device_id_hash=DEVICE, public_key=root.public_key()
    )
    d1.start(start_ipc=False)
    d1.preference_store.set_setting("enabled_domain_packs", "law,finance")
    d1.stop()
    d2 = AutoCorrectDaemon(
        data_dir=tmp_path, dry_run_hooks=True, device_id_hash=DEVICE, public_key=root.public_key()
    )
    try:
        d2.start(start_ipc=False)
        assert set(d2.resource_manager.active_bundle.domain_packs) == {"law", "finance"}
    finally:
        d2.stop()


# ------------------------------------------------------------------------ IPC


def test_ipc_rejects_pro_setters_for_standard_licence(tmp_path: Path) -> None:
    d = _daemon_with(tmp_path, Edition.STANDARD, start_ipc=True)
    try:
        client = LocalIPCClient(data_dir=tmp_path, max_retries=1)
        assert client.call("languages.get_state")["pro_enabled"] is False
        for method, params in (
            ("languages.set_domain_packs", {"pack_ids": ["programming"]}),
            ("profiles.upsert", {"app_identifier": "code.exe", "display_name": "VS Code"}),
            ("snippets.upsert", {"trigger": ";x", "expansion": "y"}),
            ("insights.set_enabled", {"enabled": True}),
        ):
            with pytest.raises(IPCError, match="Pro Edition"):
                client.call(method, params)
        # Clearing packs / disabling insights is always allowed.
        client.call("languages.set_domain_packs", {"pack_ids": []})
        client.call("insights.set_enabled", {"enabled": False})
        # Standard-tier settings remain available.
        assert client.call("languages.set_region", {"region": "EN_US"})["active_region"] == "EN_US"

        # The Settings controller must surface the refusal, not fall back to SQLite.
        ctl = SettingsController(data_dir=tmp_path, use_memory_keyring=True)
        assert ctl.is_daemon_ipc_connected()
        with pytest.raises(PermissionError):
            ctl.set_enabled_domain_packs(["programming"])
        assert d.preference_store.get_setting("enabled_domain_packs", "") == ""
    finally:
        d.stop()


def test_offline_settings_fallback_enforces_pro(tmp_path: Path) -> None:
    """With no daemon running, the UI process evaluates the same signed sources."""
    root = Ed25519PrivateKey.generate()
    cert = issue_certificate(root, current_platform_sku(Edition.STANDARD), DEVICE, order_id="T")
    (tmp_path / "licence").mkdir(parents=True)
    (tmp_path / "licence" / "entitlement.lic").write_text(cert.to_json(), encoding="utf-8")
    ctl = SettingsController(data_dir=tmp_path, use_memory_keyring=True)
    ctl._device_id_hash = DEVICE  # bind to the cert's device for this test
    ctl._entitlement_mgr._device_id_hash = DEVICE
    ctl._entitlement_mgr._public_key = root.public_key()
    assert not ctl.is_daemon_ipc_connected()
    assert ctl.get_languages_state()["pro_enabled"] is False
    with pytest.raises(PermissionError):
        ctl.set_enabled_domain_packs(["programming"])
    with pytest.raises(PermissionError):
        ctl.upsert_snippet(";x", "y")
    with pytest.raises(PermissionError):
        ctl.upsert_app_profile("code.exe", "VS Code")


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
    d = _daemon_with(tmp_path, Edition.PRO)
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


def test_app_profile_applies_settings_and_packs_for_pro_only(tmp_path: Path) -> None:
    for edition, expect_pack in ((Edition.PRO, True), (Edition.STANDARD, False)):
        data = tmp_path / edition.value
        data.mkdir()
        d = _daemon_with(data, edition)
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
            assert ("programming" in d.resource_manager.active_bundle.domain_packs) is expect_pack
            assert d.session._enable_auto_capitalise is (not expect_pack)
            d._on_focus_changed(FocusContext(process_name="notepad.exe"))
            assert d.session._enable_auto_capitalise is True
            assert "programming" not in d.resource_manager.active_bundle.domain_packs
        finally:
            d.stop()


def test_disabled_profile_excludes_app(tmp_path: Path) -> None:
    d = _daemon_with(tmp_path, Edition.PRO)
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
