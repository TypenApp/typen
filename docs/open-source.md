# Open Source, Free for Everyone, Funded by Donations

> **Project** · 3 min read  
> Typen is MIT-licensed with a single edition and no trial, licence key or activation. How the project is funded, what changed from the earlier commercial betas, and how to contribute.

## Contents

1. [One Edition, Nothing Locked](#one-edition)
2. [Donations Only](#funding)
3. [Official GitHub Organisation & Focused Repositories](#github-organisation)
4. [MIT Licence & Contributing](#licence-and-contributing)

---

<a id="one-edition"></a>
## One Edition, Nothing Locked

Typen has exactly one build and it contains everything: the offline correction engine, every English variant and domain vocabulary pack, per-application profiles, text-expansion snippets, local insights, and the Local AI and BYOK Cloud AI screens. There is no trial, no licence certificate, no device lock and no account.

Internally the daemon, the IPC server and the Settings controller still ask a single EntitlementManager whether a feature is allowed. In Typen that object always answers yes; it is kept only so a fork that wants gating has exactly one class to replace.

<a id="funding"></a>
## Donations Only

The project has no paid tier and never will. It is funded by donations through GitHub Sponsors, which pay for code-signing certificates, CI minutes for three platforms, hosting for the site and live demo, and the time that goes into lexicon curation and bug fixes. Donating changes nothing in the app.

Earlier betas (1.2.0-beta.3 and before) shipped Standard and Pro licences, a 14-day trial and a payment integration. All of that code has been removed from the repository, not merely disabled. Anyone who bought a licence simply has the same Typen as everyone else now, with nothing to activate.

<a id="github-organisation"></a>
## Official GitHub Organisation & Focused Repositories

Typen lives under the official TypenApp GitHub organisation (github.com/TypenApp) across four focused repositories so that the desktop application, the global language library, optional AI resources and documentation each have a clear home, release history and issue tracker:

- github.com/TypenApp/typen — Main desktop application, OS keyboard hooks, Settings UI, installers and public website.
- github.com/TypenApp/language-data — Global English lexicon pipeline, confusion sets, domain vocabulary packs and held-out quality corpus.
- github.com/TypenApp/model-resources — Optional Layer 2 on-device ONNX / GGUF grammar and rewrite model descriptors and Ed25519 signing tools.
- github.com/TypenApp/docs — Product guides, architecture specifications and CLI reference.

<a id="licence-and-contributing"></a>
## MIT Licence & Contributing

The source is published under the MIT licence: you may read, build, modify and redistribute it, including commercially, as long as the copyright notice is preserved. Bundled third-party components (SCOWL/ESDB word lists, Qt / PySide6-Essentials under LGPLv3, PyInstaller, Python libraries) keep their own licences, listed in LICENSE.

The most useful contributions are correction reports: a misspelling the engine misses, or a correction it should not have made. Open a Correction Report in TypenApp/language-data or TypenApp/typen; accepted reports become held-out test cases in tests/test_engine_quality_heldout.py, whose thresholds are only ever raised. Platform testing, packaging fixes, documentation improvements and pull requests are equally welcome.

**Build from source**

```bash
git clone https://github.com/TypenApp/typen.git && cd typen
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,ui]"
pytest
python -m autocorrect.launcher --headless-check
```

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://typen.org/docs/open-source) · [TypenApp on GitHub](https://github.com/TypenApp)*
