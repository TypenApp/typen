"""
Merging per-platform release manifests into the one the site reads.

The Windows build is stable and versioned plainly; macOS and Linux are betas.
All three hang off one GitHub Release, named by `release_tag`, and that tag is
what the site must use for download links.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pipeline.merge_release_manifests import collect_platform_manifests, merge


def _manifest(platform: str, full_version: str, channel: str, built_at: str, **extra: object) -> dict:
    return {
        "product": "Typen",
        "version": "1.2.0",
        "channel": channel,
        "full_version": full_version,
        "platform": platform,
        "built_at": built_at,
        "code_signed": False,
        "resources": {"bundle_version": "1.0.9", "schema_version": 1, "word_count": 166475},
        "artifacts": [
            {
                "kind": "installer",
                "file": f"Typen-{full_version}-{platform}.bin",
                "size_bytes": 1,
                "sha256": "0" * 64,
            }
        ],
        "packs": [],
        **extra,
    }


def _write(downloads: Path, manifests: list[dict]) -> None:
    downloads.mkdir(parents=True, exist_ok=True)
    for m in manifests:
        (downloads / f"release-manifest-{m['platform']}.json").write_text(json.dumps(m), encoding="utf-8")


def test_stable_windows_and_beta_unix_share_one_release(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _manifest("win64", "1.2.0", "stable", "2026-11-04T03:07:26Z", release_tag="v1.2.0-beta.6"),
            _manifest(
                "macos-arm64", "1.2.0-beta.6", "beta.6", "2026-11-04T03:06:30Z", release_tag="v1.2.0-beta.6"
            ),
            _manifest(
                "linux-x86_64", "1.2.0-beta.6", "beta.6", "2026-11-04T03:07:13Z", release_tag="v1.2.0-beta.6"
            ),
        ],
    )
    merged = merge(collect_platform_manifests(tmp_path), resources_manifest=tmp_path / "none.json")

    # The release (tag) is what the top level describes...
    assert merged["release_tag"] == "v1.2.0-beta.6"
    assert merged["full_version"] == "1.2.0-beta.6" and merged["channel"] == "beta.6"
    assert merged["version"] == "1.2.0"
    # ...while each platform keeps its own version: no beta in the Windows file name.
    win = merged["platforms"]["win64"]
    assert win["full_version"] == "1.2.0" and win["channel"] == "stable"
    assert win["artifacts"][0]["file"] == "Typen-1.2.0-win64.bin"
    assert merged["platforms"]["macos-arm64"]["full_version"] == "1.2.0-beta.6"
    assert merged["platforms"]["macos-arm64"]["channel"] == "beta.6"
    # Legacy top-level mirror still points at the Windows files.
    assert merged["artifacts"] == win["artifacts"]


def test_release_tag_falls_back_for_older_manifests(tmp_path: Path) -> None:
    _write(tmp_path, [_manifest("win64", "1.2.0-beta.5", "beta.5", "2026-11-04T03:07:26Z")])
    merged = merge(collect_platform_manifests(tmp_path), resources_manifest=tmp_path / "none.json")
    assert merged["release_tag"] == "v1.2.0-beta.5"
    assert merged["platforms"]["win64"]["channel"] == "beta.5"


def test_disagreeing_release_tags_are_refused(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _manifest("win64", "1.2.0", "stable", "2026-11-04T03:07:26Z", release_tag="v1.2.0-beta.6"),
            _manifest(
                "linux-x86_64", "1.2.0-beta.5", "beta.5", "2026-11-04T03:07:13Z", release_tag="v1.2.0-beta.5"
            ),
        ],
    )
    with pytest.raises(SystemExit):
        merge(collect_platform_manifests(tmp_path), resources_manifest=tmp_path / "none.json")
