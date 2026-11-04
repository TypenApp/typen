"""
Tests for the `TypenApp` GitHub organisation multi-repository architecture,
URL consistency, documentation synchronisation, and standalone repo scaffolding.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.sync_docs import sync_docs
from scripts.build_org_repos import build_all_org_repos

from autocorrect.daemon.tray import SystemTrayController
from autocorrect.ipc.server import LocalIPCServer
from autocorrect.licensing import (
    DONATE_URL,
    GITHUB_ORG,
    GITHUB_REPO,
    GITHUB_REPO_URL,
    GITHUB_SPONSORS_URL,
    SPONSORS_HANDLE,
)
from autocorrect.ui.settings_main import SettingsController
from autocorrect.updates import (
    APP_RELEASES_REPO,
    LANGUAGE_DATA_REPO,
    MODEL_RESOURCES_REPO,
)

ROOT = Path(__file__).resolve().parent.parent


def test_organisation_constants_and_about_urls(tmp_path: Path, monkeypatch: object) -> None:
    import webbrowser

    assert GITHUB_ORG == "TypenApp"
    assert GITHUB_REPO == "TypenApp/typen"
    assert GITHUB_REPO_URL == "https://github.com/TypenApp/typen"
    assert SPONSORS_HANDLE == "TypenApp"
    assert GITHUB_SPONSORS_URL == "https://github.com/sponsors/TypenApp"
    assert DONATE_URL == "https://github.com/sponsors/TypenApp"
    assert APP_RELEASES_REPO == "TypenApp/typen"
    assert LANGUAGE_DATA_REPO == "TypenApp/language-data"
    assert MODEL_RESOURCES_REPO == "TypenApp/model-resources"

    ctl = SettingsController(data_dir=tmp_path, use_memory_keyring=True)
    about = ctl.get_about_state()
    assert about["source_url"] == "https://github.com/TypenApp/typen"
    assert about["donate_url"] == "https://github.com/sponsors/TypenApp"
    assert about["sponsors_url"] == "https://github.com/sponsors/TypenApp"
    assert LocalIPCServer is not None

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u) or True)  # type: ignore[attr-defined]
    assert ctl.open_sponsors_page() == "https://github.com/sponsors/TypenApp"
    assert ctl.open_source_repository() == "https://github.com/TypenApp/typen"
    assert opened == [
        "https://github.com/sponsors/TypenApp",
        "https://github.com/TypenApp/typen",
    ]


def test_tray_menu_and_funding_yml_point_to_github_sponsors() -> None:
    funding = (ROOT / ".github" / "FUNDING.yml").read_text(encoding="utf-8")
    assert "github: [TypenApp, litlEMPEROR]" in funding
    assert "https://autocorrect-desktop.vercel.app/donate" in funding

    tray = SystemTrayController(
        on_toggle_pause=lambda: True,
        on_quit=lambda: None,
        get_status_label=lambda: "Typen — Active",
        data_dir=Path("."),
    )
    menu = tray._build_menu()
    labels = [str(item) for item in menu.items if str(item).strip() and str(item) != "- - - -"]
    assert any("Sponsor Typen on GitHub" in label for label in labels)


def test_release_manifest_uses_typen_and_typenapp_org() -> None:
    manifest_path = ROOT / "site" / "src" / "data" / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["product"] == "Typen"
    assert manifest["download_repo"] == "TypenApp/typen"
    raw_text = manifest_path.read_text(encoding="utf-8")
    assert "Tact" not in raw_text and "tact" not in raw_text
    assert "litlEMPEROR" not in raw_text


def test_docs_sync_is_up_to_date(tmp_path: Path) -> None:
    # Verify committed docs/ directory is in lockstep with site/src/data/docs.ts
    files = sync_docs(ROOT / "docs", check=True)
    assert "README.md" in files
    assert "open-source.md" in files
    assert "TypenApp/typen" in files["open-source.md"]
    assert "TypenApp/language-data" in files["open-source.md"]
    assert "TypenApp/model-resources" in files["open-source.md"]
    assert "TypenApp/docs" in files["open-source.md"]


def test_build_all_org_repos_scaffolds_five_repositories(tmp_path: Path) -> None:
    built = build_all_org_repos(tmp_path)
    assert set(built.keys()) == {".github", "typen", "language-data", "model-resources", "docs"}

    # 1. TypenApp/.github
    assert (built[".github"] / "profile" / "README.md").exists()
    assert (built[".github"] / "SUPPORT.md").exists()
    assert (built[".github"] / "ISSUE_TEMPLATE" / "correction_report.yml").exists()

    # 2. TypenApp/typen
    assert (built["typen"] / "pyproject.toml").exists()
    assert (built["typen"] / "src" / "autocorrect" / "launcher.py").exists()

    # 3. TypenApp/language-data
    assert (built["language-data"] / "pyproject.toml").exists()
    assert (built["language-data"] / "pipeline" / "ingest.py").exists()
    assert (built["language-data"] / "resources" / "en_base" / "manifest.json").exists()
    assert (built["language-data"] / "tests" / "test_engine_quality_heldout.py").exists()

    # 4. TypenApp/model-resources
    catalog_path = built["model-resources"] / "model-catalog.json"
    assert catalog_path.exists()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["repository"] == "TypenApp/model-resources"
    assert len(catalog["models"]) == 2
    assert (built["model-resources"] / "scripts" / "sign_model_release.py").exists()

    # 5. TypenApp/docs
    assert (built["docs"] / "README.md").exists()
    assert (built["docs"] / "getting-started.md").exists()
    assert (built["docs"] / "open-source.md").exists()
