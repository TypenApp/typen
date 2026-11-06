# Contributing to Typen

Thank you for contributing to **Typen**! Typen is a free, open-source (MIT), offline-first system-wide autocorrect and writing assistant maintained under the [`TypenApp`](https://github.com/TypenApp) GitHub organisation.

---

## Where to Contribute (`github.com/TypenApp`)

Typen is split into focused repositories so each concern has a clean history, CI pipeline, and release cycle:

| Repository | What belongs here |
| --- | --- |
| [`TypenApp/typen`](https://github.com/TypenApp/typen) | Main desktop application, OS keyboard hooks (Win32, Quartz, X11, Wayland/IBus), Local IPC, Settings UI, installers, and public website |
| [`TypenApp/language-data`](https://github.com/TypenApp/language-data) | Global English lexicon pipeline (SCOWL/ESDB ingestion), confusion sets, direct typo rules, 6 domain vocabulary packs, and held-out quality benchmarks |
| [`TypenApp/model-resources`](https://github.com/TypenApp/model-resources) | Optional Layer 2 on-device AI model descriptors (`grammar-onnx-int8-small`, `rewrite-gguf-q4-360m`), hardware profiles, and Ed25519 manifest signing |
| [`TypenApp/docs`](https://github.com/TypenApp/docs) | User guides, architecture documentation, security & privacy specs, and CLI reference |

---

## Reporting Correction Issues (Missed Typos or False Positives)

The single most impactful contribution to Typen is reporting:
1. **A missed typo** — a word or phrase you mistyped that Typen did not fix.
2. **A false positive** — a valid word, technical term, or phrase that Typen wrongly changed.

Open a **Correction Report** issue in [`TypenApp/language-data`](https://github.com/TypenApp/language-data/issues) or [`TypenApp/typen`](https://github.com/TypenApp/typen/issues) with:
- The exact input text (including 1–2 surrounding words if context matters).
- What Typen produced vs. what you expected.
- Your active English variant (`EN_GB`, `EN_US`, `EN_CA`, `EN_AU`, or `UNIVERSAL`) and any enabled domain packs.

Every accepted correction report is added to the held-out regression suite (`tests/test_engine_quality_heldout.py`), whose accuracy thresholds are only ever raised.

---

## Local Development Setup

### Prerequisites
- Python **3.11+** (3.12 recommended)
- Node.js **20+** (only if working on `site/`)

### Clone and Install

```bash
git clone https://github.com/TypenApp/typen.git
cd typen
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -e ".[dev,ui]"
```

On macOS or Linux, include platform extras:
```bash
pip install -e ".[dev,ui,macos]"   # macOS
pip install -e ".[dev,ui,linux]"   # Linux
```

### Running Tests and Quality Gates

Before submitting a pull request, run the full test and lint suite:

```bash
# 1. Run unit, integration, and held-out corpus quality tests
pytest

# 2. Run Ruff linter
ruff check src pipeline tests

# 3. Run headless end-to-end daemon & resource smoke check
python -m autocorrect.launcher --headless-check
```

### Testing in the Local Browser Sandbox

To test typing behaviour safely without installing a system-wide OS keyboard hook:

```bash
autocorrect-sandbox --host 127.0.0.1 --port 8765
```

---

## Architectural Guardrails for Pull Requests

1. **Zero Network Calls in Layer 1**: The core typing engine (`src/autocorrect/core`, `src/autocorrect/intelligence`, `src/autocorrect/input`) must remain 100% offline and sub-millisecond.
2. **Privacy by Construction**: Never log raw keystrokes, word buffers, or clipboard/document content to disk or stdout.
3. **Held-Out Corpus Separation**: Never tune lexicon rules by copying test cases from `tests/test_engine_quality_heldout.py` into `pipeline/ingest.py`. Held-out tests measure real-world generalisation.
4. **LGPLv3 Qt Compliance**: Only `PySide6-Essentials` modules are permitted (`src/autocorrect/ui/lgpl_compliance.py`). Never import GPLv3-only Qt modules (`QtCharts`, `QtGraphs`, `QtQuick3D`, `QtVirtualKeyboard`).
5. **100% Free & Open Source**: Do not introduce feature gates, paid tiers, or telemetry.

---

## Pull Request Process

1. Fork the target repository under [`TypenApp`](https://github.com/TypenApp) and create a topic branch from `main` (or `master`).
2. Add or update tests covering your change.
3. Ensure `pytest` and `ruff check` pass locally.
4. Open a Pull Request describing the motivation, architectural impact, and verification steps.

By contributing to any `TypenApp` repository, you agree that your contributions will be licensed under the [MIT License](LICENSE).
