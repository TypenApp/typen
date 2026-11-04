"""
Assemble clean, standalone repository trees for the `TypenApp` GitHub organisation:

1. `TypenApp/.github`          -> `dist/org-repos/dot-github`
2. `TypenApp/typen`            -> `dist/org-repos/typen`
3. `TypenApp/language-data`    -> `dist/org-repos/language-data`
4. `TypenApp/model-resources`  -> `dist/org-repos/model-resources`
5. `TypenApp/docs`             -> `dist/org-repos/docs`

Usage:
    python scripts/build_org_repos.py [--out-dir dist/org-repos]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from pipeline.sync_docs import sync_docs  # noqa: E402
from scripts.configure_github_sponsors import enable_repo_sponsorships  # noqa: E402

from autocorrect.licensing.root_key import ROOT_PUBLIC_KEY_HEX  # noqa: E402

DEFAULT_OUT_DIR = ROOT / "dist" / "org-repos"

ORG_NAME = "TypenApp"
ORG_URL = f"https://github.com/{ORG_NAME}"

REPO_SPECS: list[dict[str, object]] = [
    {
        "dir_name": "dot-github",
        "repo_name": ".github",
        "full_name": f"{ORG_NAME}/.github",
        "description": "Organisation profile, community health files, and issue/PR templates for TypenApp.",
        "homepage": "https://autocorrect-desktop.vercel.app",
        "topics": ["typen", "autocorrect", "open-source"],
    },
    {
        "dir_name": "typen",
        "repo_name": "typen",
        "full_name": f"{ORG_NAME}/typen",
        "description": "Free, open-source, offline-first system-wide autocorrect for Windows, macOS and Linux.",
        "homepage": "https://autocorrect-desktop.vercel.app",
        "topics": ["typen", "autocorrect", "desktop", "offline-first", "windows", "macos", "linux", "python"],
    },
    {
        "dir_name": "language-data",
        "repo_name": "language-data",
        "full_name": f"{ORG_NAME}/language-data",
        "description": "Global English lexicon pipeline, confusion sets, domain packs and held-out quality corpus for Typen.",
        "homepage": "https://autocorrect-desktop.vercel.app/docs/core-engine",
        "topics": ["typen", "lexicon", "nlp", "spellcheck", "scowl", "symspell"],
    },
    {
        "dir_name": "model-resources",
        "repo_name": "model-resources",
        "full_name": f"{ORG_NAME}/model-resources",
        "description": "Optional Layer 2 on-device ONNX/GGUF grammar and rewrite model descriptors and Ed25519 signing tools for Typen.",
        "homepage": "https://autocorrect-desktop.vercel.app/docs/ai-intelligence",
        "topics": ["typen", "onnx", "gguf", "local-ai", "ed25519"],
    },
    {
        "dir_name": "docs",
        "repo_name": "docs",
        "full_name": f"{ORG_NAME}/docs",
        "description": "Official documentation, architecture specifications, security guarantees and CLI reference for Typen.",
        "homepage": "https://autocorrect-desktop.vercel.app/docs",
        "topics": ["typen", "documentation", "autocorrect"],
    },
]


def _rmtree(path: Path) -> None:
    def _handle_readonly(func: object, target: str, _exc: BaseException) -> None:
        os.chmod(target, stat.S_IWRITE)
        if callable(func):
            func(target)

    if path.exists():
        shutil.rmtree(path, onexc=_handle_readonly)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree_filtered(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        "*.pyo",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        ".next",
        "_vendor",
        "*.egg-info",
        ".venv",
        "dist",
        "build",
    )
    if dst.exists():
        _rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def _copy_common_community_files(target_root: Path) -> None:
    for fname in ("LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md"):
        src = ROOT / fname
        if src.exists():
            _copy_file(src, target_root / fname)


def build_dot_github_repo(out_dir: Path) -> Path:
    """Assemble `TypenApp/.github` organisation profile and default governance files."""
    repo_dir = out_dir / "dot-github"
    if repo_dir.exists():
        _rmtree(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    _copy_common_community_files(repo_dir)
    _copy_file(ROOT / ".github" / "FUNDING.yml", repo_dir / "FUNDING.yml")
    _copy_file(ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md", repo_dir / "PULL_REQUEST_TEMPLATE.md")
    _copy_tree_filtered(ROOT / ".github" / "ISSUE_TEMPLATE", repo_dir / "ISSUE_TEMPLATE")

    support_md = """# Support & Community

