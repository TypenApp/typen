#!/usr/bin/env bash
# Build the Tact macOS BETA distributables.
#
#   1. Generates icons (ICNS).
#   2. Runs PyInstaller via packaging/autocorrect.spec  -> dist/Tact.app
#   3. Signs the .app (Developer ID + Hardened Runtime) when AC_SIGN_IDENTITY is set,
#      otherwise ad-hoc signs so the bundle launches locally.
#   4. Smoke-tests the frozen binary (--version, --headless-check).
#   5. Produces a .dmg (hdiutil) and a .zip; notarises + staples the DMG when
#      the AC_NOTARY_* credentials are present.
#   6. Writes SHA-256 sums + release-manifest.json (platform: macos-<arch>).
#
# Signing / notarisation environment (all optional; unsigned beta when absent):
#   AC_SIGN_IDENTITY        "Developer ID Application: Your Name (TEAMID)"
#   AC_NOTARY_KEYCHAIN_PROFILE   name stored via `xcrun notarytool store-credentials`
#     -- or --
#   AC_NOTARY_APPLE_ID, AC_NOTARY_TEAM_ID, AC_NOTARY_PASSWORD (app-specific password)
#
# Usage:  packaging/build_macos_beta.sh [--channel beta.3] [--skip-publish]
set -euo pipefail

CHANNEL="beta.3"
SKIP_PUBLISH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --channel) CHANNEL="$2"; shift 2 ;;
    --skip-publish) SKIP_PUBLISH=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"

VERSION="$($PY -c "import sys; sys.path.insert(0,'src'); from autocorrect.version import APP_VERSION; print(APP_VERSION)")"
FULL_VERSION="$VERSION-$CHANNEL"
ARCH="$(uname -m)"            # arm64 | x86_64
case "$ARCH" in x86_64) ARCH_LABEL="x64" ;; *) ARCH_LABEL="$ARCH" ;; esac
PLATFORM="macos-$ARCH_LABEL"
DIST="$ROOT/dist"
APP="$DIST/Tact.app"
OUT="$DIST/installer"

echo "==> Tact $FULL_VERSION ($PLATFORM)"

# 0. Tooling
$PY -c "import PyInstaller" 2>/dev/null || $PY -m pip install --quiet pyinstaller
$PY -c "import Quartz, ApplicationServices, AppKit" 2>/dev/null || $PY -m pip install --quiet -e ".[macos]"

# 1. Icons
$PY packaging/make_icon.py --icns

# 2. PyInstaller
rm -rf "$APP" "$DIST/AutoCorrectDesktop"
$PY -m PyInstaller --noconfirm --clean --distpath "$DIST" --workpath "$DIST/build" packaging/autocorrect.spec

# 3. Code signing
ENTITLEMENTS="$ROOT/packaging/macos_entitlements.plist"
CODE_SIGNED=false
if [[ -n "${AC_SIGN_IDENTITY:-}" ]]; then
  echo "==> Signing with: $AC_SIGN_IDENTITY"
  # Sign every Mach-O inside-out first (PyInstaller ships many .so/.dylib), then the bundle.
  while IFS= read -r -d '' f; do
    codesign --force --options runtime --timestamp --sign "$AC_SIGN_IDENTITY" --entitlements "$ENTITLEMENTS" "$f"
  done < <(find "$APP/Contents" \( -name "*.so" -o -name "*.dylib" -o -perm -u+x -type f \) -print0)
  codesign --force --options runtime --timestamp --sign "$AC_SIGN_IDENTITY" --entitlements "$ENTITLEMENTS" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
  CODE_SIGNED=true
else
  echo "==> AC_SIGN_IDENTITY not set: ad-hoc signing (Gatekeeper will warn; beta only)"
  codesign --force --deep --sign - "$APP"
fi

# 4. Smoke test
BIN="$APP/Contents/MacOS/AutoCorrectDesktop"
SMOKE="$(mktemp -d)/autocorrect_beta_smoke"
"$BIN" --version
CHECK="$("$BIN" --headless-check --data-dir "$SMOKE" 2>&1 || true)"
echo "    $CHECK"
[[ "$CHECK" == *OK* ]] || { echo "Frozen app failed --headless-check" >&2; exit 1; }

