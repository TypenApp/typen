# 10-Screen Desktop Customisation UI & Local IPC Guide

> **Desktop App** · 7 min read  
> Walkthrough of all 10 screens in the PySide6-Essentials + Qt Quick/QML Settings application and the authenticated Local IPC protocol.

## Contents

1. [Out-of-Process UI & Authenticated Local IPC](#out-of-process-ipc)
2. [All 10 Desktop Customisation Screens](#ten-screens-walkthrough)
3. [Qt 6 / PySide6-Essentials LGPLv3 Compliance Architecture](#lgplv3-compliance)

---

<a id="out-of-process-ipc"></a>
## Out-of-Process UI & Authenticated Local IPC

The Settings interface (autocorrect-settings) never opens SQLite for direct writes while the daemon is active, and never loads duplicate mmap lexicon files. Instead, it connects to LocalIPCServer inside autocorrect-daemon over a Windows Named Pipe (\\.\pipe\AutoCorrectIPC_<hash>) or a 0600 Unix Domain Socket (~/.autocorrect_desktop/ipc.sock).

Every request is authenticated using a 256-bit random hex token stored in ~/.autocorrect_desktop/ipc.token (chmod 0600). Changes made in any screen update the daemon's zero-latency PreferenceMemoryOverlay between keystrokes.

<a id="ten-screens-walkthrough"></a>
## All 10 Desktop Customisation Screens

The left navigation rail provides instant access to all 10 customisation domains:

- 1. Overview: Live system hook status, Pause/Resume toggle, active English variant, mmap lexicon word count, and privacy-preserving LocalInsightsStore counters.
- 2. General: Launch at OS login (Windows Run registry key / macOS LaunchAgents plist), global hotkeys (Ctrl+Shift+R rewrite, Ctrl+Alt+P pause), and One-Click Privacy Wipe.
- 3. Dictionary: Search, add, and delete custom words; review Suggested Words captured from double-Backspace reverts; and bulk Import/Export via CSV or portable JSON.
- 4. Languages: Switch between EN_GB (British), EN_US (American), EN_CA (Canadian), EN_AU (Australian), and UNIVERSAL English, and toggle the 6 Domain Vocabulary Packs.
- 5. Corrections: Tune the Aggressiveness slider (0.50 to 1.50), toggle punctuation assistance, double-space period, and auto-capitalisation, and manage Rejected Pairs (Never Correct) and Preferred Variants (Always Prefer).
- 6. Intelligence: Inspect Layer 2 Local AI hardware acceleration (DirectML / CoreML / AVX2) and configure Layer 3 BYOK Cloud AI keys, Local-Only Lockdown, and daily/monthly USD spend caps.
- 7. Profiles: Configure per-application profiles (e.g. code.exe vs winword.exe) with custom aggressiveness, punctuation, and domain packs.
- 8. Text Expansion: Create and edit snippets (;sig, @@email) with dynamic {{date}} and {{time}} macros.
- 9. Updates: Independently manage Desktop App updates, Zstandard delta Language Intelligence updates (with one-click Rollback to Last Known Good), and Local AI Model downloads.
- 10. About: Version, MIT licence, link to the source and a button to support the project with a donation.

<a id="lgplv3-compliance"></a>
## Qt 6 / PySide6-Essentials LGPLv3 Compliance Architecture

Typen depends exclusively on PySide6-Essentials (QtCore, QtGui, QtQml, QtQuick, QtQuickControls2, QtQuickLayouts, QtQuickDialogs, QtSvg) under the GNU Lesser General Public License v3 (LGPLv3).

GPLv3-only modules (such as QtCharts, QtGraphs, QtQuick3D, and QtVirtualKeyboard) are strictly excluded and verified at both runtime and build time via src/autocorrect/ui/lgpl_compliance.py. Packaging uses one-folder (never one-file) mode so any Qt shared libraries (.dll / .dylib / .so) remain user-replaceable on disk. The current Windows build does not bundle Qt at all; it ships the native fallback Settings window.

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://autocorrect-desktop-six.vercel.app/docs/customisation) · [TypenApp on GitHub](https://github.com/TypenApp)*
