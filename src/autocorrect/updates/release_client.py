"""
Fetch the public release manifest and select a signed ApplicationReleaseDescriptor
for the running platform / install layout / update channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import httpx

from autocorrect.updates.application_updater import ApplicationReleaseDescriptor
from autocorrect.updates.install_layout import InstallLayout, preferred_artifact_kind
from autocorrect.updates.update_policy import UpdatePolicyEngine
from autocorrect.version import APP_VERSION

DEFAULT_MANIFEST_URL = "https://typen.org/release-manifest.json"
GITHUB_API_RELEASES = "https://api.github.com/repos/{repo}/releases"
USER_AGENT = f"Typen/{APP_VERSION}"


@dataclass(frozen=True, slots=True)
class SelectedAppUpdate:
    descriptor: ApplicationReleaseDescriptor
    signature_b64: str
    release_tag: str
    artifact_kind: str
    signed: bool
    newer: bool
    reason: str


def fetch_manifest(
    url: str = DEFAULT_MANIFEST_URL,
    *,
    client: httpx.Client | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    http = client or httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    owns = client is None
    try:
        resp = http.get(url)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError("release manifest is not a JSON object")
        return data
    finally:
        if owns:
            http.close()


def fetch_manifest_with_fallback(
    *,
    primary_url: str = DEFAULT_MANIFEST_URL,
    download_repo: str = "TypenApp/typen",
    channel: str = "stable",
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Try typen.org first; on failure, resolve a GitHub Release asset URL."""
    try:
        return fetch_manifest(primary_url, client=client)
    except Exception:
        pass
    tag = _resolve_github_release_tag(download_repo, channel=channel, client=client)
    url = f"https://github.com/{download_repo}/releases/download/{tag}/release-manifest.json"
    return fetch_manifest(url, client=client)


