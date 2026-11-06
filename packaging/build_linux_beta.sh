#!/usr/bin/env bash
# Build the Typen Linux BETA distributables (x86_64 / aarch64).
#
#   1. Generates freedesktop PNG icons.
#   2. Runs PyInstaller via packaging/autocorrect.spec       -> dist/AutoCorrectDesktop/
#   3. Smoke-tests the frozen binary (--version, --headless-check).
#   4. Produces:
#        - tar.gz portable archive
#        - AppImage (if `appimagetool` is on PATH or APPIMAGETOOL is set)
#        - .deb (if `dpkg-deb` is available)
#   5. Signs every artifact with minisign when AC_MINISIGN_KEY points at a secret key
#      (Linux has no OS-level code signing; minisign gives users a verifiable signature).
#   6. Writes SHA-256 sums + release-manifest-linux-<arch>.json.
#
# Runtime requirements on the user's machine (documented in the .deb Depends and README):
#   X11 session: libx11 (python-xlib is bundled; XRecord/XTest server extensions)
#   Wayland:     ibus + python3-gi (the IBus engine runs with the system Python)
#
# Usage:  packaging/build_linux_beta.sh [--channel beta.3] [--skip-publish]
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
ARCH="$(uname -m)"            # x86_64 | aarch64
case "$ARCH" in x86_64) DEB_ARCH="amd64" ;; aarch64) DEB_ARCH="arm64" ;; *) DEB_ARCH="$ARCH" ;; esac
PLATFORM="linux-$ARCH"
DIST="$ROOT/dist"
APPDIR_SRC="$DIST/AutoCorrectDesktop"
OUT="$DIST/installer"

echo "==> Typen $FULL_VERSION ($PLATFORM)"

# 0. Tooling
$PY -c "import PyInstaller" 2>/dev/null || $PY -m pip install --quiet pyinstaller
$PY -c "import Xlib" 2>/dev/null || $PY -m pip install --quiet -e ".[linux]"
# The Settings window is PySide6/QML; without it the frozen app would ship the tkinter fallback.
$PY -c "import PySide6.QtQml" 2>/dev/null || $PY -m pip install --quiet -e ".[ui]"

# 1. Icons
$PY packaging/make_icon.py --png

# 2. PyInstaller
rm -rf "$APPDIR_SRC"
$PY -m PyInstaller --noconfirm --clean --distpath "$DIST" --workpath "$DIST/build" packaging/autocorrect.spec

# 3. Smoke test (headless: no DISPLAY needed for --headless-check)
BIN="$APPDIR_SRC/AutoCorrectDesktop"
SMOKE="$(mktemp -d)/autocorrect_beta_smoke"
"$BIN" --version
CHECK="$("$BIN" --headless-check --data-dir "$SMOKE" 2>&1 || true)"
echo "    $CHECK"
[[ "$CHECK" == *OK* ]] || { echo "Frozen binary failed --headless-check" >&2; exit 1; }

