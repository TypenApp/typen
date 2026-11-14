# CLI Entry Points, Local Sandbox & Lexicon Pipeline Reference

> **Developers** · 5 min read  
> Command-line reference for autocorrect-daemon, autocorrect-settings, autocorrect-sandbox, and the ESDB/SCOWL binary lexicon compiler (autocorrect-pipeline).

## Contents

1. [Installed CLI Entry Points (pyproject.toml)](#cli-commands)
2. [Testing Safely with autocorrect-sandbox](#local-sandbox)
3. [ESDB / SCOWL Lexicon Ingestion & Binary Compilation Pipeline](#binary-pipeline)

---

<a id="cli-commands"></a>
## Installed CLI Entry Points (pyproject.toml)

The packaged typen.exe accepts --settings, --headless-check, --no-tray, --data-dir, --version, --stop, --safe-mode and --resume. From a source checkout, AutoCorrect registers these command-line entry points in pyproject.toml:

**CLI Commands Reference**

```bash
# 0. Same entry point as the packaged executable (service + tray, or --settings)
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
autocorrect-pipeline build --version 1.0.9 --out-dir ./build/en_1.0.9
```

<a id="local-sandbox"></a>
## Testing Safely with autocorrect-sandbox

During development or evaluation, autocorrect-sandbox starts a local HTTP server on 127.0.0.1:8765 connected to the real Python InputSessionManager and AutocorrectEngine with dry_run_hooks=True.

Every keystroke in the browser textarea is serialized and evaluated against the mmap lexicon, displaying live telemetry for Active Word Buffer, Caret State, Sentence Capitaliser, Undo Transaction Slot, and evaluation latency in milliseconds.

The same code powers the demo on this website. The site never simulates corrections: /api/demo is a Python serverless function that imports the engine and the en_base resources vendored from the same commit, and every visitor gets an isolated session (own word buffer, undo ledger and custom dictionary) keyed by an X-Session-Id header. Because a request may land on a fresh instance, each keystroke also carries the text before the caret and the visitor's dictionary words, from which a new instance primes an equivalent session without re-correcting anything. During local development `next dev` proxies /api/demo to autocorrect-sandbox on 127.0.0.1:8765 instead.

<a id="binary-pipeline"></a>
## ESDB / SCOWL Lexicon Ingestion & Binary Compilation Pipeline

The offline build pipeline (pipeline/ingest.py, pipeline/validate.py, pipeline/compile_binary.py, pipeline/sign_release.py) ingests over 166,000 attested English words and inflections from SCOWL/ESDB (size levels up to 70, including dialect-tagged headwords and irregular forms), ranks every word by wordfreq corpus frequency, strips known misspellings so corpus noise never validates a typo, adds a recognition-only technical vocabulary, compiles zero-copy binary artifacts (lexicon.bin, symspell_idx.bin, context_ngram.bin), and packages Zstandard full and delta archives signed with Ed25519.

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://typen.org/docs/cli-reference) · [TypenApp on GitHub](https://github.com/TypenApp)*