def _resolve_github_release_tag(
    repo: str,
    *,
    channel: str,
    client: httpx.Client | None = None,
) -> str:
    http = client or httpx.Client(timeout=20.0, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    owns = client is None
    try:
        resp = http.get(GITHUB_API_RELEASES.format(repo=repo), params={"per_page": 20})
        resp.raise_for_status()
        releases = resp.json()
        if not isinstance(releases, list):
            raise ValueError("unexpected GitHub releases payload")
        want_beta = channel.lower() == "beta"
        for rel in releases:
            tag = str(rel.get("tag_name") or "")
            if not tag.startswith("v"):
                continue
            is_beta = "-beta" in tag or "-rc" in tag or bool(rel.get("prerelease"))
            if want_beta and is_beta:
                return tag
            if not want_beta and not is_beta:
                return tag
        if releases:
            return str(releases[0].get("tag_name") or "")
        raise ValueError("no GitHub releases found")
    finally:
        if owns:
            http.close()


def _descriptor_from_dict(d: dict[str, Any]) -> ApplicationReleaseDescriptor:
    return ApplicationReleaseDescriptor(
        version=str(d["version"]),
        platform_sku_suffix=str(d["platform_sku_suffix"]),
        released_at=str(d["released_at"]),
        installer_sha256=str(d["installer_sha256"]),
        installer_size=int(d["installer_size"]),
        download_url=str(d["download_url"]),
        is_security_patch=bool(d.get("is_security_patch", False)),
        target_branch_prefix=str(d.get("target_branch_prefix") or "1.0."),
    )


def select_app_update(
    manifest: dict[str, Any],
    *,
    platform_key: str,
    layout: InstallLayout,
    channel: str,
    current_version: str = APP_VERSION,
    prefer_kind: str | None = None,
) -> SelectedAppUpdate | None:
    """
    Pick the signed (or unsigned) app_update for this platform.
    Returns None when the platform is missing from the manifest.
    """
    platforms = manifest.get("platforms") or {}
    entry = platforms.get(platform_key)
    if not isinstance(entry, dict):
        return None

    release_tag = str(manifest.get("release_tag") or f"v{manifest.get('full_version', '')}")
    kind_wanted = prefer_kind or preferred_artifact_kind(layout)

    signed_block = _signed_block_for_kind(entry, kind_wanted)
    if signed_block is not None:
        desc_raw = dict(signed_block["descriptor"])
        descriptor = _descriptor_from_dict(desc_raw)
        return _wrap_selection(
            descriptor,
            str(signed_block["signature_b64"]),
            release_tag,
            str(desc_raw.get("artifact_kind") or kind_wanted),
            signed=True,
            current_version=current_version,
        )

    rebuilt = _from_artifacts(entry, platform_key, kind_wanted, release_tag, manifest)
    if rebuilt is None:
        return None
    return _wrap_selection(rebuilt, "", release_tag, kind_wanted, signed=False, current_version=current_version)


def _signed_block_for_kind(entry: dict[str, Any], kind_wanted: str) -> dict[str, Any] | None:
    updates = entry.get("app_updates")
    if isinstance(updates, dict):
        block = updates.get(kind_wanted)
        if isinstance(block, dict) and block.get("descriptor") and block.get("signature_b64"):
            return block
    app_update = entry.get("app_update")
    if isinstance(app_update, dict) and app_update.get("descriptor") and app_update.get("signature_b64"):
        art_kind = str((app_update.get("descriptor") or {}).get("artifact_kind") or "")
        if not art_kind or art_kind == kind_wanted:
            return app_update
    return None


def _from_artifacts(
    entry: dict[str, Any],
    platform_key: str,
    kind_wanted: str,
    release_tag: str,
    manifest: dict[str, Any],
) -> ApplicationReleaseDescriptor | None:
    artifacts = list(entry.get("artifacts") or [])
    by_kind = {str(a.get("kind")): a for a in artifacts if isinstance(a, dict)}
    art = by_kind.get(kind_wanted) or (artifacts[0] if artifacts else None)
    if not isinstance(art, dict):
        return None
    repo = str(manifest.get("download_repo") or "TypenApp/typen")
    file_name = str(art["file"])
    sku = {"win64": "WIN", "macos-arm64": "MAC", "macos-x64": "MAC"}.get(platform_key, "LINUX")
    if platform_key.startswith("linux"):
        sku = "LINUX"
    full_version = str(entry.get("full_version") or manifest.get("full_version") or APP_VERSION)
    product_version = str(manifest.get("version") or APP_VERSION)
    branch = ".".join(product_version.split(".")[:2]) + "."
    return ApplicationReleaseDescriptor(
        version=full_version,
        platform_sku_suffix=sku,
        released_at=str(entry.get("built_at") or ""),
        installer_sha256=str(art["sha256"]),
        installer_size=int(art.get("size_bytes") or 0),
        download_url=f"https://github.com/{repo}/releases/download/{release_tag}/{file_name}",
        is_security_patch=False,
        target_branch_prefix=branch,
    )


def _wrap_selection(
    descriptor: ApplicationReleaseDescriptor,
    signature_b64: str,
    release_tag: str,
    artifact_kind: str,
    *,
    signed: bool,
    current_version: str,
) -> SelectedAppUpdate:
    eligibility = UpdatePolicyEngine.check_app_update_eligibility(
        remote_version=descriptor.version,
        remote_released_at_iso=descriptor.released_at or "1970-01-01T00:00:00Z",
        is_security_patch=descriptor.is_security_patch,
        target_branch_prefix=descriptor.target_branch_prefix,
        updates_expire_at=None,
        current_app_version=current_version,
    )
    return SelectedAppUpdate(
        descriptor=descriptor,
        signature_b64=signature_b64,
        release_tag=release_tag,
        artifact_kind=artifact_kind,
        signed=signed,
        newer=eligibility.eligible,
        reason=eligibility.reason,
    )


ProgressCallback = Callable[[int, int], None]
