"""
Build and optionally Ed25519-sign per-platform `app_update` descriptors for
in-app application updates.

When `AC_ED25519_PRIVATE_KEY_HEX` is set (pair of the public key baked into
`autocorrect.licensing.root_key`), each platform entry in the merged release
manifest gains:

    "app_update": { "descriptor": {...}, "signature_b64": "..." }   # preferred kind
    "app_updates": {
      "installer": { "descriptor": {...}, "signature_b64": "..." },
      "portable":  { ... },
      ...
    }

Without the secret, descriptors are omitted and the desktop client will report
that an update exists but is not signed for in-app install.
"""

from __future__ import annotations

import os
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pipeline.sign_release import sign_manifest_payload

# Preferred artifact kinds for the singular `app_update` convenience field.
_KIND_PRIORITY: dict[str, tuple[str, ...]] = {
    "win64": ("installer", "portable"),
    "macos-arm64": ("portable", "installer"),
    "macos-x64": ("portable", "installer"),
    "linux-x86_64": ("appimage", "portable", "deb"),
    "linux-aarch64": ("appimage", "portable", "deb"),
}

_SKU: dict[str, str] = {
    "win64": "WIN",
    "macos-arm64": "MAC",
    "macos-x64": "MAC",
    "linux-x86_64": "LINUX",
    "linux-aarch64": "LINUX",
}

_UNSET: object = object()


def build_app_update_descriptor(
    *,
    platform_key: str,
    platform_entry: dict[str, Any],
    release_tag: str,
    download_repo: str,
    product_version: str,
    artifact: dict[str, Any] | None = None,
) -> dict[str, object] | None:
    """Return the canonical ApplicationReleaseDescriptor dict, or None if no artifact."""
    art = artifact
    if art is None:
        artifacts = list(platform_entry.get("artifacts") or [])
        by_kind = {str(a.get("kind")): a for a in artifacts if isinstance(a, dict)}
        for kind in _KIND_PRIORITY.get(platform_key, ("portable",)):
            if kind in by_kind:
                art = by_kind[kind]
                break
        if art is None and artifacts:
            art = artifacts[0]
    if art is None:
        return None
    file_name = str(art["file"])
    full_version = str(platform_entry.get("full_version") or product_version)
    sku = _SKU.get(platform_key, "WIN")
    branch = ".".join(product_version.split(".")[:2]) + "."
    download_url = f"https://github.com/{download_repo}/releases/download/{release_tag}/{file_name}"
    return {
        "version": full_version,
        "platform_sku_suffix": sku,
        "released_at": str(platform_entry.get("built_at") or ""),
        "installer_sha256": str(art["sha256"]),
        "installer_size": int(art.get("size_bytes") or 0),
        "download_url": download_url,
        "is_security_patch": False,
        "target_branch_prefix": branch,
        "artifact_kind": str(art.get("kind") or ""),
        "artifact_file": file_name,
    }


def canonical_for_signature(descriptor: dict[str, object]) -> dict[str, object]:
    """Match ApplicationReleaseDescriptor.to_canonical_dict field set."""
    return {
        "version": descriptor["version"],
        "platform_sku_suffix": descriptor["platform_sku_suffix"],
        "released_at": descriptor["released_at"],
        "installer_sha256": descriptor["installer_sha256"],
        "installer_size": descriptor["installer_size"],
        "download_url": descriptor["download_url"],
        "is_security_patch": descriptor["is_security_patch"],
        "target_branch_prefix": descriptor["target_branch_prefix"],
    }


def load_private_key_from_env() -> Ed25519PrivateKey | None:
    raw = os.environ.get("AC_ED25519_PRIVATE_KEY_HEX", "").strip().lower()
    if not raw:
        return None
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw))


def attach_app_updates(
    merged: dict[str, Any],
    *,
    private_key: Ed25519PrivateKey | None | object = _UNSET,
) -> dict[str, Any]:
    """
    Mutate `merged` platforms with `app_update` / `app_updates` blocks.
    Pass `private_key=None` to force unsigned (tests). Omit to read env.
    """
    if private_key is _UNSET:
        key = load_private_key_from_env()
    else:
        key = private_key  # type: ignore[assignment]
    if key is None:
        return merged

    release_tag = str(merged.get("release_tag") or f"v{merged.get('full_version', '')}")
    download_repo = str(merged.get("download_repo") or "TypenApp/typen")
    product_version = str(merged.get("version") or "0.0.0")
    platforms = merged.get("platforms") or {}
    for plat, entry in platforms.items():
        artifacts = [a for a in (entry.get("artifacts") or []) if isinstance(a, dict)]
        by_kind: dict[str, dict[str, Any]] = {}
        for art in artifacts:
            kind = str(art.get("kind") or "")
            if not kind:
                continue
            desc = build_app_update_descriptor(
                platform_key=str(plat),
                platform_entry=entry,
                release_tag=release_tag,
                download_repo=download_repo,
                product_version=product_version,
                artifact=art,
            )
            if desc is None:
                continue
            sig = sign_manifest_payload(canonical_for_signature(desc), key)
            by_kind[kind] = {"descriptor": desc, "signature_b64": sig}
        if not by_kind:
            continue
        entry["app_updates"] = by_kind
        preferred = None
        for kind in _KIND_PRIORITY.get(str(plat), ("portable",)):
            if kind in by_kind:
                preferred = by_kind[kind]
                break
        entry["app_update"] = preferred or next(iter(by_kind.values()))
    return merged
