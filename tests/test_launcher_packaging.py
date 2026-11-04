"""
Tests for the unified executable entry point (`autocorrect.launcher`), the tray
controller's process-spawn contract, and frozen-build resource resolution.
These guard the behaviours the packaged Windows beta depends on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from autocorrect import launcher
from autocorrect.daemon.tray import SystemTrayController, build_settings_command
from autocorrect.intelligence import resource_manager


def test_launcher_version_flag_reports_channel(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        launcher.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert launcher.APP_DISPLAY_NAME == "Tact" and "Tact" in out
    assert launcher.RELEASE_CHANNEL in out


def test_launcher_headless_check_initialises_every_subsystem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = launcher.main(["--headless-check", "--data-dir", str(tmp_path)])
    assert code == 0
    out = capsys.readouterr().out
    assert " OK " in out
    assert "schema" in out
    assert (tmp_path / "preferences.sqlite3").exists()


def test_settings_command_uses_module_when_running_from_source(tmp_path: Path) -> None:
    cmd = build_settings_command(tmp_path)
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "autocorrect.ui.settings_main"]
    assert str(tmp_path) in cmd


def test_settings_command_reinvokes_executable_when_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = build_settings_command(tmp_path)
    assert cmd[0] == sys.executable
    assert "--settings" in cmd
    assert "-m" not in cmd


def test_tray_controller_builds_menu_without_display() -> None:
    pytest.importorskip("pystray")
    calls: list[str] = []
    tray = SystemTrayController(
        on_toggle_pause=lambda: calls.append("toggle") or True,
        on_quit=lambda: calls.append("quit"),
        get_status_label=lambda: "AutoCorrect — Active",
        data_dir=Path("."),
        is_paused=lambda: False,
    )
    menu = tray._build_menu()
    labels = [str(item) for item in menu.items if str(item).strip() and str(item) != "- - - -"]
    assert any("Open Settings" in label for label in labels)
    assert any("Pause typing assistance" in label for label in labels)
    assert any("Quit" in label for label in labels)
    img = SystemTrayController.create_tray_icon_image(active=True)
    assert img.size == (64, 64)


def test_bundled_resources_prefer_meipass_when_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_internal = tmp_path / "_internal" / "resources" / "en_base"
    fake_internal.mkdir(parents=True)
    (fake_internal / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert resource_manager._resolve_bundled_resources_dir() == fake_internal


def test_bundled_resources_fall_back_to_repo_checkout() -> None:
    resolved = resource_manager._resolve_bundled_resources_dir()
    assert (resolved / "manifest.json").exists()
    assert resolved.name == "en_base"
