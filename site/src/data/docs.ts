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
      "Install the Windows beta, understand the tray service and Settings window, and verify your 14-day full-featured Pro trial. macOS and Linux notes describe the planned setup.",
    readingTime: "4 min read",
    sections: [
      {
        id: "architecture-overview",
        heading: "How AutoCorrect Desktop Works",
        paragraphs: [
          "AutoCorrect Desktop is engineered around a strict two-process separation: a lightweight, always-on background service that hooks system-wide keyboard input with sub-millisecond word evaluation latency, and an on-demand 10-screen Settings window. Both run from the same executable (AutoCorrectDesktop.exe); the Settings window is started with the --settings flag. The Qt Quick/QML front end (PySide6-Essentials) is used when installed; the beta ships the lightweight native fallback window.",
          "When you close the Settings window, the UI process terminates completely (0% UI CPU and 0 MB GUI RAM), while the background daemon continues correcting typos across every native and web application on your machine.",
        ],
        bullets: [
          "100% Offline Core: Zero cloud dependency for everyday spelling, grammar, homophone, and punctuation corrections.",
          "158,988-Word Memory-Mapped Lexicon: Instant cold startup (< 150ms) via zero-copy mmap binary tables.",
          "14-Day Full Pro Trial: Automatically starts on first launch with no credit card required.",
        ],
      },
      {
        id: "windows-setup",
        heading: "Windows 10 & 11 Installation (Beta)",
        paragraphs: [
          "Download the installer (.exe) or portable (.zip) build from the Downloads page and compare its SHA-256 with the value shown there. The beta is not code-signed, so SmartScreen will show a warning on first run: choose More info, then Run anyway.",
          "The installer offers launch-at-login and creates Start menu shortcuts for the service and for Settings. After launch a tray icon appears; right-click it to pause, open Settings, or quit. The portable build is a one-folder PyInstaller bundle: unzip it anywhere and run AutoCorrectDesktop.exe.",
          "On Windows, AutoCorrect uses SetWindowsHookExW (WH_KEYBOARD_LL and WH_MOUSE_LL) paired with atomic SendInput (KEYEVENTF_UNICODE) packets tagged with AUTOCORRECT_EXTRA_INFO_TAG so synthetic keystrokes are never re-evaluated.",
        ],
        codeBlock: {
          language: "powershell",
          title: "Verify and launch from PowerShell",
          code: `# 1. Verify the download
Get-FileHash .\\AutoCorrect-Desktop-1.2.0-beta.1-win64-setup.exe -Algorithm SHA256

# 2. Start the background service (tray icon)
& "$env:LOCALAPPDATA\\Programs\\AutoCorrect Desktop\\AutoCorrectDesktop.exe"

# 3. Open the Settings window (connects to the service over a Named Pipe)
& "$env:LOCALAPPDATA\\Programs\\AutoCorrect Desktop\\AutoCorrectDesktop.exe" --settings

# Optional: print a one-line health check and exit
& "...\\AutoCorrectDesktop.exe" --headless-check`,
        },
      },
      {
        id: "macos-setup",
        heading: "macOS 12+ Accessibility Setup (planned)",
        paragraphs: [
          "A macOS build is not part of the current beta. When it ships, you will drag AutoCorrect.app to /Applications. Because AutoCorrect intercepts physical keystrokes via a Quartz Event Tap (CGEventTapCreate), macOS requires explicit Accessibility permission.",
          "Navigate to System Settings -> Privacy & Security -> Accessibility and toggle AutoCorrect.app ON. AutoCorrect automatically inspects AXSecureTextField and IsSecureEventInputEnabled on every focus change so password prompts and Secure Input terminals are never read.",
        ],
      },
      {
        id: "linux-setup",
        heading: "Linux (X11 & Wayland IBus) Setup (planned)",
        paragraphs: [
          "A Linux build is not part of the current beta. On X11 sessions, X11FocusInspector and X11TextInjector operate directly; on Wayland sessions, WaylandIBusEngineAdapter integrates with IBus and respects IBUS_INPUT_PURPOSE_PASSWORD automatically.",
        ],
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
          "Standard-tier contextual grammar also repairs subject-verb agreement and plural determiners in real time: 'Raw eggs is best.' -> 'Raw eggs are best.', 'The dogs was barking.' -> 'The dogs were barking.', and 'I should of went home.' -> 'I should have gone home.' while guarding against false positives like 'One of the raw eggs is cracked.' or 'Physics is hard'.",
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
          "1. Overview: Live system hook status, Pause/Resume toggle, active English variant, mmap lexicon word count, edition badge, and privacy-preserving LocalInsightsStore counters.",
          "2. General: Launch at OS login (Windows Run registry key / macOS LaunchAgents plist), global hotkeys (Ctrl+Shift+R rewrite, Ctrl+Alt+P pause), and One-Click Privacy Wipe.",
          "3. Dictionary: Search, add, and delete custom words; review Suggested Words captured from double-Backspace reverts; and bulk Import/Export via CSV or portable JSON.",
          "4. Languages: Switch between EN_GB (British), EN_US (American), EN_CA (Canadian), EN_AU (Australian), and UNIVERSAL English, and toggle the 6 Pro Domain Vocabulary Packs.",
          "5. Corrections: Tune the Aggressiveness slider (0.50 to 1.50), toggle punctuation assistance, double-space period, and auto-capitalisation, and manage Rejected Pairs (Never Correct) and Preferred Variants (Always Prefer).",
          "6. Pro Intelligence: Inspect Layer 2 Local AI hardware acceleration (DirectML / CoreML / AVX2) and configure Layer 3 BYOK Cloud AI keys, Local-Only Lockdown, and daily/monthly USD spend caps.",
          "7. Profiles: Configure per-application profiles (e.g. code.exe vs winword.exe) with custom aggressiveness, punctuation, and domain packs.",
          "8. Text Expansion: Create and edit Pro snippets (;sig, @@email) with dynamic {{date}} and {{time}} macros.",
          "9. Updates: Independently manage Desktop App updates, Zstandard delta Language Intelligence updates (with one-click Rollback to Last Known Good), and Local AI Model downloads.",
          "10. Licence: View offline Ed25519 certificate status, Device Lock SHA-256 fingerprint, 12-month update entitlement window, seat deactivation, and BACHS checkout/renewal quotes.",
        ],
      },
      {
        id: "lgplv3-compliance",
        heading: "Qt 6 / PySide6-Essentials LGPLv3 Compliance Architecture",
        paragraphs: [
          "AutoCorrect Desktop depends exclusively on PySide6-Essentials (QtCore, QtGui, QtQml, QtQuick, QtQuickControls2, QtQuickLayouts, QtQuickDialogs, QtSvg) under the GNU Lesser General Public License v3 (LGPLv3).",
          "GPLv3-only modules (such as QtCharts, QtGraphs, QtQuick3D, and QtVirtualKeyboard) are strictly excluded and verified at both runtime and build time via src/autocorrect/ui/lgpl_compliance.py. Packaging uses one-folder (never one-file) mode so any Qt shared libraries (.dll / .dylib / .so) remain user-replaceable on disk. The current Windows beta does not bundle Qt at all; it ships the native fallback Settings window.",
        ],
      },
    ],
  },
  {
    slug: "pro-productivity",
    title: "Pro Productivity: Snippets, Domain Packs & App Profiles",
    shortTitle: "Pro Productivity",
    category: "Pro Features",
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
    "expansion": "Best regards,\\nAutoCorrect Engineering Team",
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
    title: "Pro AI: Layer 2 Local Models & Layer 3 BYOK Cloud AI",
    shortTitle: "Local & BYOK AI",
    category: "Pro Features",
    summary:
      "Hardware-aware local ONNX/GGUF sentence analysis (400ms Pause Pill & Ctrl+Shift+R hotkey) and consent-gated BYOK Cloud AI with hard USD spending limits.",
    readingTime: "6 min read",
    sections: [
      {
        id: "three-layer-intelligence",
        heading: "The 3-Layer Intelligence Hierarchy",
        paragraphs: [
          "AutoCorrect strictly separates real-time keystroke correction from heavy neural inference so typing latency never degrades:",
        ],
        bullets: [
          "Layer 1 (Always-On, < 0.4ms): Deterministic mmap Lexicon + SymSpell + Trigram Context Model + Confusion Sets.",
          "Layer 2 (Pro Local AI, On-Device): Hardware-aware quantized ONNX/GGUF sentence grammar engine triggered ONLY after a >= 400ms pause at a sentence boundary (non-focus-stealing Pause Pill) or via explicit Ctrl+Shift+R hotkey.",
          "Layer 3 (Pro BYOK Cloud AI, Explicit Invocation Only): Direct HTTPS calls to OpenAI, Anthropic, Gemini, or custom OpenAI-compatible endpoints using your own API key stored in OS Keyring.",
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
      "How AutoCorrect guarantees zero keystroke logging, automatic password field exclusion, Ed25519 manifest verification, and atomic Zstandard delta updates.",
    readingTime: "5 min read",
    sections: [
      {
        id: "zero-keylogging-guarantee",
        heading: "Zero Keystroke Logging & Ephemeral Memory Buffers",
        paragraphs: [
          "AutoCorrect is architected so that your typed documents, messages, and passwords can never be reconstructed from disk. SQLitePreferenceStore (preferences.sqlite3) stores only your explicit custom dictionary words, rejected correction pairs, preferred variants, and aggregate counters.",
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
    slug: "licensing",
    title: "Perpetual Licensing, Device Lock & BACHS Payment Architecture",
    shortTitle: "Licensing & Payments",
    category: "Commercial",
    summary:
      "Understand the 4 commercial entitlements, offline Ed25519 licence certificates, SHA-256 device locking, and the 9-step BACHS checkout lifecycle.",
    readingTime: "5 min read",
    sections: [
      {
        id: "perpetual-plus-updates",
        heading: "Perpetual Usage + 12-Month Update Entitlement",
        paragraphs: [
          "AutoCorrect rejects mandatory SaaS subscriptions for desktop utilities. Every Standard ($14.99) or Pro ($34.99) purchase grants four distinct entitlements encoded in a locally stored, Ed25519-signed certificate (entitlement.lic):",
        ],
        bullets: [
          "1. Product Edition Entitlement: STANDARD or PRO.",
          "2. Platform Entitlement: WINDOWS (STANDARD-WIN / PRO-WIN) or MACOS (STANDARD-MAC / PRO-MAC).",
          "3. Perpetual Usage Right: Your installed application build and language resources continue working 100% offline forever—even years after your update window ends.",
          "4. 12-Month Update Window (updates_expire_at): Full access to new app releases, emerging vocabulary bundles, and AI model updates for 1 year, with optional 30% discounted renewals and critical security patches always permitted.",
        ],
      },
      {
        id: "device-locking",
        heading: "Privacy-Preserving Hardware Device Lock (SHA-256)",
        paragraphs: [
          "To bind a licence seat to your machine without collecting hardware serial numbers in plaintext, activation_manager.py reads the OS machine identifier (Windows HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid, macOS IOPlatformUUID, or Linux /etc/machine-id) and computes a salted SHA-256 digest (compute_local_device_id_hash).",
          "You can deactivate your current device seat at any time from the Licence screen (LicenceService.deactivate_current_device) to transfer your licence to a new computer.",
        ],
      },
      {
        id: "bachs-checkout-flow",
        heading: "9-Step BACHS Payment & Webhook Verification Lifecycle",
        paragraphs: [
          "Purchases, 30% update renewals, and Standard-to-Pro cross-grades are processed through BACHS (BachsPaymentAdapter in src/autocorrect/payments/bachs_adapter.py):",
        ],
        bullets: [
          "Steps 1–3: CheckoutManager calculates the exact server-side quote (applying 30% renewal or cross-grade credit via product_cart[].pricing override) and creates an idempotent BACHS checkout session.",
          "Steps 4–6: Customer completes hosted checkout in USD, NGN, GHS, or KES; BACHS delivers a webhook verified via webhooks.construct_event (X-Bachs-Signature-V2) over raw request bytes.",
          "Steps 7–9: PurchaseVerificationService validates amount, currency, and reference, signs the Ed25519 SignedLicenceCertificate, and the desktop app persists entitlement.lic for 100% offline verification.",
        ],
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
          "The packaged AutoCorrectDesktop.exe accepts --settings, --headless-check, --no-tray, --data-dir and --version. From a source checkout, AutoCorrect registers these command-line entry points in pyproject.toml:",
        ],
        codeBlock: {
          language: "bash",
          title: "CLI Commands Reference",
          code: `# 0. Same entry point as the packaged executable (service + tray, or --settings)
autocorrect-desktop --data-dir ~/.autocorrect_desktop
autocorrect-desktop --settings

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
          "Every keystroke in the browser textarea is serialized and evaluated against the mmap lexicon, displaying live telemetry for Active Word Buffer, Caret State, Sentence Capitaliser, Undo Transaction Slot, evaluation latency in milliseconds, and Device Lock SHA-256.",
          "The same server powers the demo on this website. The site never simulates corrections: its /api/engine route proxies each keystroke to autocorrect-sandbox (AUTOCORRECT_ENGINE_URL, default http://127.0.0.1:8765), and every visitor gets an isolated session (own word buffer, undo ledger and custom dictionary) keyed by an X-Session-Id header. If the engine is unreachable the demo says so and shows recorded engine output instead.",
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
