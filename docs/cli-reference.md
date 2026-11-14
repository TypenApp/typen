# CLI Entry Points, Local Sandbox & Lexicon Pipeline Reference

> **Developers** · 5 min read  
> Command-line reference for typen, typen-daemon, typen-settings, typen-sandbox, and the ESDB/SCOWL binary lexicon compiler (typen-pipeline).

## Contents

1. [Installed CLI Entry Points (pyproject.toml)](#cli-commands)
2. [Testing Safely with typen-sandbox](#local-sandbox)
3. [ESDB / SCOWL Lexicon Ingestion & Binary Compilation Pipeline](#binary-pipeline)

---

<a id="cli-commands"></a>
## Installed CLI Entry Points (pyproject.toml)

The packaged typen.exe accepts --settings, --headless-check, --no-tray, --data-dir, --version, --stop, --safe-mode and --resume. From a source checkout, Typen registers these command-line entry points in pyproject.toml:

**CLI Commands Reference**

```bash
# 0. Same entry point as the packaged executable (service + tray, or --settings)
typen --data-dir ~/.autocorrect_desktop
typen --settings

# 0b. Service control: shut down cleanly, start without hooks, or leave safe mode
typen --stop
typen --safe-mode
typen --resume

# 1. Start only the background hook daemon & Local IPC server (foreground, Ctrl+C to stop)
typen-daemon --live --data-dir ~/.autocorrect_desktop

# 2. Launch the out-of-process Settings UI (QML when PySide6 is installed)
typen-settings --data-dir ~/.autocorrect_desktop

# 3. Run headless health check of all UI controller screens & SQLite store
typen-settings --headless-check

# 4. Launch the Controlled Local Browser Sandbox on http://127.0.0.1:8765
typen-sandbox --host 127.0.0.1 --port 8765

# 5. Compile & cryptographically sign a language resource bundle
typen-pipeline build --version 2.0.0 --out-dir ./build/en_2.0.0
```

<a id="local-sandbox"></a>
## Testing Safely with typen-sandbox

During development or evaluation, typen-sandbox starts a local HTTP server on 127.0.0.1:8765 connected to the real Python InputSessionManager and AutocorrectEngine with dry_run_hooks=True.

Every keystroke in the browser textarea is serialized and evaluated against the mmap lexicon, displaying live telemetry for Active Word Buffer, Caret State, Sentence Capitaliser, Undo Transaction Slot, and evaluation latency in milliseconds.

The same code powers the demo on this website. The site never simulates corrections: /api/demo is a Python serverless function that imports the engine and the en_base resources vendored from the same commit, and every visitor gets an isolated session (own word buffer, undo ledger and custom dictionary) keyed by an X-Session-Id header. Because a request may land on a fresh instance, each keystroke also carries the text before the caret and the visitor's dictionary words, from which a new instance primes an equivalent session without re-correcting anything. During local development `next dev` proxies /api/demo to typen-sandbox on 127.0.0.1:8765 instead.

<a id="binary-pipeline"></a>
## ESDB / SCOWL Lexicon Ingestion & Binary Compilation Pipeline

The offline build pipeline (pipeline/ingest.py, pipeline/validate.py, pipeline/compile_binary.py, pipeline/sign_release.py) ingests over 464,000 attested English words and inflections from SCOWL/ESDB (up to level 100, including dialect-tagged headwords and irregular forms) and the comprehensive English dictionary JSON, ranks every word by wordfreq corpus frequency, strips known misspellings so corpus noise never validates a typo, adds technical and modern vocabulary, compiles zero-copy binary artifacts (lexicon.bin, symspell_idx.bin, context_ngram.bin), and packages Zstandard full and delta archives signed with Ed25519.

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://typen.org/docs/cli-reference) · [TypenApp on GitHub](https://github.com/TypenApp)*
