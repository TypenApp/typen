# Security, Privacy & Cryptographic Update Architecture

> **Security** · 5 min read  
> How Typen guarantees zero keystroke logging, automatic password field exclusion, Ed25519 manifest verification, and atomic Zstandard delta updates.

## Contents

1. [Zero Keystroke Logging & Ephemeral Memory Buffers](#zero-keylogging-guarantee)
2. [Automatic Password Field & Security App Exclusions](#password-and-app-exclusions)
3. [Ed25519-Signed Zstandard Delta Updates & Atomic Rollback](#signed-delta-updates)

---

<a id="zero-keylogging-guarantee"></a>
## Zero Keystroke Logging & Ephemeral Memory Buffers

Typen is architected so that your typed documents, messages, and passwords can never be reconstructed from disk. SQLitePreferenceStore (preferences.sqlite3) stores only your explicit custom dictionary words, rejected correction pairs, preferred variants, and aggregate counters.

The active word buffer holds at most the single word currently being typed, and the context ring buffer holds at most 5 integer word IDs—both flushed immediately on every window switch or mouse click.

<a id="password-and-app-exclusions"></a>
## Automatic Password Field & Security App Exclusions

Before evaluating any keystroke, the platform FocusInspector checks the active window and UI control:

- Windows (Win32FocusInspector): Inspects Win32 window styles for ES_PASSWORD and excludes password managers (1password.exe, bitwarden.exe, keepassxc.exe, dashlane.exe).
- macOS (MacAXFocusInspector): Checks AXSubrole == 'AXSecureTextField' and Quartz IsSecureEventInputEnabled().
- Linux (X11FocusInspector / WaylandIBusEngineAdapter): Inspects window class exclusions and IBUS_INPUT_PURPOSE_PASSWORD.

<a id="signed-delta-updates"></a>
## Ed25519-Signed Zstandard Delta Updates & Atomic Rollback

Language Intelligence Library updates (.tar.zst and .patch.zst) are decoupled from application binary updates. LanguageResourceUpdater verifies the Ed25519 signature over the canonical release descriptor, checks the SHA-256 digest, blocks any archive containing path traversal ('..') or executable extensions (.exe, .dll, .so, .dylib, .py, .sh), verifies per-artifact hashes in manifest.json, and performs a pre-flight smoke load before atomically swapping active_version.json.

If any check fails, or if you click 'Rollback to Last Known Good' in the Updates screen, ResourceManager immediately falls back to last_known_good_dir or the bundled baseline.

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://autocorrect-desktop.vercel.app/docs/security-privacy) · [TypenApp on GitHub](https://github.com/TypenApp)*