# 5. DMG + ZIP
mkdir -p "$OUT"; rm -f "$OUT"/*.dmg "$OUT"/*.zip "$OUT"/SHA256SUMS.txt "$OUT"/release-manifest.json
ZIP="$OUT/Tact-$FULL_VERSION-$PLATFORM.zip"
DMG="$OUT/Tact-$FULL_VERSION-$PLATFORM.dmg"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Tact" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

NOTARIZED=false
if [[ "$CODE_SIGNED" == true ]]; then
  if [[ -n "${AC_NOTARY_KEYCHAIN_PROFILE:-}" ]]; then
    NOTARY_ARGS=(--keychain-profile "$AC_NOTARY_KEYCHAIN_PROFILE")
  elif [[ -n "${AC_NOTARY_APPLE_ID:-}" && -n "${AC_NOTARY_TEAM_ID:-}" && -n "${AC_NOTARY_PASSWORD:-}" ]]; then
    NOTARY_ARGS=(--apple-id "$AC_NOTARY_APPLE_ID" --team-id "$AC_NOTARY_TEAM_ID" --password "$AC_NOTARY_PASSWORD")
  else
    NOTARY_ARGS=()
  fi
  if [[ ${#NOTARY_ARGS[@]} -gt 0 ]]; then
    echo "==> Notarising DMG"
    xcrun notarytool submit "$DMG" "${NOTARY_ARGS[@]}" --wait
    xcrun stapler staple "$DMG"
    xcrun stapler staple "$APP"
    # Re-zip so the ZIP also carries the stapled ticket.
    rm -f "$ZIP"; ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
    spctl --assess --type open --context context:primary-signature -v "$DMG"
    NOTARIZED=true
  else
    echo "==> Notary credentials not set: skipping notarisation"
  fi
fi

# 6. Hashes + manifest
$PY - "$OUT" "$VERSION" "$CHANNEL" "$PLATFORM" "$CODE_SIGNED" "$NOTARIZED" <<'PYEOF'
import hashlib, json, sys, datetime, pathlib
out, version, channel, platform, signed, notarized = sys.argv[1:7]
out = pathlib.Path(out); root = out.parent.parent
res = json.loads((root / "resources/en_base/manifest.json").read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
arts, sums = [], []
for p in sorted(out.iterdir()):
    if p.suffix in (".dmg", ".zip"):
        kind = "installer" if p.suffix == ".dmg" else "portable"
        arts.append({"kind": kind, "file": p.name, "size_bytes": p.stat().st_size, "sha256": sha(p)})
        sums.append(f"{sha(p)}  {p.name}")
packs_out = out / "packs"; packs_out.mkdir(exist_ok=True); packs = []
for p in sorted((root / "resources/en_base/packs").glob("*.pack.json")):
    (packs_out / p.name).write_bytes(p.read_bytes()); pj = json.loads(p.read_text())
    packs.append({"id": pj["pack_id"], "version": pj["version"], "file": p.name, "size_bytes": p.stat().st_size,
                  "sha256": sha(p), "word_count": len(pj.get("words", {})), "direct_typo_count": len(pj.get("direct_typos", {}))})
    sums.append(f"{sha(p)}  packs/{p.name}")
manifest = {"product": "Tact", "version": version, "channel": channel, "full_version": f"{version}-{channel}",
            "platform": platform, "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "code_signed": signed == "true", "notarized": notarized == "true",
            "resources": {"bundle_version": res["version"], "schema_version": res["schema_version"], "word_count": res["word_count"]},
            "artifacts": arts, "packs": packs}
(out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
(out / f"release-manifest-{platform}.json").write_text(json.dumps(manifest, indent=2) + "\n")
for a in arts: print(f"    {a['file']:<60} {a['size_bytes']:>12,} bytes  {a['sha256']}")
PYEOF

# 7. Refresh the manifest the site reads (binaries stay in dist/installer; the
#    release workflow attaches them to the GitHub Release the site links to).
if [[ "$SKIP_PUBLISH" -eq 0 ]]; then
  $PY -m pipeline.merge_release_manifests --downloads "$OUT"
  echo "==> Artifacts in $OUT; site manifest updated."
  echo "    To publish: git tag v$FULL_VERSION && git push origin v$FULL_VERSION"
fi