mkdir -p "$OUT"; rm -f "$OUT"/*."$PLATFORM".* "$OUT"/*.AppImage "$OUT"/*.deb "$OUT"/*.minisig

# 4a. Portable tarball
TARBALL="$OUT/Typen-$FULL_VERSION-$PLATFORM-portable.tar.gz"
tar -C "$DIST" -czf "$TARBALL" AutoCorrectDesktop

# Shared desktop entry + icon theme (used by AppImage and .deb)
DESKTOP_FILE="$(mktemp)"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Typen
GenericName=Autocorrect
Comment=System-wide offline autocorrect and writing assistant
Exec=AutoCorrectDesktop
Icon=autocorrect-desktop
Terminal=false
Categories=Utility;Accessibility;
Keywords=spelling;autocorrect;typing;
StartupNotify=false
X-GNOME-UsesNotifications=false
EOF

# 4b. AppImage
APPIMAGETOOL="${APPIMAGETOOL:-$(command -v appimagetool || true)}"
if [[ -n "$APPIMAGETOOL" ]]; then
  APPDIR="$DIST/AutoCorrectDesktop.AppDir"
  rm -rf "$APPDIR"; mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications"
  cp -R "$APPDIR_SRC"/. "$APPDIR/usr/bin/"
  cp -R packaging/icons/hicolor "$APPDIR/usr/share/icons/" 2>/dev/null || { mkdir -p "$APPDIR/usr/share/icons"; cp -R packaging/icons/hicolor "$APPDIR/usr/share/icons/"; }
  cp "$DESKTOP_FILE" "$APPDIR/autocorrect-desktop.desktop"
  cp "$DESKTOP_FILE" "$APPDIR/usr/share/applications/autocorrect-desktop.desktop"
  cp packaging/icons/hicolor/256x256/apps/autocorrect-desktop.png "$APPDIR/autocorrect-desktop.png"
  cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/AutoCorrectDesktop" "$@"
EOF
  chmod +x "$APPDIR/AppRun"
  # mktemp creates the desktop file 0600 and cp preserves it; appimagetool refuses non-world-readable AppDirs.
  chmod -R a+rX "$APPDIR"
  APPIMAGE="$OUT/Typen-$FULL_VERSION-$PLATFORM.AppImage"
  ARCH="$ARCH" "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE" >/dev/null
  echo "    built $(basename "$APPIMAGE")"
else
  echo "==> appimagetool not found: skipping AppImage"
fi

# 4c. Debian package
if command -v dpkg-deb >/dev/null 2>&1; then
  PKG="$DIST/deb/autocorrect-desktop_${VERSION}~${CHANNEL}_${DEB_ARCH}"
  rm -rf "$PKG"; mkdir -p "$PKG/DEBIAN" "$PKG/opt/autocorrect-desktop" "$PKG/usr/bin" "$PKG/usr/share/applications" "$PKG/usr/share/icons" "$PKG/etc/xdg/autostart"
  cp -R "$APPDIR_SRC"/. "$PKG/opt/autocorrect-desktop/"
  ln -s /opt/autocorrect-desktop/AutoCorrectDesktop "$PKG/usr/bin/AutoCorrectDesktop"
  ln -s /opt/autocorrect-desktop/AutoCorrectDesktop "$PKG/usr/bin/autocorrect-desktop"
  cp "$DESKTOP_FILE" "$PKG/usr/share/applications/autocorrect-desktop.desktop"
  cp -R packaging/icons/hicolor "$PKG/usr/share/icons/"
  # IBus component so Wayland users can pick "English (AutoCorrect)" as an input source.
  mkdir -p "$PKG/usr/share/ibus/component" "$PKG/usr/libexec"
  $PY -m autocorrect.adapters.linux.ibus_component --exec /usr/libexec/ibus-engine-autocorrect > "$PKG/usr/share/ibus/component/autocorrect.xml"
  cat > "$PKG/usr/libexec/ibus-engine-autocorrect" <<'EOF'
#!/bin/sh
# IBus engine wrapper: runs with the system Python (needs python3-gi + gir1.2-ibus-1.0)
# but reuses the bundled AutoCorrect runtime for the lexicon/engine.
exec /opt/autocorrect-desktop/AutoCorrectDesktop --ibus "$@"
EOF
  chmod +x "$PKG/usr/libexec/ibus-engine-autocorrect"
  INSTALLED_KB="$(du -sk "$PKG/opt" | cut -f1)"
  cat > "$PKG/DEBIAN/control" <<EOF
Package: autocorrect-desktop
Version: ${VERSION}~${CHANNEL}
Section: utils
Priority: optional
Architecture: ${DEB_ARCH}
Installed-Size: ${INSTALLED_KB}
Maintainer: Omnii <https://github.com/TypenApp/typen/issues>
Depends: libc6 (>= 2.31), libx11-6, libxtst6, libxext6
Recommends: ibus, python3-gi, gir1.2-ibus-1.0, gnome-shell-extension-appindicator | libayatana-appindicator3-1
Homepage: https://autocorrect-desktop.vercel.app
Description: System-wide offline autocorrect and writing assistant
 Corrects spelling, contextual confusions, punctuation and capitalisation as
 you type in any application. Works via XRecord/XTest on X11 and as an IBus
 input method on Wayland. Fully offline; licences are verified locally.
EOF
  cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q || true
# Let a running IBus daemon discover the new engine.
command -v ibus >/dev/null 2>&1 && (ibus write-cache --system >/dev/null 2>&1 || true)
exit 0
EOF
  chmod 755 "$PKG/DEBIAN/postinst"
  chmod -R a+rX "$PKG/opt" "$PKG/usr"
  # The package Version keeps the Debian "~" pre-release ordering, but the *file name* must not:
  # GitHub rewrites "~" to "." in release asset names, which would break every download link.
  DEB="$OUT/autocorrect-desktop_${VERSION}-${CHANNEL}_${DEB_ARCH}.deb"
  dpkg-deb --build --root-owner-group "$PKG" "$DEB" >/dev/null
  echo "    built $(basename "$DEB")"
else
  echo "==> dpkg-deb not found: skipping .deb"
fi
rm -f "$DESKTOP_FILE"

# 5. minisign signatures
CODE_SIGNED=false
if [[ -n "${AC_MINISIGN_KEY:-}" ]] && command -v minisign >/dev/null 2>&1; then
  for f in "$OUT"/*.tar.gz "$OUT"/*.AppImage "$OUT"/*.deb; do
    [[ -f "$f" ]] || continue
    minisign -S -s "$AC_MINISIGN_KEY" -m "$f" -t "Typen $FULL_VERSION $PLATFORM"
  done
  CODE_SIGNED=true
else
  echo "==> AC_MINISIGN_KEY not set (or minisign missing): artifacts are unsigned"
fi

# 6. Hashes + manifest
$PY - "$OUT" "$VERSION" "$CHANNEL" "$PLATFORM" "$CODE_SIGNED" <<'PYEOF'
import hashlib, json, sys, datetime, pathlib
out, version, channel, platform, signed = sys.argv[1:6]
out = pathlib.Path(out); root = out.parent.parent
res = json.loads((root / "resources/en_base/manifest.json").read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
kinds = {".gz": "portable", ".AppImage": "appimage", ".deb": "deb"}
arts, sums = [], []
for p in sorted(out.iterdir()):
    if p.suffix in kinds and platform in p.name or p.suffix == ".deb":
        a = {"kind": kinds[p.suffix], "file": p.name, "size_bytes": p.stat().st_size, "sha256": sha(p)}
        sig = p.with_name(p.name + ".minisig")
        if sig.exists(): a["minisig"] = sig.name
        arts.append(a); sums.append(f"{sha(p)}  {p.name}")
packs_out = out / "packs"; packs_out.mkdir(exist_ok=True); packs = []
for p in sorted((root / "resources/en_base/packs").glob("*.pack.json")):
    (packs_out / p.name).write_bytes(p.read_bytes()); pj = json.loads(p.read_text())
    packs.append({"id": pj["pack_id"], "version": pj["version"], "file": p.name, "size_bytes": p.stat().st_size,
                  "sha256": sha(p), "word_count": len(pj.get("words", {})), "direct_typo_count": len(pj.get("direct_typos", {}))})
    sums.append(f"{sha(p)}  packs/{p.name}")
manifest = {"product": "Typen", "version": version, "channel": channel, "full_version": f"{version}-{channel}",
            "release_tag": f"v{version}-{channel}",
            "platform": platform, "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "code_signed": signed == "true", "signature_scheme": "minisign" if signed == "true" else None,
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