Need help installing, configuring, or building **Typen**?

## Documentation

Start with the official guides on our website or in [`TypenApp/docs`](https://github.com/TypenApp/docs):

1. [Getting Started & Cross-Platform Installation](https://autocorrect-desktop.vercel.app/docs/getting-started)
2. [Core Typing Engine & Double-Backspace Undo](https://autocorrect-desktop.vercel.app/docs/core-engine)
3. [10-Screen Desktop Customisation UI & Local IPC](https://autocorrect-desktop.vercel.app/docs/customisation)
4. [Productivity: Snippets, Domain Packs & App Profiles](https://autocorrect-desktop.vercel.app/docs/productivity)
5. [AI: Layer 2 Local Models & Layer 3 BYOK Cloud AI](https://autocorrect-desktop.vercel.app/docs/ai-intelligence)
6. [Security, Privacy & Cryptographic Update Architecture](https://autocorrect-desktop.vercel.app/docs/security-privacy)
7. [CLI & Lexicon Pipeline Reference](https://autocorrect-desktop.vercel.app/docs/cli-reference)

## Where to Open an Issue

- **Desktop App, OS Keyboard Hooks, Settings UI, Installers**: [`TypenApp/typen/issues`](https://github.com/TypenApp/typen/issues)
- **Missed Typos, False Positives, Domain Vocabulary Packs**: [`TypenApp/language-data/issues`](https://github.com/TypenApp/language-data/issues)
- **Local AI Model Descriptors & Hardware Acceleration**: [`TypenApp/model-resources/issues`](https://github.com/TypenApp/model-resources/issues)
- **Documentation & Guides**: [`TypenApp/docs/issues`](https://github.com/TypenApp/docs/issues)
- **Questions, Ideas & Show-and-Tell**: [`TypenApp` Discussions](https://github.com/orgs/TypenApp/discussions)
"""
    (repo_dir / "SUPPORT.md").write_text(support_md, encoding="utf-8")

    profile_readme = """# Typen

**Autocorrect for every app on your desktop — 100% offline, sub-millisecond, free and open source.**

Typen is one small background service that fixes typos, homophones, punctuation, and capitalisation as you type across every application on Windows, macOS, and Linux. Nothing you type ever leaves your machine.

- **Website & Live Engine Demo**: <https://autocorrect-desktop.vercel.app>
- **Download Installers**: <https://github.com/TypenApp/typen/releases>
- **Documentation**: <https://autocorrect-desktop.vercel.app/docs>
- **Sponsor Typen**: <https://github.com/sponsors/TypenApp>

---

## Repositories in `TypenApp`

| Repository | Description |
| --- | --- |
| [**`TypenApp/typen`**](https://github.com/TypenApp/typen) | Main desktop application, OS keyboard hooks (Win32, Quartz, X11, Wayland/IBus), authenticated Local IPC, 10-screen Settings UI, cross-platform installers, and public website. |
| [**`TypenApp/language-data`**](https://github.com/TypenApp/language-data) | Global English lexicon build pipeline (166,475 words from SCOWL/ESDB), SymSpell delete-distance index, trigram context model, confusion sets, 6 domain vocabulary packs, and held-out quality benchmarks. |
| [**`TypenApp/model-resources`**](https://github.com/TypenApp/model-resources) | Optional Layer 2 on-device AI model descriptors (`grammar-onnx-int8-small`, `rewrite-gguf-q4-360m`), hardware capability profiles, and Ed25519 manifest signing tools. |
| [**`TypenApp/docs`**](https://github.com/TypenApp/docs) | Product documentation, core engine architecture specs, security & privacy guarantees, and CLI reference. |

---

## Why Typen?

- **Every application**: A low-level OS keyboard hook sees keystrokes before the application does and injects flicker-free suffix-diff replacements.
- **Nothing leaves your computer**: A 166k-word lexicon is memory-mapped from disk (`mmap`) and queried in under a millisecond. Zero keystroke logging, automatic password-field exclusion, and zero telemetry.
- **Reversible by design**: Every correction is a transaction. Press `Backspace` twice immediately after a correction to restore your original word and queue it for your personal dictionary.
- **Free forever**: MIT-licensed with a single edition, no trial, no licence key, and no paid tier.
"""
    profile_dir = repo_dir / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "README.md").write_text(profile_readme, encoding="utf-8")
    (repo_dir / "README.md").write_text(profile_readme, encoding="utf-8")
    return repo_dir


def build_typen_repo(out_dir: Path) -> Path:
    """Assemble `TypenApp/typen` (main application + website)."""
    repo_dir = out_dir / "typen"
    if repo_dir.exists():
        _rmtree(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    _copy_common_community_files(repo_dir)
    for top_file in ("README.md", "pyproject.toml", ".gitignore", ".env.example"):
        src = ROOT / top_file
        if src.exists():
            _copy_file(src, repo_dir / top_file)

    for folder in (
        ".github",
        "src",
        "pipeline",
        "packaging",
        "resources",
        "tests",
        "site",
        "docs",
        "scripts",
    ):
        src_folder = ROOT / folder
        if src_folder.exists():
            _copy_tree_filtered(src_folder, repo_dir / folder)

    return repo_dir


def build_language_data_repo(out_dir: Path) -> Path:
    """Assemble `TypenApp/language-data` (global lexicon pipeline, domain packs, and quality gates)."""
    repo_dir = out_dir / "language-data"
    if repo_dir.exists():
        _rmtree(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    _copy_common_community_files(repo_dir)
    _copy_file(ROOT / ".gitignore", repo_dir / ".gitignore")
    _copy_tree_filtered(ROOT / "pipeline", repo_dir / "pipeline")
    _copy_tree_filtered(ROOT / "resources", repo_dir / "resources")

    # Include the core & intelligence packages so `autocorrect-pipeline` and held-out
    # quality tests run standalone inside `TypenApp/language-data`.
    for subpkg in ("__init__.py", "version.py"):
        _copy_file(ROOT / "src" / "autocorrect" / subpkg, repo_dir / "src" / "autocorrect" / subpkg)
    for pkg_name in ("core", "intelligence", "input", "licensing"):
        _copy_tree_filtered(
            ROOT / "src" / "autocorrect" / pkg_name,
            repo_dir / "src" / "autocorrect" / pkg_name,
        )

    for test_name in ("conftest.py", "test_engine_quality_heldout.py"):
        src_test = ROOT / "tests" / test_name
        if src_test.exists():
            _copy_file(src_test, repo_dir / "tests" / test_name)

    _copy_file(ROOT / ".github" / "FUNDING.yml", repo_dir / ".github" / "FUNDING.yml")
    _copy_file(
        ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md", repo_dir / ".github" / "PULL_REQUEST_TEMPLATE.md"
    )
    _copy_file(
        ROOT / ".github" / "ISSUE_TEMPLATE" / "correction_report.yml",
        repo_dir / ".github" / "ISSUE_TEMPLATE" / "correction_report.yml",
    )

    pyproject = """[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "typen-language-data"
version = "1.0.9"
description = "Global English lexicon pipeline, confusion sets, domain packs and held-out quality corpus for Typen"
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}
authors = [{name = "Omnii"}]
dependencies = [
    "cryptography>=42.0.0",
    "zstandard>=0.22.0",
    "rapidfuzz>=3.6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.5.0",
    "wordfreq>=3.1.0",
]

[project.urls]
Homepage = "https://autocorrect-desktop.vercel.app"
Repository = "https://github.com/TypenApp/language-data"
MainApp = "https://github.com/TypenApp/typen"
Issues = "https://github.com/TypenApp/language-data/issues"

[project.scripts]
autocorrect-pipeline = "pipeline.cli:main"

[tool.setuptools.packages.find]
where = ["src", "."]
include = ["autocorrect*", "pipeline*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "."]
addopts = "-q"

[tool.ruff]
line-length = 110
target-version = "py311"
src = ["src", "pipeline", "tests"]
extend-exclude = ["resources", "pipeline/data"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "S"]
ignore = [
    "E501",
    "UP017",
    "UP035",
    "UP042",
    "S101",
    "S105", "S106",
    "S110", "S112",
    "S603", "S607",
    "B008",
    "B905",
]
"""
    (repo_dir / "pyproject.toml").write_text(pyproject, encoding="utf-8")

    readme = """# Typen Global Language Library (`TypenApp/language-data`)

This repository contains the lexicon ingestion pipeline, binary compiler, homophone confusion sets, 6 specialized domain vocabulary packs, and held-out quality test suites that power [**Typen**](https://github.com/TypenApp/typen).

- **Main Application**: [`TypenApp/typen`](https://github.com/TypenApp/typen)
- **Model Resources**: [`TypenApp/model-resources`](https://github.com/TypenApp/model-resources)
- **Documentation**: [`TypenApp/docs`](https://github.com/TypenApp/docs)

---

## What Lives Here

| Path | Description |
| --- | --- |
| `pipeline/ingest.py` | Master English dataset builder combining SCOWL/ESDB headwords, dialect tags (`EN_GB`, `EN_US`, `EN_CA`, `EN_AU`), wordfreq tiers, and direct typo maps |
| `pipeline/external_sources.py` | Loader for `pipeline/data/external/scowl-pre.txt` (166,475 attested English words and inflections) |
| `pipeline/validate.py` | Dataset sanitisation and invariant checks (ensures known misspellings never enter the valid lexicon) |
| `pipeline/compile_binary.py` | Zero-copy `mmap` binary compiler (`lexicon.bin`, `lexicon_meta.bin`, `symspell_idx.bin`, `direct_typos.bin`, `context_ngram.bin`, `abbreviations.bin`) |
| `pipeline/regression_runner.py` | Golden corpus regression runner enforcing minimum typo accuracy, confusion accuracy, and near-zero false-positive rate |
| `pipeline/sign_release.py` | Ed25519 manifest signer and Zstandard `.tar.zst` full / `.patch.zst` delta archive builder |
| `resources/en_base/` | Compiled binary baseline bundle (`schema_version = 1`) and `manifest.json` |
| `resources/en_base/packs/` | 6 domain vocabulary packs: `programming`, `medicine`, `finance`, `law`, `business`, `academic` |
| `tests/` | Held-out corpus quality gate (`test_engine_quality_heldout.py`); the full curated suite lives in `TypenApp/typen` |

---

## Building & Verifying the Language Bundle

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# Compile and run the golden corpus regression gate
python -m pipeline.cli resources/en_base

# Run the held-out quality test suite
pytest
```

---

## Reporting Missed Typos or False Positives

Open a [**Correction Report**](https://github.com/TypenApp/language-data/issues/new?template=correction_report.yml) if you find:
1. A misspelling that Typen did not fix.
2. A valid word, proper noun, or technical term that Typen wrongly corrected.
3. Terms to add to one of the 6 domain vocabulary packs (`resources/en_base/packs/*.pack.json`).

## Licence

MIT. See [`LICENSE`](LICENSE) and [`pipeline/data/external/README.md`](pipeline/data/external/README.md) for SCOWL/ESDB word list notices.
"""
    (repo_dir / "README.md").write_text(readme, encoding="utf-8")

    ci_yml = """name: Language Data CI

on:
  push:
    branches: [main, master]
  pull_request:

jobs:
  quality-gate:
    name: Lexicon compile & held-out quality gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: ruff check pipeline tests
      - run: python -m pytest tests -q
"""
    workflows_dir = repo_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "ci.yml").write_text(ci_yml, encoding="utf-8")

    release_yml = """name: Publish Language Resource Bundle

on:
  push:
    tags: ["v*"]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  bundle:
    name: Package Zstandard bundle & domain packs
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: python -m pytest tests -q
      - name: Build .tar.zst archive and SHA256SUMS.txt
        run: |
          python - <<'PY'
          import hashlib, json, pathlib
          from pipeline.sign_release import create_zstd_bundle_archive
          root = pathlib.Path("resources/en_base")
          manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
          ver = manifest["version"]
          out = pathlib.Path("dist")
          out.mkdir(exist_ok=True)
          archive_name = f"en_base-{ver}.tar.zst"
          sha, size = create_zstd_bundle_archive(root, out / archive_name)
          sums = [f"{sha}  {archive_name}"]
          for pack in sorted((root / "packs").glob("*.pack.json")):
              dst = out / pack.name
              dst.write_bytes(pack.read_bytes())
              sums.append(f"{hashlib.sha256(dst.read_bytes()).hexdigest()}  {pack.name}")
          (out / "SHA256SUMS.txt").write_text("\\n".join(sums) + "\\n", encoding="ascii")
          PY
      - name: Publish GitHub Release
        if: startsWith(github.ref, 'refs/tags/v')
        uses: softprops/action-gh-release@v2
        with:
          files: dist/*
          generate_release_notes: true
"""
    (workflows_dir / "release.yml").write_text(release_yml, encoding="utf-8")
    return repo_dir


def build_model_resources_repo(out_dir: Path) -> Path:
    """Assemble `TypenApp/model-resources` (Layer 2 Local AI model catalog, descriptors, and signing tools)."""
    repo_dir = out_dir / "model-resources"
    if repo_dir.exists():
        _rmtree(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    _copy_common_community_files(repo_dir)
    _copy_file(ROOT / ".gitignore", repo_dir / ".gitignore")
    _copy_file(ROOT / ".github" / "FUNDING.yml", repo_dir / ".github" / "FUNDING.yml")
    _copy_file(
        ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md", repo_dir / ".github" / "PULL_REQUEST_TEMPLATE.md"
    )

    descriptors = [
        {
            "model_id": "grammar-onnx-int8-small",
            "version": "1.0.0",
            "released_at": "2026-11-01T00:00:00Z",
            "format": "onnx-int8",
            "min_ram_mb": 4096,
            "recommended_accelerators": ["DirectML", "CoreML", "CPU-AVX2"],
            "size_bytes": 68157440,
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "status": "descriptor-published",
            "description": "Quantized INT8 ONNX sentence grammar evaluation model for machines with >= 4 GB RAM.",
        },
        {
            "model_id": "rewrite-gguf-q4-360m",
            "version": "1.0.0",
            "released_at": "2026-11-01T00:00:00Z",
            "format": "gguf-q4",
            "min_ram_mb": 16384,
            "recommended_accelerators": ["DirectML", "CoreML", "CPU-AVX2"],
            "size_bytes": 241172480,
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "status": "descriptor-published",
            "description": "4-bit GGUF local sentence rewrite and style refinement model for machines with >= 16 GB RAM and 8+ cores.",
        },
    ]

    desc_dir = repo_dir / "descriptors"
    desc_dir.mkdir(parents=True, exist_ok=True)
    for d in descriptors:
        (desc_dir / f"{d['model_id']}.json").write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")

    catalog = {
        "schema_version": 1,
        "repository": "TypenApp/model-resources",
        "ed25519_public_key_hex": ROOT_PUBLIC_KEY_HEX,
        "idle_unload_seconds": 300,
        "pause_pill_min_idle_ms": 400,
        "models": descriptors,
    }
    (repo_dir / "model-catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")

    sign_script = f'''"""
Sign and verify Layer 2 Local AI model descriptors (`LocalModelDescriptor`)
using Typen's canonical Ed25519 signature scheme.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ROOT_PUBLIC_KEY_HEX = "{ROOT_PUBLIC_KEY_HEX}"
CANONICAL_KEYS = ("model_id", "version", "released_at", "format", "min_ram_mb", "size_bytes", "sha256")


def canonical_descriptor_dict(raw: dict[str, object]) -> dict[str, object]:
    return {{k: raw[k] for k in CANONICAL_KEYS}}


def canonicalize_json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_descriptor(descriptor: dict[str, object], private_key_hex: str) -> str:
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    raw = canonicalize_json_bytes(canonical_descriptor_dict(descriptor))
    return base64.b64encode(priv.sign(raw)).decode("ascii")


def verify_descriptor(
    descriptor: dict[str, object],
    signature_b64: str,
    public_key_hex: str = ROOT_PUBLIC_KEY_HEX,
) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        raw = canonicalize_json_bytes(canonical_descriptor_dict(descriptor))
        pub.verify(base64.b64decode(signature_b64), raw)
        return True
    except Exception:
        return False


def validate_catalog(catalog_path: Path) -> int:
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["ed25519_public_key_hex"] == ROOT_PUBLIC_KEY_HEX
    models = data["models"]
    assert len(models) >= 2
    for m in models:
        canon = canonical_descriptor_dict(m)
        assert len(str(canon["sha256"])) == 64
        assert int(canon["min_ram_mb"]) >= 4096
    print(f"Validated {{len(models)}} model descriptors in {{catalog_path}}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("model-catalog.json"))
    args = parser.parse_args(argv)
    return validate_catalog(args.catalog)


if __name__ == "__main__":
    raise SystemExit(main())
'''
    scripts_dir = repo_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "sign_model_release.py").write_text(sign_script, encoding="utf-8")

    test_catalog = """from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.sign_model_release import (
     canonical_descriptor_dict,
    sign_descriptor,
    validate_catalog,
    verify_descriptor,
)

ROOT = Path(__file__).resolve().parent.parent


def test_model_catalog_and_descriptors_are_valid() -> None:
    assert validate_catalog(ROOT / "model-catalog.json") == 0
    catalog = json.loads((ROOT / "model-catalog.json").read_text(encoding="utf-8"))
    for model in catalog["models"]:
        desc_file = ROOT / "descriptors" / f"{model['model_id']}.json"
        assert desc_file.exists()
        assert json.loads(desc_file.read_text(encoding="utf-8")) == model


def test_ed25519_roundtrip_on_model_descriptor() -> None:
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes_raw().hex()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    desc = json.loads((ROOT / "descriptors" / "grammar-onnx-int8-small.json").read_text(encoding="utf-8"))
    sig = sign_descriptor(desc, priv_hex)
    assert verify_descriptor(desc, sig, pub_hex)
    tampered = dict(canonical_descriptor_dict(desc), size_bytes=123)
    assert not verify_descriptor(tampered, sig, pub_hex)
"""
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_model_catalog.py").write_text(test_catalog, encoding="utf-8")

    pyproject = """[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "typen-model-resources"
version = "1.0.0"
description = "Optional Layer 2 on-device ONNX/GGUF model descriptors and Ed25519 signing tools for Typen"
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}
authors = [{name = "Omnii"}]
dependencies = [
    "cryptography>=42.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "-q"
"""
    (repo_dir / "pyproject.toml").write_text(pyproject, encoding="utf-8")

    readme = f"""# Typen Local AI Model Resources (`TypenApp/model-resources`)

Optional **Layer 2 On-Device AI** model descriptors, hardware capability profiles, and Ed25519 manifest signing tools for [**Typen**](https://github.com/TypenApp/typen).

- **Main Application**: [`TypenApp/typen`](https://github.com/TypenApp/typen)
- **Language Data**: [`TypenApp/language-data`](https://github.com/TypenApp/language-data)
- **Documentation**: [`TypenApp/docs`](https://github.com/TypenApp/docs)

---

## How Layer 2 Local AI Works in Typen

Typen separates real-time keystroke correction from heavy neural inference so typing latency never degrades:

1. **Layer 1 (Always-On, `< 0.4ms`)**: Deterministic `mmap` lexicon + SymSpell + trigram context model (ships inside `TypenApp/typen` and `TypenApp/language-data`).
2. **Layer 2 (Local AI, On-Device)**: Quantized `ONNX` / `GGUF` sentence grammar and rewrite models managed by `LocalModelManager` (`src/autocorrect/ai/local_model_manager.py`) and verified by `ModelUpdater` (`src/autocorrect/updates/model_updater.py`).
   - Triggered **only** after a `>= 400ms` pause at a sentence boundary (via a non-focus-stealing Pause Pill) or via the explicit `Ctrl+Shift+R` hotkey.
   - Automatically unloads from RAM after `300s` (`MODEL_IDLE_UNLOAD_SECONDS`) of inactivity.

---

## Model Tiers & Hardware Profiles

| Model ID | Format | Minimum RAM | Recommended Hardware | Purpose |
| --- | --- | --- | --- | --- |
| `grammar-onnx-int8-small` | `onnx-int8` | 4,096 MB (4 GB) | DirectML / CoreML / CPU-AVX2 | Fast local sentence grammar verification |
| `rewrite-gguf-q4-360m` | `gguf-q4` | 16,384 MB (16 GB), 8+ cores | DirectML / CoreML / CPU-AVX2 | Local sentence rewrite and style refinement |

---

## Cryptographic Verification

Every model download is verified by `ModelUpdater.install_model_bytes()` before installation:
1. **Ed25519 Signature Check**: Canonical JSON (`model_id`, `version`, `released_at`, `format`, `min_ram_mb`, `size_bytes`, `sha256`) is verified against the embedded root public key:
   ```text
   {ROOT_PUBLIC_KEY_HEX}
   ```
2. **SHA-256 Checksum Verification**: Model bytes are hashed and compared against `descriptor.sha256` before atomic placement into the user's models directory.

## Validating the Catalog

```bash
pip install -e ".[dev]"
python scripts/sign_model_release.py --catalog model-catalog.json
pytest
```

## Licence

MIT. See [`LICENSE`](LICENSE).
"""
    (repo_dir / "README.md").write_text(readme, encoding="utf-8")

    ci_yml = """name: Model Resources CI

on:
  push:
    branches: [main, master]
  pull_request:

jobs:
  validate:
    name: Validate model catalog & Ed25519 signing
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install -e ".[dev]"
      - run: python scripts/sign_model_release.py --catalog model-catalog.json
      - run: pytest
"""
    workflows_dir = repo_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "ci.yml").write_text(ci_yml, encoding="utf-8")
    return repo_dir


def build_docs_repo(out_dir: Path) -> Path:
    """Assemble `TypenApp/docs` (Markdown guides synced from `site/src/data/docs.ts`)."""
    repo_dir = out_dir / "docs"
    if repo_dir.exists():
        _rmtree(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    _copy_common_community_files(repo_dir)
    _copy_file(ROOT / ".github" / "FUNDING.yml", repo_dir / ".github" / "FUNDING.yml")
    _copy_file(
        ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md", repo_dir / ".github" / "PULL_REQUEST_TEMPLATE.md"
    )

    sync_docs(repo_dir, check=False)

    ci_yml = """name: Docs CI

on:
  push:
    branches: [main, master]
  pull_request:

jobs:
  lint-docs:
    name: Verify Markdown guides & relative links
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Check required guides and relative links
        run: |
          python - <<'PY'
          import pathlib, re
          root = pathlib.Path(".")
          required = [
              "README.md",
              "getting-started.md",
              "core-engine.md",
              "customisation.md",
              "productivity.md",
              "ai-intelligence.md",
              "security-privacy.md",
              "open-source.md",
              "cli-reference.md",
          ]
          for name in required:
              p = root / name
              assert p.exists() and p.stat().st_size > 200, f"Missing or empty: {name}"
          readme = (root / "README.md").read_text(encoding="utf-8")
          for link in re.findall(r"\\]\\(([a-z0-9-]+\\.md)\\)", readme):
              assert (root / link).exists(), f"Broken link in README.md: {link}"
          print(f"Verified {len(required)} documentation files.")
          PY
"""
    workflows_dir = repo_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    (workflows_dir / "ci.yml").write_text(ci_yml, encoding="utf-8")
    return repo_dir


def build_all_org_repos(out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    built = {
        ".github": build_dot_github_repo(out_dir),
        "typen": build_typen_repo(out_dir),
        "language-data": build_language_data_repo(out_dir),
        "model-resources": build_model_resources_repo(out_dir),
        "docs": build_docs_repo(out_dir),
    }
    manifest_path = out_dir / "org-repos-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "organisation": ORG_NAME,
                "organisation_url": ORG_URL,
                "repositories": REPO_SPECS,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return built


def _get_github_token() -> str:
    env_tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env_tok:
        return env_tok.strip()
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input=b"protocol=https\nhost=github.com\n\n",
        capture_output=True,
        check=True,
    )
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("Could not obtain GitHub token from GITHUB_TOKEN or git credential fill")


def publish_org_repos(
    built: dict[str, Path],
    *,
    org: str = ORG_NAME,
    dry_run: bool = False,
) -> None:
    headers: dict[str, str] = {}
    if not dry_run:
        token = _get_github_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        with httpx.Client(headers=headers, timeout=30.0) as client:
            org_resp = client.patch(
                f"https://api.github.com/orgs/{org}",
                json={
                    "name": "Typen",
                    "description": "Free, open-source, offline-first system-wide autocorrect for Windows, macOS and Linux.",
                    "blog": "https://autocorrect-desktop.vercel.app",
                },
            )
            if org_resp.is_success:
                print(f"Updated organisation profile: https://github.com/{org}")

    for spec in REPO_SPECS:
        repo_name = str(spec["repo_name"])
        full_slug = f"{org}/{repo_name}"
        remote_url = f"https://github.com/{full_slug}.git"
        repo_dir = built[repo_name]

        git_dir = repo_dir / ".git"
        if git_dir.exists():
            _rmtree(git_dir)

        subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Omnii"], cwd=repo_dir, check=True)
        subprocess.run(
            ["git", "config", "user.email", "omnii@users.noreply.github.com"], cwd=repo_dir, check=True
        )
        subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Initial release for {full_slug}"],
            cwd=repo_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=repo_dir, check=True)

        if dry_run:
            print(f"[DryRun] Initialized git repository for {full_slug} at {repo_dir}")
            continue

        with httpx.Client(headers=headers, timeout=30.0) as client:
            check = client.get(f"https://api.github.com/repos/{full_slug}")
            if check.status_code == 404:
                print(f"Creating public repository {full_slug}...")
                create_resp = client.post(
                    f"https://api.github.com/orgs/{org}/repos",
                    json={
                        "name": repo_name,
                        "description": spec["description"],
                        "homepage": spec["homepage"],
                        "private": False,
                        "has_issues": True,
                        "has_projects": False,
                        "has_wiki": False,
                    },
                )
                create_resp.raise_for_status()
            else:
                print(f"Updating metadata for {full_slug}...")
                patch_resp = client.patch(
                    f"https://api.github.com/repos/{full_slug}",
                    json={
                        "description": spec["description"],
                        "homepage": spec["homepage"],
                        "private": False,
                        "has_issues": True,
                    },
                )
                patch_resp.raise_for_status()

        print(f"Pushing main branch to {remote_url}...")
        subprocess.run(["git", "push", "-u", "origin", "main", "--force"], cwd=repo_dir, check=True)
        if repo_name == "typen":
            subprocess.run(["git", "push", "origin", "main:master", "--force"], cwd=repo_dir, check=True)

        with httpx.Client(headers=headers, timeout=30.0) as client:
            client.put(
                f"https://api.github.com/repos/{full_slug}/topics",
                json={"names": spec["topics"]},
            )
        print(f"Published https://github.com/{full_slug}")

    if not dry_run:
        with httpx.Client(headers=headers, timeout=30.0) as client:
            enable_repo_sponsorships(client, org=org, repos=[str(s["repo_name"]) for s in REPO_SPECS])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for assembled repos"
    )
    parser.add_argument("--org", default=ORG_NAME, help="GitHub organisation handle")
    parser.add_argument(
        "--publish", action="store_true", help="Create/update and push repositories on GitHub"
    )
    parser.add_argument("--dry-run", action="store_true", help="Initialize git repos locally without pushing")
    args = parser.parse_args(argv)

    built = build_all_org_repos(args.out_dir)
    for repo_name, path in built.items():
        print(f"Assembled {args.org}/{repo_name:<18} -> {path}")

    if args.publish or args.dry_run:
        publish_org_repos(built, org=args.org, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
