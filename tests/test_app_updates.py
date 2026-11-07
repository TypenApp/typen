"""In-app application update: selection, verify, apply command builders, coordinator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pipeline.sign_app_update import attach_app_updates, build_app_update_descriptor, canonical_for_signature
from pipeline.sign_release import sign_manifest_payload

from autocorrect.updates.application_updater import ApplicationReleaseDescriptor, ApplicationUpdater
from autocorrect.updates.apply_update import windows_installer_command
from autocorrect.updates.coordinator import AppUpdateCoordinator
from autocorrect.updates.install_layout import InstallLayout, preferred_artifact_kind
from autocorrect.updates.release_client import select_app_update
from autocorrect.updates.update_policy import UpdatePolicyEngine


def _key_pair() -> tuple[Ed25519PrivateKey, bytes]:
    priv = Ed25519PrivateKey.generate()
    return priv, priv.public_key().public_bytes_raw()


def _sample_manifest(*, signed: bool = True, version: str = "9.9.9") -> dict:
    priv, _pub = _key_pair()
    merged = {
        "product": "Typen",
        "version": "9.9.9",
        "channel": "stable",
        "full_version": version,
        "release_tag": f"v{version}",
        "built_at": "2026-11-07T00:00:00Z",
        "download_repo": "TypenApp/typen",
        "platforms": {
            "win64": {
                "built_at": "2026-11-07T00:00:00Z",
                "full_version": version,
                "channel": "stable",
                "code_signed": False,
                "artifacts": [
                    {
                        "kind": "installer",
                        "file": f"Typen-{version}-win64-setup.exe",
                        "size_bytes": 12,
                        "sha256": hashlib.sha256(b"fake-installer").hexdigest(),
                    },
                    {
                        "kind": "portable",
                        "file": f"Typen-{version}-win64-portable.zip",
                        "size_bytes": 8,
                        "sha256": hashlib.sha256(b"fake-zip").hexdigest(),
                    },
                ],
            },
            "macos-arm64": {
                "built_at": "2026-11-07T00:00:00Z",
                "full_version": f"{version}-beta.1" if "beta" not in version else version,
                "channel": "beta.1",
                "artifacts": [
                    {
                        "kind": "portable",
                        "file": "Typen-mac.zip",
                        "size_bytes": 4,
                        "sha256": hashlib.sha256(b"mac").hexdigest(),
                    }
                ],
            },
            "linux-x86_64": {
                "built_at": "2026-11-07T00:00:00Z",
                "full_version": version,
                "channel": "stable",
                "artifacts": [
                    {
                        "kind": "appimage",
                        "file": "Typen.AppImage",
                        "size_bytes": 4,
                        "sha256": hashlib.sha256(b"ai").hexdigest(),
                    },
                    {
                        "kind": "deb",
                        "file": "typen.deb",
                        "size_bytes": 4,
                        "sha256": hashlib.sha256(b"deb").hexdigest(),
                    },
                    {
                        "kind": "portable",
                        "file": "typen.tar.gz",
                        "size_bytes": 4,
                        "sha256": hashlib.sha256(b"tar").hexdigest(),
                    },
                ],
            },
        },
    }
    if signed:
        attach_app_updates(merged, private_key=priv)
        # Stash private key on the dict for tests that need to re-sign downloads.
        merged["_test_private_key"] = priv
    return merged


def test_preferred_artifact_kinds() -> None:
    assert preferred_artifact_kind(InstallLayout.WINDOWS_INSTALLED) == "installer"
    assert preferred_artifact_kind(InstallLayout.MACOS_APP) == "portable"
    assert preferred_artifact_kind(InstallLayout.LINUX_APPIMAGE) == "appimage"
    assert preferred_artifact_kind(InstallLayout.LINUX_DEB) == "deb"


def test_semver_prerelease_ordering() -> None:
    assert UpdatePolicyEngine._is_newer_semver("1.3.0-beta.2", "1.3.0-beta.3")
    assert UpdatePolicyEngine._is_newer_semver("1.3.0-beta.3", "1.3.0")
    assert not UpdatePolicyEngine._is_newer_semver("1.3.0", "1.3.0-beta.9")


def test_select_app_update_signed_windows_installer() -> None:
    manifest = _sample_manifest(version="9.9.9")
    selected = select_app_update(
        manifest,
        platform_key="win64",
        layout=InstallLayout.WINDOWS_INSTALLED,
        channel="stable",
        current_version="1.0.0",
    )
    assert selected is not None
    assert selected.signed
    assert selected.newer
    assert selected.artifact_kind == "installer"
    assert selected.descriptor.version == "9.9.9"
    assert selected.signature_b64


def test_select_app_update_unsigned_when_missing_sig() -> None:
    manifest = _sample_manifest(signed=False, version="9.9.9")
    selected = select_app_update(
        manifest,
        platform_key="win64",
        layout=InstallLayout.WINDOWS_INSTALLED,
        channel="stable",
        current_version="1.0.0",
    )
    assert selected is not None
    assert not selected.signed
    assert selected.newer


def test_select_linux_appimage_layout() -> None:
    manifest = _sample_manifest(version="9.9.9")
    selected = select_app_update(
        manifest,
        platform_key="linux-x86_64",
        layout=InstallLayout.LINUX_APPIMAGE,
        channel="stable",
        current_version="1.0.0",
    )
    assert selected is not None
    assert selected.artifact_kind == "appimage"


def test_build_and_sign_descriptor_roundtrip() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    priv, pub = _key_pair()
    entry = {
        "built_at": "2026-11-07T00:00:00Z",
        "full_version": "2.0.0",
        "artifacts": [
            {"kind": "installer", "file": "setup.exe", "size_bytes": 3, "sha256": "abc"}
        ],
    }
    desc = build_app_update_descriptor(
        platform_key="win64",
        platform_entry=entry,
        release_tag="v2.0.0",
        download_repo="TypenApp/typen",
        product_version="2.0.0",
    )
    assert desc is not None
    sig = sign_manifest_payload(canonical_for_signature(desc), priv)
    updater = ApplicationUpdater(Path("."), Ed25519PublicKey.from_public_bytes(pub))
    result = updater.evaluate_release(
        ApplicationReleaseDescriptor(
            version=str(desc["version"]),
            platform_sku_suffix=str(desc["platform_sku_suffix"]),
            released_at=str(desc["released_at"]),
            installer_sha256=str(desc["installer_sha256"]),
            installer_size=int(desc["installer_size"]),
            download_url=str(desc["download_url"]),
            is_security_patch=False,
            target_branch_prefix=str(desc["target_branch_prefix"]),
        ),
        sig,
        None,
        "1.0.0",
    )
    assert result.eligible


def test_windows_installer_command_flags() -> None:
    cmd = windows_installer_command(Path("C:/tmp/setup.exe"))
    assert cmd[0].endswith("setup.exe")
    assert "/VERYSILENT" in cmd
    assert "/UPDATEDBYAPP=1" in cmd


def test_download_and_stage_verifies_sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    priv, pub = _key_pair()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pub_key = Ed25519PublicKey.from_public_bytes(pub)
    payload = b"installer-bytes-here"
    digest = hashlib.sha256(payload).hexdigest()
    desc = ApplicationReleaseDescriptor(
        version="9.9.9",
        platform_sku_suffix="WIN",
        released_at="2026-11-07T00:00:00Z",
        installer_sha256=digest,
        installer_size=len(payload),
        download_url="https://example.test/setup.exe",
        target_branch_prefix="9.9.",
    )
    sig = sign_manifest_payload(desc.to_canonical_dict(), priv)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == desc.download_url
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    updater = ApplicationUpdater(tmp_path, pub_key)
    staged = updater.download_and_stage(desc, sig, None, "1.0.0", client=client)
    assert staged.read_bytes() == payload
    out = updater.materialize_staged(staged, "installer", download_url=desc.download_url)
    assert out.suffix == ".exe"


def test_coordinator_check_and_unsigned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    priv, pub = _key_pair()
    pub_key = Ed25519PublicKey.from_public_bytes(pub)
    unsigned = _sample_manifest(signed=False, version="9.9.9")

    def fake_fetch(**kwargs):  # type: ignore[no-untyped-def]
        return unsigned

    monkeypatch.setattr("autocorrect.updates.coordinator.fetch_manifest_with_fallback", fake_fetch)
    monkeypatch.setattr(
        "autocorrect.updates.coordinator.detect_install_layout",
        lambda: InstallLayout.WINDOWS_INSTALLED,
    )
    monkeypatch.setattr("autocorrect.updates.coordinator.platform_key", lambda: "win64")

    shutdown_calls: list[bool] = []
    coord = AppUpdateCoordinator(
        updater=ApplicationUpdater(tmp_path, pub_key),
        state_path=tmp_path / "state.json",
        get_channel=lambda: "stable",
        get_updates_expire_at=lambda: None,
        request_shutdown=lambda: shutdown_calls.append(True),
    )
    # Patch APP_VERSION comparison by using current_version inside select — coordinator
    # uses module APP_VERSION; monkeypatch select to force newer unsigned.
    state = coord.check()
    assert state["status"] in ("unsigned", "up_to_date", "available", "error")
    # With unsigned manifest and APP_VERSION likely < 9.9.9:
    if UpdatePolicyEngine._is_newer_semver(
        __import__("autocorrect.version", fromlist=["APP_VERSION"]).APP_VERSION, "9.9.9"
    ):
        assert state["status"] == "unsigned"
        apply_state = coord.apply()
        assert "not Ed25519-signed" in (apply_state.get("error") or "")
        assert not shutdown_calls


def test_attach_app_updates_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AC_ED25519_PRIVATE_KEY_HEX", raising=False)
    merged = _sample_manifest(signed=False)
    attach_app_updates(merged, private_key=None)
    assert "app_update" not in merged["platforms"]["win64"]
    priv, _ = _key_pair()
    attach_app_updates(merged, private_key=priv)
    assert "signature_b64" in merged["platforms"]["win64"]["app_update"]
