# Getting Started & Cross-Platform Installation

> **Foundation** · 4 min read  
> Install Typen on Windows (stable), macOS or Linux (public beta), understand the tray service and Settings window, grant the OS permissions each platform needs, and check that corrections are live.

## Contents

1. [How Typen Works](#architecture-overview)
2. [Windows 10 & 11 Installation](#windows-setup)
3. [macOS 12+ Setup (Input Monitoring & Accessibility) — Beta](#macos-setup)
4. [Linux Setup (X11 & Wayland via IBus) — Beta](#linux-setup)

---

<a id="architecture-overview"></a>
## How Typen Works

Typen is engineered around a strict two-process separation: a lightweight, always-on background service that hooks system-wide keyboard input with sub-millisecond word evaluation latency, and an on-demand 10-screen Settings window. Both run from the same executable (AutoCorrectDesktop.exe); the Settings window is started with the --settings flag. The Qt Quick/QML front end (PySide6-Essentials) is used when installed; the current builds ship the lightweight native fallback window.

When you close the Settings window, the UI process terminates completely (0% UI CPU and 0 MB GUI RAM), while the background daemon continues correcting typos across every native and web application on your machine.

- 100% Offline Core: Zero cloud dependency for everyday spelling, grammar, homophone, and punctuation corrections.
- 166,000+-Word Memory-Mapped Lexicon: Instant cold startup (< 150ms) via zero-copy mmap binary tables.
- Free and open source: every feature is available to everyone; there is no trial, licence key or account.

<a id="windows-setup"></a>
## Windows 10 & 11 Installation

Windows is the stable platform: the build has been verified end to end on real machines. Download the installer (.exe) or portable (.zip) build from the Download page — every file is attached to the matching GitHub release — and compare its SHA-256 with the value shown there. The Windows build is not code-signed yet, so SmartScreen will show a warning on first run: choose More info, then Run anyway.

The installer offers launch-at-login and creates Start menu shortcuts for the service and for Settings. After launch a tray icon appears; right-click it to pause, open Settings, or quit. The portable build is a one-folder PyInstaller bundle: unzip it anywhere and run AutoCorrectDesktop.exe.

On Windows, AutoCorrect uses SetWindowsHookExW (WH_KEYBOARD_LL and WH_MOUSE_LL) paired with atomic SendInput (KEYEVENTF_UNICODE) packets tagged with AUTOCORRECT_EXTRA_INFO_TAG so synthetic keystrokes are never re-evaluated.

**Verify and launch from PowerShell**

```powershell
# 1. Verify the download
Get-FileHash .\Typen-<version>-win64-setup.exe -Algorithm SHA256
# ...and compare with SHA256SUMS.txt on the GitHub release

# 2. Start the background service (tray icon)
& "$env:LOCALAPPDATA\Programs\Typen\AutoCorrectDesktop.exe"

# 3. Open the Settings window (connects to the service over a Named Pipe)
& "$env:LOCALAPPDATA\Programs\Typen\AutoCorrectDesktop.exe" --settings

# Optional: print a one-line health check and exit
& "...\AutoCorrectDesktop.exe" --headless-check
```

<a id="macos-setup"></a>
## macOS 12+ Setup (Input Monitoring & Accessibility) — Beta

The macOS build is in public beta: feature-complete, with less real-world mileage than the Windows build. Check the Downloads page for availability: the macOS build is listed there only once it has been published. Open the .dmg and drag Typen to /Applications. Because Typen listens to keystrokes through a Quartz Event Tap (CGEventTapCreate) and types corrections with CGEventPost, macOS requires two permissions: Input Monitoring (to read keys) and Accessibility (to inject replacements).

On first launch macOS shows both prompts. Approve them in System Settings -> Privacy & Security -> Input Monitoring and -> Accessibility, then relaunch. If a permission is missing, the menu-bar status reads 'Not correcting' with the exact step to fix it; the service keeps running so Settings remains available.

Every focus change checks IsSecureEventInputEnabled() and the focused element's AXSecureTextField role, so password prompts and Secure Keyboard Entry terminals are never read. Launch at login is a per-user LaunchAgent (~/Library/LaunchAgents/io.autocorrect.desktop.plist) that is loaded with launchctl immediately. Data lives in ~/Library/Application Support/AutoCorrect.

<a id="linux-setup"></a>
## Linux Setup (X11 & Wayland via IBus) — Beta

The Linux build is in public beta: feature-complete, with less real-world mileage than the Windows build. Check the Downloads page for availability: Linux artifacts (.deb, AppImage, portable tar.gz) are listed there only once they have been published, each with a minisign signature. Data lives in $XDG_DATA_HOME/autocorrect (default ~/.local/share/autocorrect) and launch at login uses an XDG autostart entry.

X11 sessions: the service uses the XRecord extension to observe keys and XTest to type corrections; window class and title (EWMH _NET_ACTIVE_WINDOW / WM_CLASS) identify password managers, polkit and keyring prompts, and terminals. Because XRecord observes keys after delivery, the delimiter you typed is deleted and re-typed together with the corrected word.

Wayland sessions: compositors do not allow global key hooks, so the service reports 'Not correcting' and asks you to enable the IBus engine. Install ibus, python3-gi and gir1.2-ibus-1.0 (the .deb recommends them), then add 'English (Typen)' under Settings -> Keyboard -> Input Sources and switch to it. The engine receives IBUS_INPUT_PURPOSE_PASSWORD / PIN and the NO_SPELLCHECK hint from applications, so secure fields are never touched, and replaces text with delete_surrounding_text + commit_text.

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://autocorrect-desktop.vercel.app/docs/getting-started) · [TypenApp on GitHub](https://github.com/TypenApp)*
