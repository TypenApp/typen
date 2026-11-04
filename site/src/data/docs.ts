export interface DocSection {
  heading: string;
  id: string;
  paragraphs: string[];
  codeBlock?: {
    language: string;
    title: string;
    code: string;
  };
  bullets?: string[];
}

export interface DocArticle {
  slug: string;
  title: string;
  shortTitle: string;
  category: string;
  summary: string;
  readingTime: string;
  sections: DocSection[];
}

export const DOC_ARTICLES: DocArticle[] = [
  {
    slug: "getting-started",
    title: "Getting Started & Cross-Platform Installation",
    shortTitle: "Getting Started",
    category: "Foundation",
    summary:
      "Install Typen on Windows (stable), macOS or Linux (public beta), understand the tray service and Settings window, grant the OS permissions each platform needs, and check that corrections are live.",
    readingTime: "5 min read",
    sections: [
      {
        id: "architecture-overview",
        heading: "How Typen Works",
        paragraphs: [
          "Typen is engineered around a strict two-process separation: a lightweight, always-on background service that hooks system-wide keyboard input with sub-millisecond word evaluation latency, and an on-demand 10-screen Settings window. Both run from the same executable (AutoCorrectDesktop.exe); the Settings window is started with the --settings flag. The Qt Quick/QML front end (PySide6-Essentials) is used when installed; the current builds ship the lightweight native fallback window.",
          "When you close the Settings window, the UI process terminates completely (0% UI CPU and 0 MB GUI RAM), while the background daemon continues correcting typos across every native and web application on your machine.",
        ],
        bullets: [
          "100% Offline Core: Zero cloud dependency for everyday spelling, grammar, homophone, and punctuation corrections.",
          "166,000+-Word Memory-Mapped Lexicon: Instant cold startup (< 150ms) via zero-copy mmap binary tables.",
          "Free and open source: every feature is available to everyone; there is no trial, licence key or account.",
        ],
      },
      {
        id: "windows-setup",
        heading: "Windows 10 & 11 Installation",
        paragraphs: [
          "Windows is the stable platform: the build has been verified end to end on real machines. Download the installer (.exe) or portable (.zip) build from the Download page — every file is attached to the matching GitHub release — and compare its SHA-256 with the value shown there. The Windows build is not code-signed yet, so SmartScreen will show a warning on first run: choose More info, then Run anyway.",
          "The installer offers launch-at-login and creates Start menu shortcuts for the service and for Settings. After launch the Typen mark (a black tile with \"Aa_\" and a red squiggle; white on dark taskbars, grey while paused) appears in the system tray, and on the very first run the Settings window opens so you can see the service is live. The keyboard hook is only attached once the tray icon is on screen, so Pause and Quit are always reachable. Right-click the icon to pause, open Settings, or quit; launching the Start-menu entry again while the service is running opens Settings instead of a second copy. The portable build is a one-folder PyInstaller bundle: unzip it anywhere and run AutoCorrectDesktop.exe.",
          "On Windows, Typen uses SetWindowsHookExW (WH_KEYBOARD_LL) to observe keys and Raw Input (WM_INPUT) to notice mouse clicks, paired with atomic SendInput (KEYEVENTF_UNICODE) packets tagged with AUTOCORRECT_EXTRA_INFO_TAG so synthetic keystrokes are never re-evaluated. The hook callback does nothing but queue the event and return, so Typen can never hold up the system input chain; all correction work runs on a separate worker thread, and if that worker ever falls behind, the hook releases itself and the tray reports 'Not correcting' rather than slowing your machine down.",
        ],
        codeBlock: {
          language: "powershell",
          title: "Verify and launch from PowerShell",
          code: `# 1. Verify the download
Get-FileHash .\\Typen-<version>-win64-setup.exe -Algorithm SHA256
# ...and compare with SHA256SUMS.txt on the GitHub release

# 2. Start the background service (tray icon)
& "$env:LOCALAPPDATA\\Programs\\Typen\\AutoCorrectDesktop.exe"

# 3. Open the Settings window (connects to the service over a Named Pipe)
& "$env:LOCALAPPDATA\\Programs\\Typen\\AutoCorrectDesktop.exe" --settings

# Optional: print a one-line health check and exit
& "...\\AutoCorrectDesktop.exe" --headless-check`,
        },
      },
      {
        id: "macos-setup",
        heading: "macOS 12+ Setup (Input Monitoring & Accessibility) — Beta",
        paragraphs: [
          "The macOS build is in public beta: feature-complete, with less real-world mileage than the Windows build. Check the Downloads page for availability: the macOS build is listed there only once it has been published. Open the .dmg and drag Typen to /Applications. Because Typen listens to keystrokes through a Quartz Event Tap (CGEventTapCreate) and types corrections with CGEventPost, macOS requires two permissions: Input Monitoring (to read keys) and Accessibility (to inject replacements).",
          "On first launch macOS shows both prompts. Approve them in System Settings -> Privacy & Security -> Input Monitoring and -> Accessibility, then relaunch. If a permission is missing, the menu-bar status reads 'Not correcting' with the exact step to fix it; the service keeps running so Settings remains available.",
          "Every focus change checks IsSecureEventInputEnabled() and the focused element's AXSecureTextField role, so password prompts and Secure Keyboard Entry terminals are never read. Launch at login is a per-user LaunchAgent (~/Library/LaunchAgents/io.autocorrect.desktop.plist) that is loaded with launchctl immediately. Data lives in ~/Library/Application Support/AutoCorrect.",
        ],
      },
      {
        id: "linux-setup",
        heading: "Linux Setup (X11 & Wayland via IBus) — Beta",
        paragraphs: [
          "The Linux build is in public beta: feature-complete, with less real-world mileage than the Windows build. Check the Downloads page for availability: Linux artifacts (.deb, AppImage, portable tar.gz) are listed there only once they have been published, each with a minisign signature. Data lives in $XDG_DATA_HOME/autocorrect (default ~/.local/share/autocorrect) and launch at login uses an XDG autostart entry.",
          "X11 sessions: the service uses the XRecord extension to observe keys and XTest to type corrections; window class and title (EWMH _NET_ACTIVE_WINDOW / WM_CLASS) identify password managers, polkit and keyring prompts, and terminals. Because XRecord observes keys after delivery, the delimiter you typed is deleted and re-typed together with the corrected word.",
          "Wayland sessions: compositors do not allow global key hooks, so the service reports 'Not correcting' and asks you to enable the IBus engine. Install ibus, python3-gi and gir1.2-ibus-1.0 (the .deb recommends them), then add 'English (Typen)' under Settings -> Keyboard -> Input Sources and switch to it. The engine receives IBUS_INPUT_PURPOSE_PASSWORD / PIN and the NO_SPELLCHECK hint from applications, so secure fields are never touched, and replaces text with delete_surrounding_text + commit_text.",
        ],
      },
      {
        id: "kill-switch",
        heading: "Pausing and the Esc Kill Switch",
        paragraphs: [
          "There are three ways to stop Typen from touching your keyboard, from gentlest to strongest:",
        ],
        bullets: [
          "Pause hotkey — Ctrl+Alt+P (changeable under Settings -> General). Toggles pause from any application; the tray icon turns grey while paused. Ctrl+Alt+, opens Settings.",
          "Esc kill switch — hold Esc for 15 seconds. If anything ever feels wrong, hold the Escape key down for 15 seconds (adjustable between 3 and 120 seconds in Settings -> General, or switch it off there). Typen releases its keyboard hook immediately, pauses, shows a notification, and writes a safe-mode marker. The kill switch is watched independently of the keyboard hook, so it works even if the hook itself is the problem. It is available on Windows, macOS and X11 (not on Wayland, where Typen never holds a global hook).",
          "Quit from the tray menu, or --stop from a terminal (see below).",
        ],
      },
      {
        id: "safe-mode",
        heading: "Safe Mode",
        paragraphs: [
          "Once the kill switch has fired, Typen stays in safe mode across restarts: the service and tray still start, Settings still works, but no keyboard hook is attached and the status reads 'Not correcting — Typing assistance was switched off by the emergency stop (Esc held)'. To go live again, choose 'Resume typing assistance' in the tray menu, press the pause hotkey, click Resume in Settings, or start the service with --resume. You can also enter safe mode deliberately with --safe-mode.",
        ],
      },
      {
        id: "logs-and-flags",
        heading: "Logs and Command-Line Flags",
        paragraphs: [
          "Typen writes a rotating log (1 MB x 5 files) to <data dir>/logs/typen.log; the service's data directory is %USERPROFILE%\\.autocorrect_desktop on Windows, ~/Library/Application Support/AutoCorrect on macOS and ~/.local/share/autocorrect on Linux. The log records hook installation, hotkey registration, health degradations and any unhandled exception, so it is the first thing to attach to a bug report. Set TYPEN_LOG_LEVEL=DEBUG for more detail.",
          "The same flags work with python -m autocorrect.launcher when running from source, and --data-dir <path> points any of them at an alternative data directory.",
        ],
        codeBlock: {
          language: "powershell",
          title: "Service control flags",
          code: `# Open Settings (starts the service first if it is not running)
& "...\\AutoCorrectDesktop.exe" --settings

# Ask a running service to shut down cleanly (falls back to terminating it)
& "...\\AutoCorrectDesktop.exe" --stop

# Start without attaching the keyboard hook (tray + Settings only)
& "...\\AutoCorrectDesktop.exe" --safe-mode

# Clear safe mode and start correcting again
& "...\\AutoCorrectDesktop.exe" --resume

# One-line health check (hook state, data dir), then exit
& "...\\AutoCorrectDesktop.exe" --headless-check`,
        },
      },
    ],
  },
  {
    slug: "core-engine",
    title: "Core Typing Engine, Suffix-Diff Replacement & Undo Mechanics",
    shortTitle: "Core Engine & Undo",
    category: "Core Architecture",
    summary:
      "Deep dive into InputSessionManager, SuffixDiffPlanner, retroactive two-word homophone repair, sentence capitalisation, and deliberate double-Backspace undo.",
    readingTime: "6 min read",
    sections: [
      {
        id: "word-boundary-evaluation",
        heading: "Word Boundary Evaluation & Caret Invalidation",
        paragraphs: [
          "Unlike intrusive browser extensions that parse entire DOM trees on every keystroke, InputSessionManager maintains a tiny ephemeral ActiveWordBuffer and a 5-token ContextRingBuffer.",
          "Whenever you click the mouse, press an arrow/navigation key (Left, Right, Home, End), or use any Ctrl/Alt/Cmd shortcut, the word buffer immediately transitions to BufferState.TAINTED. A tainted buffer never backspaces or mutates surrounding text until a clean word boundary restarts.",
        ],
      },
      {
        id: "suffix-diff-planner",
        heading: "Flicker-Free Suffix-Diff Replacement (SuffixDiffPlanner)",
        paragraphs: [
          "When replacing a misspelled token such as 'recieved ' with 'received ', SuffixDiffPlanner computes the longest common prefix ('rec', length 3) and only backspaces the diverging suffix ('ieved', 5 backspaces) before injecting 'eived ' in a single atomic OS input packet.",
          "This eliminates visual caret jitter and prevents race conditions in fast electron, terminal, or rich-text editors.",
        ],
        codeBlock: {
          language: "python",
          title: "SuffixDiffPlanner Example (src/autocorrect/input/diff_planner.py)",
          code: `plan = SuffixDiffPlanner.plan(
    original_full="recieved ",
    target_full="received ",
    delimiter_was_suppressed=True,
)
# plan.common_prefix_len == 3 ("rec")
# plan.backspaces_to_send == 5 ("ieved")
# plan.text_to_inject == "eived "`,
        },
      },
      {
        id: "retroactive-homophones-and-grammar",
        heading: "Retroactive Two-Word Homophone & Subject-Verb Repair",
        paragraphs: [
          "Some confusions cannot be resolved until the following word is completed. When you type 'your ' followed by 'welcome ', the engine evaluates the two-word bigram at the second word boundary and atomically transforms 'your welcome ' into 'you're welcome ' (preserving initial capitalisation).",
          "Contextual grammar also repairs subject-verb agreement and plural determiners in real time: 'Raw eggs is best.' -> 'Raw eggs are best.', 'The dogs was barking.' -> 'The dogs were barking.', and 'I should of went home.' -> 'I should have gone home.' while guarding against false positives like 'One of the raw eggs is cracked.' or 'Physics is hard'.",
        ],
      },
      {
        id: "double-backspace-undo",
        heading: "Deliberate Double-Backspace Undo & Suggested Dictionary Words",
        paragraphs: [
          "A fast typist often presses a single Backspace subconsciously to delete a trailing space. Therefore, the first Backspace after an autocorrection is always a normal edit (deleting only the delimiter).",
          "Pressing Backspace a second consecutive time triggers TransactionLedger.consume_for_reversal(), restoring your exact original token ('received' -> 'recieved') and arming a one-shot suppression for that token instance.",
          "Crucially, reverting a word does NOT silently pollute your permanent dictionary. Instead, the reverted word is quietly noted in the 'Suggested Add to Dictionary Words' queue inside the Dictionary settings screen, so you can promote or dismiss it whenever convenient.",
        ],
      },
    ],
  },
  {
    slug: "customisation",
    title: "10-Screen Desktop Customisation UI & Local IPC Guide",
    shortTitle: "Desktop Customisation UI",
    category: "Desktop App",
    summary:
      "Walkthrough of all 10 screens in the PySide6-Essentials + Qt Quick/QML Settings application and the authenticated Local IPC protocol.",
    readingTime: "7 min read",
    sections: [
      {
        id: "out-of-process-ipc",
        heading: "Out-of-Process UI & Authenticated Local IPC",
        paragraphs: [
          "The Settings interface (autocorrect-settings) never opens SQLite for direct writes while the daemon is active, and never loads duplicate mmap lexicon files. Instead, it connects to LocalIPCServer inside autocorrect-daemon over a Windows Named Pipe (\\\\.\\pipe\\AutoCorrectIPC_<hash>) or a 0600 Unix Domain Socket (~/.autocorrect_desktop/ipc.sock).",
          "Every request is authenticated using a 256-bit random hex token stored in ~/.autocorrect_desktop/ipc.token (chmod 0600). Changes made in any screen update the daemon's zero-latency PreferenceMemoryOverlay between keystrokes.",
        ],
      },
      {
        id: "ten-screens-walkthrough",
        heading: "All 10 Desktop Customisation Screens",
        paragraphs: [
          "The left navigation rail provides instant access to all 10 customisation domains:",
        ],
        bullets: [
          "1. Overview: Live system hook status, Pause/Resume toggle, active English variant, mmap lexicon word count, and privacy-preserving LocalInsightsStore counters.",
          "2. General: Launch at OS login (Windows Run registry key / macOS LaunchAgents plist), global hotkeys (Ctrl+Shift+R rewrite, Ctrl+Alt+P pause), and One-Click Privacy Wipe.",
          "3. Dictionary: Search, add, and delete custom words; review Suggested Words captured from double-Backspace reverts; and bulk Import/Export via CSV or portable JSON.",
          "4. Languages: Switch between EN_GB (British), EN_US (American), EN_CA (Canadian), EN_AU (Australian), and UNIVERSAL English, and toggle the 6 Domain Vocabulary Packs.",
          "5. Corrections: Tune the Aggressiveness slider (0.50 to 1.50), toggle punctuation assistance, double-space period, and auto-capitalisation, and manage Rejected Pairs (Never Correct) and Preferred Variants (Always Prefer).",
          "6. Intelligence: Inspect Layer 2 Local AI hardware acceleration (DirectML / CoreML / AVX2) and configure Layer 3 BYOK Cloud AI keys, Local-Only Lockdown, and daily/monthly USD spend caps.",
          "7. Profiles: Configure per-application profiles (e.g. code.exe vs winword.exe) with custom aggressiveness, punctuation, and domain packs.",
          "8. Text Expansion: Create and edit snippets (;sig, @@email) with dynamic {{date}} and {{time}} macros.",
          "9. Updates: Independently manage Desktop App updates, Zstandard delta Language Intelligence updates (with one-click Rollback to Last Known Good), and Local AI Model downloads.",
          "10. About: Version, MIT licence, link to the source and a button to support the project with a donation.",
        ],
      },
      {
        id: "lgplv3-compliance",
        heading: "Qt 6 / PySide6-Essentials LGPLv3 Compliance Architecture",
        paragraphs: [
          "Typen depends exclusively on PySide6-Essentials (QtCore, QtGui, QtQml, QtQuick, QtQuickControls2, QtQuickLayouts, QtQuickDialogs, QtSvg) under the GNU Lesser General Public License v3 (LGPLv3).",
          "GPLv3-only modules (such as QtCharts, QtGraphs, QtQuick3D, and QtVirtualKeyboard) are strictly excluded and verified at both runtime and build time via src/autocorrect/ui/lgpl_compliance.py. Packaging uses one-folder (never one-file) mode so any Qt shared libraries (.dll / .dylib / .so) remain user-replaceable on disk. The current Windows build does not bundle Qt at all; it ships the native fallback Settings window.",
        ],
      },
    ],
  },
  {
    slug: "productivity",
    title: "Productivity: Snippets, Domain Packs & App Profiles",
    shortTitle: "Productivity",
    category: "Features",
    summary:
      "Expand text snippets with dynamic date/time macros, enable the 6 specialized domain vocabulary packs, and tailor typing behaviour per application.",
    readingTime: "5 min read",
    sections: [
      {
        id: "snippet-engine",
        heading: "Text Expansion Snippets & Dynamic Macros",
        paragraphs: [
          "SnippetEngine (src/autocorrect/productivity/snippet_engine.py) matches prefix-triggered or word-boundary shortcuts in O(1) time before standard lexical evaluation.",
          "Triggers can begin with prefix symbols such as ';' or '@' (e.g. ';sig', ';addr', '@@email') and support automatic UTC/local template interpolation via {{date}} and {{time}}.",
        ],
        codeBlock: {
          language: "json",
          title: "Example Snippet Definitions",
          code: `[
  {
    "trigger": ";sig",
    "expansion": "Best regards,\\nthe Typen team",
    "description": "Standard email sign-off"
  },
  {
    "trigger": ";stamp",
    "expansion": "Reviewed on {{date}} at {{time}} UTC",
    "description": "Audit timestamp macro"
  }
]`,
        },
      },
      {
        id: "domain-vocabulary-packs",
        heading: "6 Bundled Domain Vocabulary Packs",
        paragraphs: [
          "Domain packs overlay specialized terminology and domain-specific direct typo tables onto the active ResourceBundle without bloating baseline memory:",
        ],
        bullets: [
          "programming.pack.json: Kubernetes, PostgreSQL, idempotency, kubectl, GraphQL, PySide6.",
          "medicine.pack.json: arrhythmia, pharmacokinetics, ophthalmology, cholecystectomy.",
          "finance.pack.json: reconciliation, amortisation, EBITDA, fiduciary, derivatives.",
          "law.pack.json: jurisprudence, indemnification, affidavit, estoppel, habeas.",
          "business.pack.json: deliverables, stakeholder, procurement, omni-channel.",
          "academic.pack.json: epistemology, historiography, econometrics, longitudinal.",
        ],
      },
      {
        id: "app-profiles",
        heading: "Per-Application Typing Profiles",
        paragraphs: [
          "ApplicationProfileManager automatically adapts correction behaviour when you switch windows. For example, in Visual Studio Code (code.exe), punctuation assistance, double-space periods, and auto-capitalisation are disabled while the 'programming' domain pack is active. In Microsoft Word (winword.exe), full prose assistance and the 'business' + 'academic' packs are enabled.",
        ],
      },
    ],
  },
  {
    slug: "ai-intelligence",
    title: "AI: Layer 2 Local Models & Layer 3 BYOK Cloud AI",
    shortTitle: "Local & BYOK AI",
    category: "Features",
    summary:
      "Hardware-aware local ONNX/GGUF sentence analysis (400ms Pause Pill & Ctrl+Shift+R hotkey) and consent-gated BYOK Cloud AI with hard USD spending limits.",
    readingTime: "6 min read",
    sections: [
      {
        id: "three-layer-intelligence",
        heading: "The 3-Layer Intelligence Hierarchy",
        paragraphs: [
          "Typen strictly separates real-time keystroke correction from heavy neural inference so typing latency never degrades:",
        ],
        bullets: [
          "Layer 1 (Always-On, < 0.4ms): Deterministic mmap Lexicon + SymSpell + Trigram Context Model + Confusion Sets.",
          "Layer 2 (Local AI, On-Device): Hardware-aware quantized ONNX/GGUF sentence grammar engine triggered ONLY after a >= 400ms pause at a sentence boundary (non-focus-stealing Pause Pill) or via explicit Ctrl+Shift+R hotkey.",
          "Layer 3 (BYOK Cloud AI, Explicit Invocation Only): Direct HTTPS calls to OpenAI, Anthropic, Gemini, or custom OpenAI-compatible endpoints using your own API key stored in OS Keyring.",
        ],
      },
      {
        id: "layer2-hardware-selection",
        heading: "Layer 2 Hardware Detection & Idle Unloading",
        paragraphs: [
          "LocalModelManager.detect_hardware_profile() inspects CPU cores, system RAM, and platform accelerators (DirectML on Windows, CoreML on macOS, CPU-AVX2 on Linux) to recommend 'rewrite-gguf-q4-360m' (>= 16 GB RAM, 8+ cores) or 'grammar-onnx-int8-small' (>= 4 GB RAM).",
          "To preserve system memory, if no sentence evaluation occurs for 300 seconds (MODEL_IDLE_UNLOAD_SECONDS), the local model automatically unloads from RAM until needed again.",
        ],
      },
      {
        id: "layer3-byok-guardrails",
        heading: "Layer 3 BYOK Consent, OS Keyring & Spending Circuit Breakers",
        paragraphs: [
          "Cloud AI is never invoked during ordinary background typing. Even when explicitly invoked, BYOKProviderManager enforces four mandatory guardrails:",
        ],
        bullets: [
          "1. OS Keyring Storage: API keys are stored in Windows Credential Locker or macOS Keychain via keyring and scrubbed from all logs by SecretRedactingFilter.",
          "2. Explicit Transmission Disclosure & Consent: Requires user_consented=True or global consent opt-in before a single byte leaves the machine.",
          "3. Local-Only Lockdown Switch: A master circuit breaker in SpendingController that blocks all outbound AI network calls with LocalOnlyLockdownError.",
          "4. Hard Daily & Monthly USD Spend Caps: UsageTracker logs token counts (never prompt text) in ai_usage.sqlite3 and halts requests once daily ($2.00 default) or monthly ($15.00 default) limits are reached.",
        ],
      },
    ],
  },
  {
    slug: "security-privacy",
    title: "Security, Privacy & Cryptographic Update Architecture",
    shortTitle: "Security & Privacy",
    category: "Security",
    summary:
      "How Typen guarantees zero keystroke logging, automatic password field exclusion, Ed25519 manifest verification, and atomic Zstandard delta updates.",
    readingTime: "5 min read",
    sections: [
      {
        id: "zero-keylogging-guarantee",
        heading: "Zero Keystroke Logging & Ephemeral Memory Buffers",
        paragraphs: [
          "Typen is architected so that your typed documents, messages, and passwords can never be reconstructed from disk. SQLitePreferenceStore (preferences.sqlite3) stores only your explicit custom dictionary words, rejected correction pairs, preferred variants, and aggregate counters.",
          "The active word buffer holds at most the single word currently being typed, and the context ring buffer holds at most 5 integer word IDs—both flushed immediately on every window switch or mouse click.",
        ],
      },
      {
        id: "password-and-app-exclusions",
        heading: "Automatic Password Field & Security App Exclusions",
        paragraphs: [
          "Before evaluating any keystroke, the platform FocusInspector checks the active window and UI control:",
        ],
        bullets: [
          "Windows (Win32FocusInspector): Inspects Win32 window styles for ES_PASSWORD and excludes password managers (1password.exe, bitwarden.exe, keepassxc.exe, dashlane.exe).",
          "macOS (MacAXFocusInspector): Checks AXSubrole == 'AXSecureTextField' and Quartz IsSecureEventInputEnabled().",
          "Linux (X11FocusInspector / WaylandIBusEngineAdapter): Inspects window class exclusions and IBUS_INPUT_PURPOSE_PASSWORD.",
        ],
      },
      {
        id: "signed-delta-updates",
        heading: "Ed25519-Signed Zstandard Delta Updates & Atomic Rollback",
        paragraphs: [
          "Language Intelligence Library updates (.tar.zst and .patch.zst) are decoupled from application binary updates. LanguageResourceUpdater verifies the Ed25519 signature over the canonical release descriptor, checks the SHA-256 digest, blocks any archive containing path traversal ('..') or executable extensions (.exe, .dll, .so, .dylib, .py, .sh), verifies per-artifact hashes in manifest.json, and performs a pre-flight smoke load before atomically swapping active_version.json.",
          "If any check fails, or if you click 'Rollback to Last Known Good' in the Updates screen, ResourceManager immediately falls back to last_known_good_dir or the bundled baseline.",
        ],
      },
    ],
  },
  {
    slug: "open-source",
    title: "Open Source, Free for Everyone, Funded by Donations",
    shortTitle: "Open Source & Donations",
    category: "Project",
    summary:
      "Typen is MIT-licensed with a single edition and no trial, licence key or activation. How the project is funded, what changed from the earlier commercial betas, and how to contribute.",
    readingTime: "3 min read",
    sections: [
      {
        id: "one-edition",
        heading: "One Edition, Nothing Locked",
        paragraphs: [
          "Typen has exactly one build and it contains everything: the offline correction engine, every English variant and domain vocabulary pack, per-application profiles, text-expansion snippets, local insights, and the Local AI and BYOK Cloud AI screens. There is no trial, no licence certificate, no device lock and no account.",
          "Internally the daemon, the IPC server and the Settings controller still ask a single EntitlementManager whether a feature is allowed. In Typen that object always answers yes; it is kept only so a fork that wants gating has exactly one class to replace.",
        ],
      },
      {
        id: "funding",
        heading: "Donations Only",
        paragraphs: [
          "The project has no paid tier and never will. It is funded by donations through GitHub Sponsors, which pay for code-signing certificates, CI minutes for three platforms, hosting for the site and live demo, and the time that goes into lexicon curation and bug fixes. Donating changes nothing in the app.",
          "Earlier betas (1.2.0-beta.3 and before) shipped Standard and Pro licences, a 14-day trial and a payment integration. All of that code has been removed from the repository, not merely disabled. Anyone who bought a licence simply has the same Typen as everyone else now, with nothing to activate.",
        ],
      },
      {
        id: "github-organisation",
        heading: "Official GitHub Organisation & Focused Repositories",
        paragraphs: [
          "Typen lives under the official TypenApp GitHub organisation (github.com/TypenApp) across four focused repositories so that the desktop application, the global language library, optional AI resources and documentation each have a clear home, release history and issue tracker:",
        ],
        bullets: [
          "github.com/TypenApp/typen — Main desktop application, OS keyboard hooks, Settings UI, installers and public website.",
          "github.com/TypenApp/language-data — Global English lexicon pipeline, confusion sets, domain vocabulary packs and held-out quality corpus.",
          "github.com/TypenApp/model-resources — Optional Layer 2 on-device ONNX / GGUF grammar and rewrite model descriptors and Ed25519 signing tools.",
          "github.com/TypenApp/docs — Product guides, architecture specifications and CLI reference.",
        ],
      },
      {
        id: "licence-and-contributing",
        heading: "MIT Licence & Contributing",
        paragraphs: [
          "The source is published under the MIT licence: you may read, build, modify and redistribute it, including commercially, as long as the copyright notice is preserved. Bundled third-party components (SCOWL/ESDB word lists, Qt / PySide6-Essentials under LGPLv3, PyInstaller, Python libraries) keep their own licences, listed in LICENSE.",
          "The most useful contributions are correction reports: a misspelling the engine misses, or a correction it should not have made. Open a Correction Report in TypenApp/language-data or TypenApp/typen; accepted reports become held-out test cases in tests/test_engine_quality_heldout.py, whose thresholds are only ever raised. Platform testing, packaging fixes, documentation improvements and pull requests are equally welcome.",
        ],
        codeBlock: {
          language: "bash",
          title: "Build from source",
          code: `git clone https://github.com/TypenApp/typen.git && cd typen
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,ui]"
pytest
python -m autocorrect.launcher --headless-check`,
        },
      },
    ],
  },
  {
    slug: "cli-reference",
    title: "CLI Entry Points, Local Sandbox & Lexicon Pipeline Reference",
    shortTitle: "CLI & Pipeline Reference",
    category: "Developers",
    summary:
      "Command-line reference for autocorrect-daemon, autocorrect-settings, autocorrect-sandbox, and the ESDB/SCOWL binary lexicon compiler (autocorrect-pipeline).",
    readingTime: "5 min read",
    sections: [
      {
        id: "cli-commands",
        heading: "Installed CLI Entry Points (pyproject.toml)",
        paragraphs: [
          "The packaged AutoCorrectDesktop.exe accepts --settings, --headless-check, --no-tray, --data-dir, --version, --stop, --safe-mode and --resume. From a source checkout, AutoCorrect registers these command-line entry points in pyproject.toml:",
        ],
        codeBlock: {
          language: "bash",
          title: "CLI Commands Reference",
          code: `# 0. Same entry point as the packaged executable (service + tray, or --settings)
autocorrect-desktop --data-dir ~/.autocorrect_desktop
autocorrect-desktop --settings

# 0b. Service control: shut down cleanly, start without hooks, or leave safe mode
autocorrect-desktop --stop
autocorrect-desktop --safe-mode
autocorrect-desktop --resume

# 1. Start only the background hook daemon & Local IPC server (foreground, Ctrl+C to stop)
autocorrect-daemon --live --data-dir ~/.autocorrect_desktop

# 2. Launch the out-of-process 10-screen Settings UI (QML when PySide6 is installed)
autocorrect-settings --data-dir ~/.autocorrect_desktop

# 3. Run headless health check of all 10 UI controller screens & SQLite store
autocorrect-settings --headless-check

# 4. Launch the Controlled Local Browser Sandbox on http://127.0.0.1:8765
autocorrect-sandbox --host 127.0.0.1 --port 8765

# 5. Compile & cryptographically sign a language resource bundle
autocorrect-pipeline build --version 1.0.9 --out-dir ./build/en_1.0.9`,
        },
      },
      {
        id: "local-sandbox",
        heading: "Testing Safely with autocorrect-sandbox",
        paragraphs: [
          "During development or evaluation, autocorrect-sandbox starts a local HTTP server on 127.0.0.1:8765 connected to the real Python InputSessionManager and AutocorrectEngine with dry_run_hooks=True.",
          "Every keystroke in the browser textarea is serialized and evaluated against the mmap lexicon, displaying live telemetry for Active Word Buffer, Caret State, Sentence Capitaliser, Undo Transaction Slot, and evaluation latency in milliseconds.",
          "The same code powers the demo on this website. The site never simulates corrections: /api/demo is a Python serverless function that imports the engine and the en_base resources vendored from the same commit, and every visitor gets an isolated session (own word buffer, undo ledger and custom dictionary) keyed by an X-Session-Id header. Because a request may land on a fresh instance, each keystroke also carries the text before the caret and the visitor's dictionary words, from which a new instance primes an equivalent session without re-correcting anything. During local development `next dev` proxies /api/demo to autocorrect-sandbox on 127.0.0.1:8765 instead.",
        ],
      },
      {
        id: "binary-pipeline",
        heading: "ESDB / SCOWL Lexicon Ingestion & Binary Compilation Pipeline",
        paragraphs: [
          "The offline build pipeline (pipeline/ingest.py, pipeline/validate.py, pipeline/compile_binary.py, pipeline/sign_release.py) ingests over 166,000 attested English words and inflections from SCOWL/ESDB (size levels up to 70, including dialect-tagged headwords and irregular forms), ranks every word by wordfreq corpus frequency, strips known misspellings so corpus noise never validates a typo, adds a recognition-only technical vocabulary, compiles zero-copy binary artifacts (lexicon.bin, symspell_idx.bin, context_ngram.bin), and packages Zstandard full and delta archives signed with Ed25519.",
        ],
      },
    ],
  },
];

export function getDocBySlug(slug: string): DocArticle | undefined {
  return DOC_ARTICLES.find((doc) => doc.slug === slug);
}
