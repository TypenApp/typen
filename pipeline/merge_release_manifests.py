"""
Merge per-platform release manifests into the single `release-manifest.json`
that the public site reads.

Binaries are never committed. The release workflow (.github/workflows/release.yml)
builds every platform, attaches the installers and this merged manifest to a
GitHub Release, and commits only the small merged manifest to
`site/src/data/release-manifest.json`; the site turns each `file` into a
`https://github.com/<repo>/releases/download/v<full_version>/<file>` link.

Each platform build script writes `release-manifest-<platform>.json` next to
its artifacts (win64 from build_windows_beta.ps1, macos-arm64 / macos-x64 from
build_macos_beta.sh, linux-x86_64 / linux-aarch64 from build_linux_beta.sh).
This tool combines them:

    {
      "product": ..., "version": ..., "channel": ..., "full_version": ...,
      "release_tag": "v1.2.0-beta.4",
      "built_at": <latest>, "resources": {..., "artifacts": {name: sha256}},
      "packs": [...],
      "platforms": { "win64": {...}, "macos-arm64": {...}, "linux-x86_64": {...} },
      # legacy top-level mirror of the win64 entry (platform, code_signed, artifacts)
    }

Platforms do not share one version string: the Windows build is stable and is
versioned plainly (1.2.0, channel "stable"), while macOS and Linux are betas
(1.2.0-beta.4). All of them are attached to the one GitHub Release named by
`release_tag`, which is what the site's download links use; the top-level
`channel` / `full_version` describe that release.

Only the platforms whose manifests are present are listed, so the site can
never advertise a build that was not actually produced.

    python -m pipeline.merge_release_manifests [--downloads dist/installer] [--out site/src/data/release-manifest.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOWNLOADS = ROOT / "dist" / "installer"
DEFAULT_OUT = ROOT / "site" / "src" / "data" / "release-manifest.json"
RESOURCES_MANIFEST = ROOT / "resources" / "en_base" / "manifest.json"

PLATFORM_ORDER = ["win64", "macos-arm64", "macos-x64", "linux-x86_64", "linux-aarch64"]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _channel_of(full_version: str, version: str) -> str:
    """'1.2.0-beta.4' -> 'beta.4'; a plain '1.2.0' is the stable channel."""
    suffix = full_version[len(version) + 1 :] if full_version.startswith(f"{version}-") else ""
    return suffix or "stable"


def _release_tag(manifests: dict[str, dict[str, Any]]) -> str:
    """
    The GitHub Release every platform's files are attached to. Builds that
    record it must agree; older manifests without it (all from the same
    pre-release train) fall back to v<full_version>.
    """
    tags = {str(m["release_tag"]) for m in manifests.values() if m.get("release_tag")}
    if len(tags) > 1:
        raise SystemExit(f"platform builds disagree on the release tag: {sorted(tags)}")
    if tags:
        return tags.pop()
    versions = {str(m["full_version"]) for m in manifests.values()}
    if len(versions) > 1:
        raise SystemExit(f"platform builds disagree on version and record no release tag: {sorted(versions)}")
    return f"v{versions.pop()}"


def _platform_entry(m: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "built_at": m["built_at"],
        "full_version": m["full_version"],
        "channel": m.get("channel") or _channel_of(m["full_version"], m["version"]),
        "code_signed": bool(m.get("code_signed", False)),
        "artifacts": m.get("artifacts", []),
    }
    for extra in ("notarized", "signature_scheme"):
        if extra in m and m[extra] is not None:
            entry[extra] = m[extra]
    return entry


def collect_platform_manifests(downloads: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for p in sorted(downloads.glob("release-manifest-*.json")):
        m = _load(p)
        found[str(m["platform"])] = m
    merged_here = downloads / "release-manifest.json"
    if merged_here.exists():
        m = _load(merged_here)
        if "platforms" in m:
            # Already merged: keep entries whose per-platform file is gone (older build).
            for plat, entry in m["platforms"].items():
                found.setdefault(plat, {**m, "platform": plat, **entry})
        elif "platform" in m:
            found.setdefault(str(m["platform"]), m)
    return found


def merge(
    manifests: dict[str, dict[str, Any]],
    resources_manifest: Path = RESOURCES_MANIFEST,
    *,
    download_repo: str | None = None,
) -> dict[str, Any]:
    if not manifests:
        raise SystemExit("no release manifests found")
    ordered = sorted(
        manifests.items(),
        key=lambda kv: (PLATFORM_ORDER.index(kv[0]) if kv[0] in PLATFORM_ORDER else 99, kv[0]),
    )
    newest = max(manifests.values(), key=lambda m: m["built_at"])
    app_versions = {str(m["version"]) for m in manifests.values()}
    if len(app_versions) > 1:
        sys.stderr.write(f"warning: platform builds disagree on the app version: {sorted(app_versions)}\n")
    release_tag = _release_tag(manifests)
    release_version = release_tag[1:] if release_tag.startswith("v") else release_tag

    resources = dict(newest.get("resources", {}))
    if resources_manifest.exists():
        res = _load(resources_manifest)
        resources.update(
            bundle_version=res["version"],
            schema_version=res["schema_version"],
            word_count=res["word_count"],
            released_at=res.get("released_at"),
            artifacts=res.get("artifacts", {}),
        )

    merged: dict[str, Any] = {
        "product": newest["product"],
        "version": newest["version"],
        # The release these builds are published under (its tag), not any one platform's version.
        "channel": _channel_of(release_version, str(newest["version"])),
        "full_version": release_version,
        "release_tag": release_tag,
        "built_at": newest["built_at"],
        "resources": resources,
        "packs": newest.get("packs", []),
        "platforms": {plat: _platform_entry(m) for plat, m in ordered},
    }
    if download_repo:
        # GitHub repository ("owner/name") whose Release v<full_version> holds the files.
        # Lets the site link to a public releases-only repo when the source repo is private.
        merged["download_repo"] = download_repo
    # Legacy top-level mirror (older site code and third-party scrapers read these).
    primary = manifests.get("win64") or ordered[0][1]
    merged["platform"] = primary["platform"]
    merged["code_signed"] = bool(primary.get("code_signed", False))
    merged["artifacts"] = primary.get("artifacts", [])
    return merged


def write_sha256sums(downloads: Path, merged: dict[str, Any]) -> None:
    lines = []
    for entry in merged["platforms"].values():
        for a in entry["artifacts"]:
            lines.append(f"{a['sha256']}  {a['file']}")
    for p in merged["packs"]:
        lines.append(f"{p['sha256']}  {p['file']}")
    (downloads / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--downloads",
        type=Path,
        default=DEFAULT_DOWNLOADS,
        help="directory holding the built artifacts and release-manifest-<platform>.json files",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="where to write the merged manifest the site reads",
    )
    parser.add_argument(
        "--check", action="store_true", help="Exit 1 if --out is not up to date with --downloads"
    )
    parser.add_argument(
        "--download-repo",
        default=None,
        metavar="OWNER/NAME",
        help="GitHub repository whose Release hosts the files (recorded in the manifest for the site)",
    )
    args = parser.parse_args(argv)

    manifests = collect_platform_manifests(args.downloads)
    merged = merge(manifests, download_repo=args.download_repo)
    text = json.dumps(merged, indent=2) + "\n"
    if args.check:
        current = args.out.read_text(encoding="utf-8-sig") if args.out.exists() else ""
        if json.loads(current or "{}") != merged:
            print(f"{args.out} is stale; run `python -m pipeline.merge_release_manifests`")
            return 1
        print(f"{args.out} is up to date")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    # A copy next to the artifacts so it can be attached to the GitHub Release too.
    (args.downloads / "release-manifest.json").write_text(text, encoding="utf-8")
    write_sha256sums(args.downloads, merged)
    print(f"wrote {args.out} ({', '.join(merged['platforms'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
