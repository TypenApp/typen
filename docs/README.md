# Typen Documentation (`TypenApp/docs`)

Official documentation, architecture specifications, security guarantees, and CLI reference for **Typen** — the free, open-source, offline-first system-wide autocorrect and writing assistant for Windows, macOS, and Linux.

- **Website & Live Demo**: <https://autocorrect-desktop-six.vercel.app>
- **Web Docs**: <https://autocorrect-desktop-six.vercel.app/docs>
- **GitHub Organisation**: <https://github.com/TypenApp>

## Guides & Reference

| # | Category | Guide | Summary |
| --- | --- | --- | --- |
| `01` | Foundation | [Getting Started & Cross-Platform Installation](getting-started.md) | Install Typen on Windows (stable), macOS or Linux (public beta), understand the tray service and Settings window, grant the OS permissions each platform needs, and check that corrections are live. |
| `02` | Core Architecture | [Core Typing Engine, Suffix-Diff Replacement & Undo Mechanics](core-engine.md) | Deep dive into InputSessionManager, SuffixDiffPlanner, retroactive two-word homophone repair, sentence capitalisation, and deliberate double-Backspace undo. |
| `03` | Desktop App | [10-Screen Desktop Customisation UI & Local IPC Guide](customisation.md) | Walkthrough of all 10 screens in the PySide6-Essentials + Qt Quick/QML Settings application and the authenticated Local IPC protocol. |
| `04` | Features | [Productivity: Snippets, Domain Packs & App Profiles](productivity.md) | Expand text snippets with dynamic date/time macros, enable the 6 specialized domain vocabulary packs, and tailor typing behaviour per application. |
| `05` | Features | [AI: Layer 2 Local Models & Layer 3 BYOK Cloud AI](ai-intelligence.md) | Hardware-aware local ONNX/GGUF sentence analysis (400ms Pause Pill & Ctrl+Shift+R hotkey) and consent-gated BYOK Cloud AI with hard USD spending limits. |
| `06` | Security | [Security, Privacy & Cryptographic Update Architecture](security-privacy.md) | How Typen guarantees zero keystroke logging, automatic password field exclusion, Ed25519 manifest verification, and atomic Zstandard delta updates. |
| `07` | Project | [Open Source, Free for Everyone, Funded by Donations](open-source.md) | Typen is MIT-licensed with a single edition and no trial, licence key or activation. How the project is funded, what changed from the earlier commercial betas, and how to contribute. |
| `08` | Developers | [CLI Entry Points, Local Sandbox & Lexicon Pipeline Reference](cli-reference.md) | Command-line reference for autocorrect-daemon, autocorrect-settings, autocorrect-sandbox, and the ESDB/SCOWL binary lexicon compiler (autocorrect-pipeline). |

## Official `TypenApp` Repositories

| Repository | Role |
| --- | --- |
| [`TypenApp/typen`](https://github.com/TypenApp/typen) | Main desktop application, OS keyboard hooks, Settings UI, packaging and website |
| [`TypenApp/language-data`](https://github.com/TypenApp/language-data) | Global English lexicon pipeline, confusion sets, domain packs and held-out corpus |
| [`TypenApp/model-resources`](https://github.com/TypenApp/model-resources) | Optional Layer 2 local ONNX/GGUF grammar and rewrite model descriptors and signing |
| [`TypenApp/docs`](https://github.com/TypenApp/docs) | Product documentation, architecture guides and CLI reference |

## Contributing to the Docs

Pull requests fixing typos, clarifying OS setup steps, or expanding technical sections are always welcome! Each `.md` file in this repository corresponds 1-to-1 with an article on `/docs/<slug>`.

## Licence

MIT. See [`LICENSE`](LICENSE).
