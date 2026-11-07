# Getting Started & Cross-Platform Installation

> **Foundation** · 5 min read  
> Install Typen on Windows (stable), macOS or Linux (public beta), understand the tray service and Settings window, grant the OS permissions each platform needs, and check that corrections are live.

## Contents

1. [How Typen Works](#architecture-overview)
2. [Windows 10 & 11 Installation](#windows-setup)
3. [macOS 12+ Setup (Input Monitoring & Accessibility) — Beta](#macos-setup)
4. [Linux Setup (X11 & Wayland via IBus) — Beta](#linux-setup)
5. [Pausing and the Esc Kill Switch](#kill-switch)
6. [Safe Mode](#safe-mode)
7. [Logs and Command-Line Flags](#logs-and-flags)

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

The installer offers launch-at-login and creates Start menu shortcuts for the service and for Settings. After launch the Typen mark (a black tile with "Aa_" and a red squiggle; white on dark taskbars, grey while paused) appears in the system tray, and on the very first run the Settings window opens so you can see the service is live. The keyboard hook is only attached once the tray icon is on screen, so Pause and Quit are always reachable. Right-click the icon to pause, open Settings, or quit; launching the Start-menu entry again while the service is running opens Settings instead of a second copy. The portable build is a one-folder PyInstaller bundle: unzip it anywhere and run AutoCorrectDesktop.exe.

On Windows, Typen uses SetWindowsHookExW (WH_KEYBOARD_LL) to observe keys and Raw Input (WM_INPUT) to notice mouse clicks, paired with atomic SendInput (KEYEVENTF_UNICODE) packets tagged with AUTOCORRECT_EXTRA_INFO_TAG so synthetic keystrokes are never re-evaluated. The hook callback does nothing but queue the event and return, so Typen can never hold up the system input chain; all correction work runs on a separate worker thread, and if that worker ever falls behind, the hook releases itself and the tray reports 'Not correcting' rather than slowing your machine down.

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

<a id="kill-switch"></a>
## Pausing and the Esc Kill Switch

There are three ways to stop Typen from touching your keyboard, from gentlest to strongest:

- Pause hotkey — Ctrl+Alt+P (changeable under Settings -> General). Toggles pause from any application; the tray icon turns grey while paused. Ctrl+Alt+, opens Settings.
- Esc switch — hold Esc for 10 seconds. If anything ever feels wrong, hold the Escape key down for 10 seconds (adjustable between 5 and 60 seconds in Settings -> General, or switch it off there). Typen pauses and shows a notification; hold Esc again for 10 seconds to resume, or use the tray menu or the Settings window. The switch is watched independently of the keyboard hook, so it works even if the hook itself is the problem. It is available on Windows, macOS and X11 (not on Wayland, where Typen never holds a global hook).
- Quit from the tray menu, or --stop from a terminal (see below).

<a id="safe-mode"></a>
## Safe Mode

Once the kill switch has fired, Typen stays in safe mode across restarts: the service and tray still start, Settings still works, but no keyboard hook is attached and the status reads 'Not correcting — Typing assistance was switched off by the emergency stop (Esc held)'. To go live again, choose 'Resume typing assistance' in the tray menu, press the pause hotkey, click Resume in Settings, or start the service with --resume. You can also enter safe mode deliberately with --safe-mode.

<a id="logs-and-flags"></a>
## Logs and Command-Line Flags

Typen writes a rotating log (1 MB x 5 files) to <data dir>/logs/typen.log; the service's data directory is %USERPROFILE%\.autocorrect_desktop on Windows, ~/Library/Application Support/AutoCorrect on macOS and ~/.local/share/autocorrect on Linux. The log records hook installation, hotkey registration, health degradations and any unhandled exception, so it is the first thing to attach to a bug report. Set TYPEN_LOG_LEVEL=DEBUG for more detail.

The same flags work with python -m autocorrect.launcher when running from source, and --data-dir <path> points any of them at an alternative data directory.

**Service control flags**

```powershell
# Open Settings (starts the service first if it is not running)
& "...\AutoCorrectDesktop.exe" --settings

# Ask a running service to shut down cleanly (falls back to terminating it)
& "...\AutoCorrectDesktop.exe" --stop

# Start without attaching the keyboard hook (tray + Settings only)
& "...\AutoCorrectDesktop.exe" --safe-mode

# Clear safe mode and start correcting again
& "...\AutoCorrectDesktop.exe" --resume

# One-line health check (hook state, data dir), then exit
& "...\AutoCorrectDesktop.exe" --headless-check
```

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://typen.org/docs/getting-started) · [TypenApp on GitHub](https://github.com/TypenApp)*
