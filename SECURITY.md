# Security Policy

Typen processes system-wide keyboard input on your machine. Because of that privileged position, security and privacy are foundational architectural constraints rather than optional features.

## Supported Versions

| Version | Supported |
| --- | --- |
| `1.2.x` | Yes |
| `< 1.2.0` | No (upgrade to latest `1.2.x` release) |

## Security & Privacy Guarantees

1. **Zero Keystroke Logging**: Typen holds at most the active word buffer and a 5-token integer ID ring buffer in volatile RAM, both cleared on focus change or mouse click. No typed prose is ever written to disk.
2. **Automatic Password & Secure App Exclusions**:
   - **Windows**: Inspects `ES_PASSWORD` styles and excludes password managers (`1password.exe`, `bitwarden.exe`, `keepassxc.exe`, `dashlane.exe`).
   - **macOS**: Checks `IsSecureEventInputEnabled()` and `AXSecureTextField`.
   - **Linux**: Checks EWMH window classes on X11 and `IBUS_INPUT_PURPOSE_PASSWORD` / `PIN` on Wayland.
3. **Authenticated Local IPC**: The Settings UI talks to the background daemon over a local Named Pipe (Windows) or `0600` Unix Domain Socket (macOS/Linux) authenticated with a 256-bit random hex token (`ipc.token`, mode `0600`).
4. **Ed25519 Cryptographic Update Verification**:
   - All language resource updates (`TypenApp/language-data`), optional local AI models (`TypenApp/model-resources`), and application release descriptors (`TypenApp/typen`) are verified against the embedded Ed25519 root public key (`79f7c2e422116b9597ae50d9c2f9e633d2f210b89a280983b52d6bce16344f78`) and SHA-256 digests before staging.
   - Resource archives are scanned to reject path traversal (`..`) and any executable file extensions (`.exe`, `.dll`, `.so`, `.dylib`, `.py`, `.sh`, `.bat`).

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, please report them privately using [**GitHub Private Vulnerability Reporting**](https://github.com/TypenApp/typen/security/advisories/new) on the `TypenApp/typen` repository.

Please include:
- A clear description of the vulnerability and affected platform(s) (Windows, macOS, Linux X11, Linux Wayland).
- Minimal steps or proof-of-concept code to reproduce the issue.
- Potential impact (e.g., local privilege escalation, IPC bypass, secure-field detection bypass, or archive extraction traversal).

We will acknowledge receipt within **48 hours** and work with you to validate, patch, and disclose the issue responsibly.
