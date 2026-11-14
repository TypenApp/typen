# Typen

Offline-first, system-wide autocorrect, inline predictive typing and writing assistant for Windows, macOS and Linux.
One small background process (`typen.exe`) owns the keyboard hook, an adaptive personal language model, and a memory-mapped 464k-word V2 English lexicon; an on-demand Settings window talks to it over authenticated local IPC. Nothing you type leaves the machine.

Typen is free and open source (MIT) and funded by donations only. There are no editions,
trials or licence keys: every feature is available to everyone.

- Website: <https://typen.org> (live demo runs the real engine)
- Organisation: <https://github.com/TypenApp>
- Downloads: GitHub Releases (<https://github.com/TypenApp/typen/releases>)
- Donate: <https://github.com/sponsors/TypenApp>
- Current version: `2.0.0` / `v2.0.0-beta.1` (see `site/src/data/release-manifest.json`)

## Official `TypenApp` repositories

Typen is organised under [`github.com/TypenApp`](https://github.com/TypenApp) across focused repositories:

| Repository | Purpose |
| --- | --- |
| [`TypenApp/typen`](https://github.com/TypenApp/typen) | Main desktop application, OS keyboard hooks, Settings UI, packaging and public website |
| [`TypenApp/language-data`](https://github.com/TypenApp/language-data) | Global English lexicon pipeline, confusion sets, domain vocabulary packs and held-out quality corpus |
| [`TypenApp/model-resources`](https://github.com/TypenApp/model-resources) | Optional Layer 2 on-device ONNX / GGUF grammar & rewrite model descriptors and Ed25519 signing tools |
| [`TypenApp/docs`](https://github.com/TypenApp/docs) | Product documentation, architecture guides and CLI reference |

## Repository layout

| Path | What it is |
| --- | --- |
| `src/autocorrect/core` | Spelling, joined-word splitter, confusion-set, punctuation & capitalisation engine (Layer 1) |
| `src/autocorrect/intelligence` | Zero-copy mmap readers for the V2 binary lexicon artifacts + `AdaptivePersonalLM` prefix trie |
| `src/autocorrect/input` | `InputSessionManager` keystroke automaton, suffix-diff planner, boundary history stack, undo ledger |
| `src/autocorrect/adapters` | OS adapters: Win32 LL hook, inline ghost placeholder overlay, Quartz event tap, X11 XRecord/XTest, IBus engine |
| `src/autocorrect/daemon` | Background service, focus monitor, tray, login-startup registration |
| `src/autocorrect/licensing` | Always-allowed entitlement seam + the Ed25519 public key that verifies signed updates |
| `src/autocorrect/ipc` | Authenticated local IPC (Named Pipe / Unix socket) between daemon and Settings |
| `src/autocorrect/ui` | Settings controller + QML (PySide6) and native fallback windows |
| `pipeline/` | Lexicon V2 build pipeline, regression runner, manifest merger |
| `packaging/` | PyInstaller spec, Inno Setup script, macOS/Linux build scripts, plists |
| `resources/en_base` | Compiled V2 binary language bundle shipped with the app (464,269 words, lexicon v2) |
| `site/` | Next.js public site (Vercel) |

The packaged executable is `typen.exe` (`typen` on macOS and Linux). Everything a user sees says Typen.

## Development

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,ui]"                          # add [macos] / [linux] on those platforms
pytest                                              # ~390 tests
ruff check src pipeline tests                       # lint gate used in CI
typen --headless-check                              # boots every subsystem, prints one status line
typen --no-tray                                     # LIVE: installs the real OS keyboard hook
typen --settings                                    # Settings window (talks to a running daemon)
```

Engine quality is tracked by two layers of tests: the curated corpus in
`tests/test_core_standard.py` and the **held-out** set in
`tests/test_engine_quality_heldout.py` (Wikipedia common-misspellings list and
hand-written prose that are never used to build the lexicon). Thresholds there are
only ever raised.

### Per-platform notes

| | Hook | Injection | Permissions / requirements |
| --- | --- | --- | --- |
| Windows | `WH_KEYBOARD_LL` + `WH_MOUSE_LL` | `SendInput` (`KEYEVENTF_UNICODE`) | none |
| macOS | `CGEventTapCreate` (session tap) | `CGEventPost` Unicode events | Input Monitoring + Accessibility (TCC) |
| Linux / X11 | XRecord (passive) | XTest, with spare-keycode remap for off-keymap glyphs | `RECORD` and `XTEST` server extensions |
| Linux / Wayland | IBus engine (`--ibus`) | `delete_surrounding_text` + `commit_text` | `ibus`, `python3-gi`, `gir1.2-ibus-1.0` |

The daemon picks the backend at start (`daemon/app.py::_install_platform_hook`) and exposes
the result as `hook_status` over IPC; the tray and Settings show the remediation when a
hook could not be installed instead of silently doing nothing.

User data directory: `~/.autocorrect_desktop` (Windows), `~/Library/Application Support/Typen`
(macOS), `$XDG_DATA_HOME/typen` (Linux). Override with `--data-dir` or `TYPEN_DATA_DIR`.

## Signed updates

Language-resource, model and application updates are Ed25519-signed. Only the **public**
root key is in the client (`licensing/root_key.py`); the private key lives on the signing
machine (`~/.typen_signing/`, never in this repository).

## Building release artifacts

```powershell
pwsh packaging/build_windows_beta.ps1 -Channel beta.1     # Typen-2.0.0-win64-setup.exe + portable .zip
```
```bash
packaging/build_macos_beta.sh --channel beta.1            # Typen-2.0.0-beta.1-macos-*.dmg + .zip (signs/notarises if AC_SIGN_IDENTITY / AC_NOTARY_* set)
packaging/build_linux_beta.sh --channel beta.1            # tar.gz + AppImage + .deb (minisign if AC_MINISIGN_KEY set)
```

The channel names the GitHub Release (`v2.0.0-beta.1`) that hosts every
platform's files. Windows is the stable platform, so its files and version are
plain `2.0.0`; the macOS and Linux betas are `2.0.0-beta.1`. Each script leaves
its artifacts in `dist/installer/` with a `release-manifest-<platform>.json`, and
runs `pipeline/merge_release_manifests.py` to refresh
`site/src/data/release-manifest.json`. **Binaries are never committed.**
To publish, push a tag:

```bash
git tag v2.0.0-beta.1 && git push origin v2.0.0-beta.1
```

`.github/workflows/release.yml` then builds all three platforms, attaches the
installers, `SHA256SUMS.txt` and the merged manifest to a GitHub Release, and
commits the merged manifest to the website's source repository. Vercel
redeploys the site from that commit; every download link points into the release, so
the site only ever lists platforms and files that were actually built.

### Website live demo

The demo on the home page is the real engine running as a Vercel Python function
(`site/api/demo.py`). `site/scripts/vendor-engine.mjs` copies `src/autocorrect` and
`resources/en_base` into `site/api/_vendor/` at install time, so the function always
runs the engine at the same commit as the site. Locally, `next dev` proxies the demo to
`typen-sandbox --no-browser` on `127.0.0.1:8765` instead.

Code signing is environment-gated and off by default:

| Platform | Variables | Without them |
| --- | --- | --- |
| Windows | `AC_WIN_SIGN_PFX` (+`_PASSWORD`) or `AC_WIN_SIGN_SHA1`, `AC_WIN_SIGN_TIMESTAMP` | unsigned; SmartScreen warns |
| macOS | `AC_SIGN_IDENTITY`, `AC_NOTARY_KEYCHAIN_PROFILE` or `AC_NOTARY_APPLE_ID`/`_TEAM_ID`/`_PASSWORD` | ad-hoc signed; Gatekeeper warns |
| Linux | `AC_MINISIGN_KEY` | unsigned (SHA-256 only) |

## Supporting the project

Typen has no paid tier and never will. If it saves you time, consider a donation at
<https://github.com/sponsors/TypenApp>. Bug reports and pull requests are equally welcome.

## Licence

MIT. See `LICENSE` for the full text and the licences of bundled third-party components.
